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

import logging
from dataclasses import dataclass

import chess

from chess_coach.models import (
    HangingPiece,
    KingSafety,
    PawnFeatures,
    PositionReport,
    TacticalMotif,
    Threat,
)

logger = logging.getLogger(__name__)

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


def uci_to_san(fen: str, uci: str) -> str:
    """Convert a single UCI move to SAN for the given position.

    Models read SAN — which names the piece (e.g. ``Ke7``, ``O-O``, ``Qg4``) —
    far more reliably than raw coordinates like ``e1g1``. Shared by the prompt
    renderer and the move menu so there is one converter.

    Unlike a move *line* (which is truncated at the first unreplayable move
    rather than showing coordinates), a single move usually fills a required
    field — the student's move, the engine's best move — so there is nothing
    better to show than the raw UCI if it cannot be converted. That fallback is
    kept, but WARNS: it means the move is illegal in the given position, i.e.
    the caller passed the wrong base position or the engine sent a bad datum.
    """
    try:
        board = chess.Board(fen)
        move = chess.Move.from_uci(uci)
        if move in board.legal_moves:
            return board.san(move)
    except (ValueError, AssertionError):
        pass
    logger.warning("uci_to_san could not convert %r in %r — emitting raw coordinates", uci, fen)
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


def describe_pawn_structure_from_board(board: chess.Board | None) -> str:
    """Board-derived isolated/doubled pawn facts for both sides, as text.

    Composed directly from ``python-chess`` (never the engine's ``PawnFeatures``
    or any engine-tunable label), so the coach can state which pawns are
    isolated/doubled instead of guessing — the same grounding idea as the
    placement block, which stopped piece-location hallucinations. A pawn is
    *isolated* when no friendly pawn stands on either adjacent file; a file is
    *doubled* when it holds two or more friendly pawns.

    Returns an empty string for a missing/invalid board or a pawnless position
    (the caller then omits the section). Otherwise always lists both sides —
    including an explicit "none" — so the model is told what is NOT weak, too.
    """
    if board is None:
        return ""
    if not (board.pieces(chess.PAWN, chess.WHITE) or board.pieces(chess.PAWN, chess.BLACK)):
        return ""
    lines = ["--- Pawn structure (from the board) ---"]
    for color in (chess.WHITE, chess.BLACK):
        squares = sorted(board.pieces(chess.PAWN, color))
        files = [chess.square_file(sq) for sq in squares]
        isolated = [
            chess.square_name(sq)
            for sq in squares
            if (chess.square_file(sq) - 1) not in files and (chess.square_file(sq) + 1) not in files
        ]
        doubled = sorted({chess.FILE_NAMES[f] for f in files if files.count(f) >= 2})
        label = "White" if color == chess.WHITE else "Black"
        iso = ", ".join(isolated) if isolated else "none"
        dbl = ", ".join(f"{f}-file" for f in doubled) if doubled else "none"
        lines.append(f"{label}: isolated pawns: {iso}; doubled pawns: {dbl}")
    return "\n".join(lines)


_MINOR_START_SQUARES = {
    (chess.WHITE, chess.KNIGHT): {chess.B1, chess.G1},
    (chess.WHITE, chess.BISHOP): {chess.C1, chess.F1},
    (chess.BLACK, chess.KNIGHT): {chess.B8, chess.G8},
    (chess.BLACK, chess.BISHOP): {chess.C8, chess.F8},
}
_PIECE_LETTER = {
    chess.KING: "K",
    chess.QUEEN: "Q",
    chess.ROOK: "R",
    chess.BISHOP: "B",
    chess.KNIGHT: "N",
    chess.PAWN: "P",
}
_PIECE_ORDER = [chess.KING, chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN]


def minor_is_developed(board: chess.Board | None, square: str) -> bool | None:
    """Whether the minor piece on ``square`` has left its starting square.

    Returns ``True`` if a knight/bishop stands on ``square`` off its home
    square (developed), ``False`` if it is still on a home square, and ``None``
    if the square is empty or does not hold a knight/bishop. Shared by
    :func:`describe_placement` and the output fidelity checker so the
    "developed vs still-home" fact has one source.
    """
    if board is None:
        return None
    try:
        sq = chess.parse_square(square)
    except ValueError:
        return None
    piece = board.piece_at(sq)
    if piece is None or piece.piece_type not in (chess.KNIGHT, chess.BISHOP):
        return None
    start = _MINOR_START_SQUARES[(piece.color, piece.piece_type)]
    return sq not in start


