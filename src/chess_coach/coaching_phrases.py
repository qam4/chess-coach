"""Single source of truth for coaching sentences composed from engine facts.

The engine (Blunder) emits structured facts (tactic/threat types with
``squares``/``pieces``/``in_pv``/``uci_move``, pawn structure, threat map,
eval breakdown) plus a few short labels. This module turns those
*structured* facts into the canonical natural-language sentences shown to
the student and fed to the LLM — never by reading the engine's own
``description`` prose. Both consumers (``prompts`` for the LLM path and
``coaching_templates`` for the UI) call these functions, so wording can
never diverge between them.

Design rules (see ``.kiro/specs/client-side-coaching-text``):
- Pure: no engine, no network, no LLM. Deterministic.
- Facts only: side and piece names are derived from the board (FEN) +
  structured squares; engine ``description`` strings are never consumed.
- Total: unknown / malformed input yields a safe generic sentence — the
  functions never raise and never return an empty string for a present
  fact.
"""

from __future__ import annotations

import chess

from chess_coach.models import (
    HangingPiece,
    KingSafety,
    PawnFeatures,
    PositionReport,
    TacticalMotif,
    Threat,
)

# Below this many pieces on the board, king-safety commentary is noise
# (middlegame heuristics do not apply in a bare endgame) — see BUG-009 and
# the coaching-philosophy relevance tiers.
_KING_SAFETY_ENDGAME_PIECE_FLOOR = 6

_PIECE_NAMES = {
    chess.PAWN: "pawn",
    chess.KNIGHT: "knight",
    chess.BISHOP: "bishop",
    chess.ROOK: "rook",
    chess.QUEEN: "queen",
    chess.KING: "king",
}


# ---------------------------------------------------------------------------
# Board-derived helpers (facts from the position, never from engine prose)
# ---------------------------------------------------------------------------


def _board(fen: str) -> chess.Board | None:
    try:
        return chess.Board(fen)
    except ValueError:
        return None


def _color_at(board: chess.Board | None, square: str) -> str | None:
    """Return "White"/"Black" for the piece on ``square``, or None."""
    if board is None:
        return None
    try:
        sq = chess.parse_square(square)
    except ValueError:
        return None
    color = board.color_at(sq)
    if color is None:
        return None
    return "White" if color == chess.WHITE else "Black"


def _piece_name_at(board: chess.Board | None, square: str) -> str | None:
    """Return the lowercase piece name on ``square`` (e.g. "rook"), or None."""
    if board is None:
        return None
    try:
        sq = chess.parse_square(square)
    except ValueError:
        return None
    piece = board.piece_at(sq)
    if piece is None:
        return None
    return _PIECE_NAMES.get(piece.piece_type)


def _fmt_move(uci: str) -> str:
    """Render a UCI move for humans: "e1e8" -> "e1-e8"; passthrough otherwise."""
    if len(uci) >= 4 and uci[:2].isalnum() and uci[2:4].isalnum():
        return f"{uci[:2]}-{uci[2:4]}"
    return uci


def _cap(sentence: str) -> str:
    return sentence[:1].upper() + sentence[1:] if sentence else sentence


def _tok(items: list[str], i: int, fallback: str = "") -> str:
    """Safe indexed access into a structured list (piece/square tokens)."""
    return items[i] if 0 <= i < len(items) else fallback


# ---------------------------------------------------------------------------
# Tactics
# ---------------------------------------------------------------------------


def _tactic_core(t: TacticalMotif) -> str:
    """The type-specific clause of a tactic, from structured pieces/squares."""
    p = t.pieces
    if t.type == "discovered_attack":
        attacker, target, mover = _tok(p, 0), _tok(p, 1), _tok(p, 2)
        if attacker and target and mover:
            return f"a discovered attack: moving {mover} reveals {attacker} hitting {target}"
        return "a discovered attack"
    if t.type == "fork":
        forker, targets = _tok(p, 0), [x for x in p[1:] if x]
        if forker and targets:
            return f"a fork: {forker} attacks {' and '.join(targets)}"
        return "a fork"
    if t.type == "pin":
        pinner, pinned, behind = _tok(p, 0), _tok(p, 1), _tok(p, 2)
        if pinner and pinned and behind:
            return f"a pin: {pinner} pins {pinned} to {behind}"
        if pinner and pinned:
            return f"a pin: {pinner} pins {pinned}"
        return "a pin"
    if t.type == "skewer":
        skewerer, front, back = _tok(p, 0), _tok(p, 1), _tok(p, 2)
        if skewerer and front and back:
            return f"a skewer: {skewerer} skewers {front} and {back}"
        return "a skewer"
    if t.type == "back_rank_threat":
        attacker = _tok(p, 0)
        if attacker:
            return f"a back-rank threat: {attacker} targets the back rank"
        return "a back-rank threat"
    if t.type == "overloaded_piece":
        piece = _tok(p, 0)
        return f"an overloaded piece: {piece} is overloaded" if piece else "an overloaded piece"
    # Unknown type — safe generic clause.
    words = t.type.replace("_", " ").strip() or "tactic"
    return f"a {words}"