def describe_placement(board: chess.Board | None) -> str:
    """Render an explicit, plain-language piece placement for both sides.

    The engine's only complete placement is the FEN, which LLMs (especially
    small ones) cannot reliably decode — so the coach was inventing pieces.
    This gives the model the board as text it can actually use: a compact
    per-side piece list plus a developed / still-home summary of the minor
    pieces (the signal that stops "your knight is undeveloped" errors when it
    is not). Deterministic, so it never hallucinates.

    Returns an empty string for a missing/invalid board (caller omits the
    section).
    """
    if board is None:
        return ""
    lines = [f"{'White' if board.turn == chess.WHITE else 'Black'} to move."]
    piece_map = board.piece_map()
    for color in (chess.WHITE, chess.BLACK):
        by_type: dict[int, list[str]] = {pt: [] for pt in _PIECE_ORDER}
        for sq, piece in piece_map.items():
            if piece.color == color:
                by_type[piece.piece_type].append(chess.square_name(sq))
        parts = [f"{_PIECE_LETTER[pt]} {' '.join(sorted(by_type[pt]))}" for pt in _PIECE_ORDER if by_type[pt]]
        developed: list[str] = []
        home: list[str] = []
        for pt in (chess.KNIGHT, chess.BISHOP):
            start = _MINOR_START_SQUARES[(color, pt)]
            squares = sorted(sq for sq, piece in piece_map.items() if piece.color == color and piece.piece_type == pt)
            for sq in squares:
                tag = f"{_PIECE_LETTER[pt]}{chess.square_name(sq)}"
                (home if sq in start else developed).append(tag)
        label = "White" if color == chess.WHITE else "Black"
        lines.append(f"{label}: {', '.join(parts)}")
        # Repeat the side on the summary line. It reads as redundant under the label
        # above, and it is — but a model reading this line in isolation had no owner
        # for it, and duly told a student that the opponent's bishop was their own
        # (v27 ply 44). Ambiguity in a fact block is where fabrication starts.
        lines.append(
            f"  {label} developed minors: {', '.join(developed) or 'none'}; still home: {', '.join(home) or 'none'}"
        )
    return "\n".join(lines)


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


# ---------------------------------------------------------------------------
# Move menu + soundness tagging (structured — no prose, no engine calls)
# ---------------------------------------------------------------------------

# Single source of the centipawn boundaries for "how far from best is still
# acceptable". Shared by the move-menu tags below and ``Coach.classify_move``
# (good/inaccuracy/blunder), so the numbers live in exactly one place.
# Below this, the student's move and the engine's are not meaningfully different
# and NO comparison should be offered. A blind audit of what makes coaching good
# (docs/coaching-standard-audit.md) puts "manufactures fault on genuinely good
# moves" in the actively-harmful tier — it trains the student to distrust the
# instincts you most want to reinforce. Measured on one game, 10 of 44 turns did
# exactly that, at drops of 0, 0, 0, 0, 0, 0, 6, 17 and 17cp.
#
# 25 is deliberately conservative: it covers every observed case and stays well
# inside the "sound" band rather than redefining it. The audit argues for roughly a
# pawn, which would swallow the whole inaccuracy band — a much larger behavioural
# change than the evidence so far supports.
EQUAL_MAX_DROP_CP = 25
SOUND_MAX_DROP_CP = 50
DUBIOUS_MAX_DROP_CP = 100


def classify_drop(drop_cp: int) -> str:
    """Soundness tag for a candidate move from its eval-drop-from-best.

    ``sound`` (drop ≤ 50 cp), ``dubious`` (51–100 cp), ``blunder`` (> 100 cp).
    The top line is tagged ``best`` by :func:`build_move_menu` regardless of
    drop; this function classifies the non-best candidates. Total: any integer
    (including negatives, which callers clamp to 0) yields a tag.
    """
    if drop_cp <= SOUND_MAX_DROP_CP:
        return "sound"
    if drop_cp <= DUBIOUS_MAX_DROP_CP:
        return "dubious"
    return "blunder"


@dataclass(frozen=True)
class MenuMove:
    """One engine candidate move, tagged for soundness.

    ``san`` is the first move of the line rendered in SAN (falls back to the
    raw UCI when unparseable); ``uci`` is that same first move in coordinate
    form (used by the fidelity checker to match named moves). ``drop_cp`` is
    the eval-drop from the best line (≥ 0); ``tag`` is
    ``best``/``sound``/``dubious``/``blunder``; ``theme`` is the engine's
    per-line label, passed through as-is.
    """

    san: str
    uci: str
    eval_cp: int
    drop_cp: int
    tag: str
    theme: str


def build_move_menu(report: PositionReport) -> list[MenuMove]:
    """Turn the engine's ``top_lines`` into a soundness-tagged candidate menu.

    The engine sorts lines best-first for the side to move, so the drop is
    ``top_lines[0].eval_cp - line.eval_cp`` (clamped to ≥ 0) and index 0 is
    always ``best`` — the same frame the move-comparator and critical-moment
    logic use, so no per-side sign handling is needed. Lines with no moves are
    skipped. Pure and total: an empty ``top_lines`` yields an empty menu.
    """
    lines = [pv for pv in report.top_lines if pv.moves]
    if not lines:
        return []
    best_eval = lines[0].eval_cp
    menu: list[MenuMove] = []
    for i, pv in enumerate(lines):
        uci = pv.moves[0]
        san = uci_to_san(report.fen, uci)
        drop = max(0, best_eval - pv.eval_cp)
        tag = "best" if i == 0 else classify_drop(drop)
        menu.append(MenuMove(san=san, uci=uci, eval_cp=pv.eval_cp, drop_cp=drop, tag=tag, theme=pv.theme))
    return menu


def describe_move_menu(menu: list[MenuMove]) -> str | None:
    """Render the tagged menu as a compact prompt section, or None if empty.

    Deliberately compact — first move + eval + soundness tag + theme, not the
    full deep line — to keep the prompt readable for small models while still
    telling the coach which moves are sound and which are blunders.
    """
    if not menu:
        return None
    lines = ["--- Candidate moves (engine-verified) ---"]
    for m in menu:
        suffix = f" — {m.theme}" if m.theme else ""
        lines.append(f"{m.san}  ({m.eval_cp:+d} cp, {m.tag}){suffix}")
    return "\n".join(lines)