def describe_tactic_core(t: TacticalMotif) -> str:
    """The type-specific clause of a tactic, without side or PV framing.

    e.g. ``"a fork: Nc7 attacks Ra8 and Ke8"`` — for contexts that supply
    their own lead, such as "You missed {core}" or "Watch out: {core}".
    Composed from structured ``pieces``/``squares`` only.
    """
    return _tactic_core(t)


def describe_tactic(t: TacticalMotif, board: chess.Board | None) -> str:
    """Compose a coaching sentence for a tactical motif from structured data.

    Side is derived from the acting piece on ``squares[0]``; the on-board
    vs in-PV distinction is rendered as a clear phrase from ``in_pv`` (never
    the engine token "in PV").
    """
    core = _tactic_core(t)
    side = _color_at(board, _tok(t.squares, 0))
    if side:
        prefix = f"In the main line, {side} gets " if t.in_pv else f"{side} has "
    else:
        prefix = "In the main line, there is " if t.in_pv else "There is "
    return _cap(f"{prefix}{core}.")


# ---------------------------------------------------------------------------
# Threats
# ---------------------------------------------------------------------------


def describe_threat(th: Threat, board: chess.Board | None) -> str:
    """Compose a coaching sentence for a threat from structured data.

    The move comes from ``uci_move`` (never parsed from prose); if absent,
    the sentence degrades gracefully to a move-less form.
    """
    side = _color_at(board, th.source_square)
    piece = _piece_name_at(board, th.source_square) or "piece"
    owner = f"{side}'s {piece}" if side else f"the {piece}"
    targets = [x for x in th.target_squares if x]
    target = targets[0] if targets else ""
    move = _fmt_move(th.uci_move) if th.uci_move else ""

    if th.type == "check":
        base = f"{owner} can give check"
        return _cap(f"{base} with {move}." if move else f"{base}.")
    if th.type == "capture":
        base = f"{owner} can capture on {target}" if target else f"{owner} can win material"
        return _cap(f"{base}.")
    if th.type == "pin":
        return _cap(f"{owner} pins the piece on {target}." if target else f"{owner} sets up a pin.")
    if th.type == "skewer":
        return _cap(f"{owner} skewers through {target}." if target else f"{owner} sets up a skewer.")
    if th.type == "fork":
        return _cap(f"{owner} forks {' and '.join(targets)}." if targets else f"{owner} sets up a fork.")
    if th.type == "discovered_attack":
        return _cap(f"{owner} can uncover an attack.")
    # Unknown type — safe generic.
    if targets:
        return _cap(f"{owner} threatens {', '.join(targets)}.")
    return _cap(f"{owner} has a threat.")


# ---------------------------------------------------------------------------
# Hanging pieces / pawn structure / piece safety
# ---------------------------------------------------------------------------


def describe_hanging(hp: HangingPiece) -> str:
    """Compose a sentence for an undefended piece from structured data."""
    side = hp.color.capitalize() if hp.color else ""
    who = f"{side}'s {hp.piece}" if side else f"the {hp.piece}"
    return _cap(f"{who} on {hp.square} is undefended.")


def describe_pawn_structure(pf: PawnFeatures, side: str) -> str | None:
    """Compose a pawn-structure sentence for one side, or None if unremarkable."""
    label = side.capitalize()
    parts: list[str] = []
    if pf.isolated:
        parts.append(f"isolated pawn(s) on the {', '.join(pf.isolated)}-file(s)")
    if pf.doubled:
        parts.append(f"doubled pawn(s) on the {', '.join(pf.doubled)}-file(s)")
    if pf.passed:
        parts.append(f"passed pawn(s) on the {', '.join(pf.passed)}-file(s)")
    if not parts:
        return None
    return _cap(f"{label} has {'; '.join(parts)}.")


def describe_king_safety(ks: KingSafety, side: str) -> str | None:
    """Compose a king-safety sentence from the structured fields, or None.

    Built entirely from the engine's structured king-safety fields (castling
    status, missing shield files, open-file-near-king, pawn storm) — never
    from ``ks.description``. Returns None when there is nothing coaching-worthy
    (e.g. a castled king with a solid shield); an uncastled king that still
    has its shield is normal in the opening and is not flagged on its own.

    Callers gate low-material endgames with :func:`king_safety_relevant`
    before calling this — middlegame king-safety heuristics are noise there.
    """
    label = side.capitalize()
    parts: list[str] = []
    if ks.castling_status == "stuck_in_center":
        parts.append("stuck in the center")
    elif ks.castling_status == "displaced":
        parts.append(f"displaced to {ks.king_square}" if ks.king_square else "displaced")
    if ks.missing_shield_files:
        files = ", ".join(ks.missing_shield_files)
        parts.append(f"short of pawn cover on the {files} file(s)")
    if ks.open_file_near_king:
        parts.append("exposed on a nearby open file")
    if ks.pawn_storm:
        parts.append("facing a pawn storm")
    if not parts:
        return None
    return _cap(f"{label}'s king is {', '.join(parts)}.")


# ---------------------------------------------------------------------------
# Eval assessment (ported from the template's _eval_summary — structured)
# ---------------------------------------------------------------------------


def describe_eval(report: PositionReport) -> str:
    """Summarize the overall evaluation in plain language, from structured cp."""
    cp = report.eval_cp
    abs_cp = abs(cp)
    if abs_cp < 30:
        assessment = "The position is roughly equal."
    else:
        side = "White" if cp > 0 else "Black"
        if abs_cp < 100:
            assessment = f"{side} has a slight edge ({cp / 100:+.2f} pawns)."
        elif abs_cp < 300:
            assessment = f"{side} has a clear advantage ({cp / 100:+.2f} pawns)."
        else:
            assessment = f"{side} is winning ({cp / 100:+.2f} pawns)."

    eb = report.eval_breakdown
    factors = [
        (abs(eb.mobility), eb.mobility, "piece activity"),
        (abs(eb.king_safety), eb.king_safety, "king safety"),
        (abs(eb.pawn_structure), eb.pawn_structure, "pawn structure"),
    ]
    factors.sort(reverse=True)
    if abs_cp > 30:
        top_abs, top_val, top_name = factors[0]
        if top_abs > 30:
            top_better = "White" if top_val > 0 else "Black"
            eval_side = "White" if cp > 0 else "Black"
            if top_better == eval_side:
                assessment += f" The main factor is {top_name} ({top_better} is better)."
            else:
                for _, val, name in factors[1:]:
                    aligned = "White" if val > 0 else "Black"
                    if abs(val) > 20 and aligned == eval_side:
                        assessment += f" {eval_side}'s {name} outweighs {top_better}'s {top_name} edge."
                        break
    return assessment


# ---------------------------------------------------------------------------
# Presentation policy (pure, structured — no prose, no engine)
# ---------------------------------------------------------------------------


def _tactic_identity(t: TacticalMotif) -> tuple[str, ...]:
    """Structured motif identity, ignoring which move *executes* the tactic.

    A discovered attack keeps the same revealed-attacker + target across PV
    variants while the mover square varies, so key on ``squares[0:2]``; other
    motifs key on their full square list.
    """
    if t.type == "discovered_attack" and len(t.squares) >= 2:
        return (t.type, t.squares[0], t.squares[1])
    if t.squares:
        return (t.type, *t.squares)
    return (t.type,)


def select_tactics(tactics: list[TacticalMotif]) -> list[TacticalMotif]:
    """Collapse tactic variants to one per motif, preferring the on-board one.

    The engine reports a motif on-board and again inside each PV line that
    executes it; those collapse to a single entry. The on-board (non-PV)
    detection is preferred as the general, reliable statement; a PV-only
    motif is kept as fallback. First-seen order is preserved.
    """
    best: dict[tuple[str, ...], TacticalMotif] = {}
    order: list[tuple[str, ...]] = []
    for t in tactics:
        key = _tactic_identity(t)
        existing = best.get(key)
        if existing is None:
            best[key] = t
            order.append(key)
        elif existing.in_pv and not t.in_pv:
            best[key] = t  # on-board beats a PV variant
    return [best[k] for k in order]


def suppress_threats_echoing_tactics(
    threats: list[Threat],
    tactics: list[TacticalMotif],
) -> list[Threat]:
    """Drop threats that merely restate a shown tactic (same type + source).

    A pin/skewer/fork/discovered attack the engine emits as BOTH a tactic and
    a threat should be told once (as the richer tactic). Distinct threats
    (check, capture) are unaffected. Matching is structural, not textual.
    """
    kept: list[Threat] = []
    for th in threats:
        echoes = any(th.type == t.type and th.source_square in t.squares for t in tactics)
        if not echoes:
            kept.append(th)
    return kept


def king_safety_relevant(report: PositionReport) -> bool:
    """Whether king-safety commentary is coaching-relevant for this position.

    Suppressed in low-material endgames, where middlegame king-safety
    heuristics (missing pawn shield, open files near the king) are noise
    rather than useful coaching (BUG-009 / coaching-philosophy tiers).
    """
    board = _board(report.fen)
    if board is None:
        return True
    piece_count = len(board.piece_map())
    return piece_count > _KING_SAFETY_ENDGAME_PIECE_FLOOR
