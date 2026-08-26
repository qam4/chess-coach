"""Template-based coaching text generator.

Produces factual coaching text directly from structured engine data.
No LLM needed — instant, deterministic, never hallucinates.

This is Layer 1 of the hybrid coaching approach. The output can be
used standalone or passed to an LLM for tone/personality rephrasing.
"""

from __future__ import annotations

import typing
from dataclasses import dataclass

import chess

from chess_coach.coaching_phrases import (
    OPENING_LENIENCY_CP,
    describe_eval,
    describe_hanging,
    describe_king_safety,
    describe_pawn_structure,
    describe_tactic,
    describe_tactic_core,
    describe_threat,
    king_safety_relevant,
    select_tactics,
    suppress_threats_echoing_tactics,
)
from chess_coach.models import ComparisonReport, EvalBreakdown, PositionReport
from chess_coach.openings import OpeningInfo
from chess_coach.pedagogy.inject import render_guidance_entries
from chess_coach.pedagogy.resource import GuidanceEntry


def _safe_board(fen: str) -> chess.Board | None:
    """Parse a FEN into a board, or None if it is malformed."""
    try:
        return chess.Board(fen)
    except ValueError:
        return None


@dataclass
class CoachingArrow:
    """An arrow to draw on the board."""

    from_sq: str  # e.g. "c4"
    to_sq: str  # e.g. "f7"
    color: str = "#e74c3c"  # red by default


@dataclass
class CoachingSection:
    """A single section of coaching output."""

    category: str  # assessment, piece_safety, tactics, strategy, tensions, suggestion
    label: str  # human-readable label for UI rendering
    text: str  # the coaching text
    arrows: list[CoachingArrow] | None = None  # optional board arrows

    def to_dict(self) -> dict[str, typing.Any]:
        """Serialize for JSON API responses."""
        d: dict[str, typing.Any] = {
            "category": self.category,
            "label": self.label,
            "text": self.text,
        }
        if self.arrows:
            d["arrows"] = [{"from": a.from_sq, "to": a.to_sq, "color": a.color} for a in self.arrows]
        return d


# Category constants
CAT_FOCUS = "focus"
CAT_ASSESSMENT = "assessment"
CAT_PIECE_SAFETY = "piece_safety"
CAT_TACTICS = "tactics"
CAT_STRATEGY = "strategy"
CAT_TENSIONS = "tensions"
CAT_SUGGESTION = "suggestion"

_CATEGORY_LABELS = {
    CAT_FOCUS: "What to focus on",
    CAT_ASSESSMENT: "Assessment",
    CAT_PIECE_SAFETY: "Piece safety",
    CAT_TACTICS: "Tactics",
    CAT_STRATEGY: "Strategy",
    CAT_TENSIONS: "Tensions",
    CAT_SUGGESTION: "Suggestion",
}


# ---------------------------------------------------------------------------
# Eval breakdown diff — compares two positions to explain what changed
# ---------------------------------------------------------------------------

_BREAKDOWN_LABELS = {
    "material": "material",
    "mobility": "piece activity",
    "king_safety": "king safety",
    "pawn_structure": "pawn structure",
}


def diff_eval_breakdowns(before: EvalBreakdown, after: EvalBreakdown) -> list[tuple[str, int]]:
    """Return (label, delta_cp) pairs sorted by absolute delta, largest first.

    Positive delta = component improved for the side that moved.
    Negative delta = component worsened.
    Only includes components with |delta| >= 5cp (noise filter).
    """
    diffs: list[tuple[str, int]] = []
    for field in ("material", "mobility", "king_safety", "pawn_structure"):
        before_val = getattr(before, field)
        after_val = getattr(after, field)
        # After a move, eval perspective flips (opponent's turn), so negate
        delta = -(after_val) - before_val
        if abs(delta) >= 5:
            label = _BREAKDOWN_LABELS.get(field, field)
            diffs.append((label, delta))
    diffs.sort(key=lambda x: abs(x[1]), reverse=True)
    return diffs


def generate_move_impact_text(
    before: PositionReport,
    after: PositionReport,
    user_move_san: str = "",
) -> str | None:
    """Generate text explaining what the user's move changed.

    Compares eval breakdowns before and after the move to explain
    which positional factors improved or worsened.
    """
    diffs = diff_eval_breakdowns(before.eval_breakdown, after.eval_breakdown)
    if not diffs:
        return None

    improved = [(label, d) for label, d in diffs if d > 0]
    worsened = [(label, d) for label, d in diffs if d < 0]

    parts: list[str] = []
    if improved:
        items = [f"{label} (+{d}cp)" for label, d in improved]
        parts.append("Improved: " + ", ".join(items) + ".")
    if worsened:
        items = [f"{label} ({d}cp)" for label, d in worsened]
        parts.append("Worsened: " + ", ".join(items) + ".")

    return " ".join(parts)


def generate_priority_coaching(
    report: PositionReport,
    level: str = "intermediate",
) -> str | None:
    """Generate prioritized coaching: what matters most right now.

    Looks at the position and picks the 1-2 most important things
    to focus on, rather than listing everything.

    Priority order:
    1. Hanging pieces (immediate material loss)
    2. Threats in PV (engine plans to exploit this)
    3. Weakest eval component (strategic weakness to address)
    4. Best move direction (what the engine suggests)
    """
    parts: list[str] = []

    # 1. Hanging pieces — most urgent
    for side in ("white", "black"):
        for hp in report.hanging_pieces.get(side, []):
            parts.append(f"Your {hp.piece} on {hp.square} is undefended — protect it or move it.")

    # 2. Real tactical motifs — de-duplicated and composed from structured
    #    data (never the engine prose description).
    for tactic in select_tactics(report.tactics):
        parts.append(f"Watch out for {describe_tactic_core(tactic)}")

    # 3. Weakest component — strategic direction
    if not parts:  # only if no immediate tactical concerns
        breakdown = report.eval_breakdown
        components = {
            "piece activity": breakdown.mobility,
            "king safety": breakdown.king_safety,
            "pawn structure": breakdown.pawn_structure,
        }
        # Find the worst component (most negative = biggest weakness)
        worst_label, worst_val = min(components.items(), key=lambda x: x[1])
        if worst_val < -15:
            parts.append(f"Your biggest weakness is {worst_label} ({worst_val}cp). Focus on improving it.")

    # 4. Best move hint from top line theme
    if report.top_lines and report.top_lines[0].theme:
        theme = report.top_lines[0].theme
        if theme and len(parts) < 2:
            parts.append(f"The engine suggests: {theme}.")

    if not parts:
        return None
    return " ".join(parts[:3])  # cap at 3 items


def generate_position_coaching_structured(
    report: PositionReport,
    level: str = "intermediate",
    opening: OpeningInfo | None = None,
    guidance: list[GuidanceEntry] | None = None,
) -> list[CoachingSection]:
    """Generate structured coaching sections from a PositionReport.

    Returns a list of CoachingSection objects, each with a category,
    label, and text. The UI can render these as tabs, collapsible
    sections, or a flat list.

    When ``guidance`` is supplied and non-empty, the selector-chosen
    guidance entries are surfaced as a leading "What to focus on" focus
    section (Req 3.5), carrying each entry's named theme and its
    how-to-apply statement. Entries whose recorded levels exclude
    ``level`` are dropped (Req 3.3); an empty selection (or one empty
    after that filter) adds no focus section, leaving the template output
    exactly as it is today (Req 3.6, 3.7).
    """
    sections: list[CoachingSection] = []

    # Leading focus section — the curated "what to focus on" half of the
    # teaching bridge (Req 3.5), level-filtered (Req 3.3).
    focus_lines = render_guidance_entries(guidance or [], level)
    if focus_lines:
        sections.append(
            CoachingSection(
                CAT_FOCUS,
                _CATEGORY_LABELS[CAT_FOCUS],
                "\n".join(focus_lines),
            )
        )

    # Assessment
    sections.append(
        CoachingSection(
            CAT_ASSESSMENT,
            _CATEGORY_LABELS[CAT_ASSESSMENT],
            _eval_summary(report),
        )
    )

    # Piece safety — hanging pieces
    hanging = _hanging_pieces_text(report)
    if hanging:
        # Highlight hanging piece squares
        hanging_arrows = []
        for side in ("white", "black"):
            for hp in report.hanging_pieces.get(side, []):
                hanging_arrows.append(CoachingArrow(hp.square, hp.square, "#e74c3c"))
        sections.append(
            CoachingSection(
                CAT_PIECE_SAFETY,
                _CATEGORY_LABELS[CAT_PIECE_SAFETY],
                hanging,
                arrows=hanging_arrows or None,
            )
        )

    # Tactics — threats, checks, captures, motifs
    threats_and_tactics = _threats_and_tactics_text(report)
    if threats_and_tactics:
        tactic_arrows = _extract_arrows(report)
        sections.append(
            CoachingSection(
                CAT_TACTICS,
                _CATEGORY_LABELS[CAT_TACTICS],
                threats_and_tactics,
                arrows=tactic_arrows or None,
            )
        )

    # Strategy — king safety + pawn structure
    strategy_parts: list[str] = []
    king = _king_safety_text(report)
    if king:
        strategy_parts.append(king)
    pawns = _pawn_structure_text(report, level)
    if pawns:
        strategy_parts.append(pawns)
    if strategy_parts:
        sections.append(
            CoachingSection(
                CAT_STRATEGY,
                _CATEGORY_LABELS[CAT_STRATEGY],
                " ".join(strategy_parts),
            )
        )

    # Tensions — contested squares, under-defended pieces
    tensions = _board_tensions_text(report)
    if tensions:
        sections.append(
            CoachingSection(
                CAT_TENSIONS,
                _CATEGORY_LABELS[CAT_TENSIONS],
                tensions,
            )
        )

    # Suggestion — what to think about
    best = _best_move_text(report)
    if best:
        sections.append(
            CoachingSection(
                CAT_SUGGESTION,
                _CATEGORY_LABELS[CAT_SUGGESTION],
                best,
            )
        )

    return sections


def _extract_arrows(report: PositionReport) -> list[CoachingArrow]:
    """Extract board arrows from threats and tactics."""
    arrows: list[CoachingArrow] = []

    # Tactics: source → targets
    for t in report.tactics:
        if not t.squares or len(t.squares) < 2:
            continue
        src = t.squares[0]
        if t.type == "discovered_attack":
            # Contract: squares = [revealed_attacker, target, mover]. The only
            # reliable overlay is the revealed attack line (attacker → target);
            # the mover's square is not a target of the attacker, so drawing
            # attacker → mover (the old behaviour) produced a bogus arrow.
            arrows.append(CoachingArrow(src, t.squares[1], "#f59e0b"))
        else:
            for tgt in t.squares[1:]:
                arrows.append(CoachingArrow(src, tgt, "#f59e0b"))

    # Threats: source → target squares
    for side in ("white", "black"):
        color = "#3b82f6" if side == "white" else "#e74c3c"
        for threat in report.threats.get(side, []):
            for tgt in threat.target_squares:
                arrows.append(CoachingArrow(threat.source_square, tgt, color))

    return arrows


def generate_position_coaching(
    report: PositionReport,
    level: str = "intermediate",
    opening: OpeningInfo | None = None,
    guidance: list[GuidanceEntry] | None = None,
) -> str:
    """Generate coaching text from a PositionReport without an LLM.

    Returns a multi-paragraph coaching explanation built entirely from
    the structured engine data. For structured output (categories),
    use generate_position_coaching_structured() instead.

    When ``guidance`` is supplied and non-empty, the selector-chosen
    guidance is surfaced as a leading focus section (Req 3.5); an empty
    selection leaves the output exactly as today (Req 3.6, 3.7).
    """
    sections = generate_position_coaching_structured(report, level=level, opening=opening, guidance=guidance)
    return "\n\n".join(s.text for s in sections)


def _move_number_from_fen(fen: str) -> int:
    """Extract the full-move number from a FEN string.

    The move number is the last field in a FEN. Returns 1 if parsing fails.
    """
    try:
        return int(fen.split()[-1])
    except (IndexError, ValueError):
        return 1


def effective_move_classification(report: ComparisonReport) -> str:
    """Return the coaching-adjusted classification for a move.

    In the opening (first 6 moves), engine eval at shallow depth is
    unreliable — only flag moves with a large eval drop. This prevents sound
    openings like 1...e5, 1.d4, or the Scandinavian from being called
    inaccuracies or mistakes.

    Shares ``OPENING_LENIENCY_CP`` with ``Coach.evaluate_move`` so the template and
    LLM paths cannot disagree about which opening moves are worth flagging.
    """
    cls = report.classification
    if cls != "good" and _move_number_from_fen(report.fen) <= 6:
        if report.eval_drop_cp <= OPENING_LENIENCY_CP:
            return "good"
    return cls


def generate_move_coaching(
    report: ComparisonReport,
    level: str = "intermediate",
) -> str:
    """Generate move evaluation coaching from a ComparisonReport."""
    sections: list[str] = []

    # Override engine classification for early opening moves.
    # At shallow depth, the engine's eval is unreliable for opening moves —
    # it may penalize perfectly sound openings (e.g. 1...e5, 1.d4, Scandinavian).
    # In the first few moves, only flag moves with a large eval drop.
    cls = effective_move_classification(report)

    if cls == "good":
        sections.append("Good move!")
    else:
        # No cost, in any unit. Converting the drop to pawns looked like the fix for
        # showing raw evals, and it was half a fix: "you lost about 1.2 pawns" is
        # still a magnitude, and it was never even in pawns — Blunder's pawn is 124
        # (MG) to 206 (EG), so the division by 100 produced a number belonging to no
        # scale at all. Measured against Stockfish 18 the drop carries a 50-60cp
        # residual under every conversion, wider than the bands separating these
        # three labels, so the label is not defensible either.
        #
        # This text is a fallback a student reads when the model could not be
        # trusted, so it says only what we can stand behind: a stronger move existed,
        # and here is what it does. The sections below supply that from the board.
        sections.append("There was a stronger move here.")

    # What was stronger
    if report.best_move and cls != "good":
        try:
            board = chess.Board(report.fen)
            move = chess.Move.from_uci(report.best_move)
            best_san = board.san(move)
        except (ValueError, chess.InvalidMoveError):
            best_san = report.best_move
        sections.append(f"{best_san} was stronger here.")

    # Missed tactics — composed from structured data (never engine prose),
    # de-duplicated by motif identity.
    for tactic in select_tactics(report.missed_tactics):
        sections.append(f"You missed {describe_tactic_core(tactic)}")

    # Refutation line
    if report.refutation_line and cls in ("mistake", "blunder"):
        try:
            board = chess.Board(report.fen)
            # Push user move first, then convert refutation to SAN
            board.push(chess.Move.from_uci(report.user_move))
            san_moves = []
            for uci_move in report.refutation_line:
                m = chess.Move.from_uci(uci_move)
                san_moves.append(board.san(m))
                board.push(m)
            sections.append(f"The opponent can punish this with: {' '.join(san_moves)}")
        except (ValueError, chess.InvalidMoveError):
            moves = " ".join(report.refutation_line)
            sections.append(f"The opponent can punish this with: {moves}")

    return "\n\n".join(sections)


# -------------------------------------------------------------------
# Internal helpers
# -------------------------------------------------------------------


def _eval_summary(report: PositionReport) -> str:
    """Summarize the overall evaluation — delegated to the shared composer."""
    return describe_eval(report)


def _hanging_pieces_text(report: PositionReport) -> str | None:
    """Describe hanging pieces via the shared composer."""
    pieces = [describe_hanging(hp) for side in ("white", "black") for hp in report.hanging_pieces.get(side, [])]
    if not pieces:
        return None
    return "Piece safety: " + " ".join(pieces)


def _threats_and_tactics_text(report: PositionReport) -> str | None:
    """Present tactics and threats as composed coaching sentences, or None.

    All wording comes from the single composer (:mod:`coaching_phrases`):
    tactics are de-duplicated by motif identity (``select_tactics``) and
    composed from structured fields; threats that merely restate a shown
    tactic are suppressed, the rest composed. The engine's prose
    ``description`` is never read here.
    """
    board = _safe_board(report.fen)
    tactics = select_tactics(report.tactics)
    items: list[str] = [describe_tactic(t, board) for t in tactics]
    for side_key in ("white", "black"):
        for threat in suppress_threats_echoing_tactics(report.threats.get(side_key, []), tactics):
            items.append(describe_threat(threat, board))
    if not items:
        return None
    return "\n".join(items)


def _king_safety_text(report: PositionReport) -> str | None:
    """Compose the king-safety line from structured fields, or None.

    Built by the composer from the engine's structured king-safety fields
    (never the prose ``description``); suppressed wholesale in low-material
    endgames (``king_safety_relevant``) and per side when there is nothing
    coaching-worthy.
    """
    if not king_safety_relevant(report):
        return None
    parts = [
        s for side in ("white", "black") if (s := describe_king_safety(report.king_safety[side], side)) is not None
    ]
    if not parts:
        return None
    return " ".join(parts)


def _pawn_structure_text(report: PositionReport, level: str) -> str | None:
    """Describe notable pawn structure features via the shared composer."""
    if level == "beginner":
        return None  # Too advanced for beginners

    parts: list[str] = []
    for side in ("white", "black"):
        pf = report.pawn_structure.get(side)
        if pf is None:
            continue
        sentence = describe_pawn_structure(pf, side)
        if sentence:
            parts.append(sentence)

    if not parts:
        return None
    return "Pawn structure: " + " ".join(parts)


def _best_move_text(report: PositionReport) -> str | None:
    """Present the top line theme if available.

    Simple data formatter — no position-aware plan inference.
    If the engine provided a theme for the top line, present it.
    Otherwise return None.
    """
    if not report.top_lines:
        return None

    theme = report.top_lines[0].theme
    if theme:
        return f"The engine suggests: {theme}."
    return None


def _alternative_moves_text(report: PositionReport) -> str | None:
    """Show alternative candidate moves from MultiPV lines.

    Only shown when there are 2+ lines with moves. Converts UCI to SAN
    and shows the eval difference from the best line.
    """
    if len(report.top_lines) < 2:
        return None

    lines_with_moves = [pv for pv in report.top_lines if pv.moves]
    if len(lines_with_moves) < 2:
        return None

    try:
        board = chess.Board(report.fen)
        best_eval = lines_with_moves[0].eval_cp

        alts = []
        for line in lines_with_moves[1:]:
            move = chess.Move.from_uci(line.moves[0])
            san = board.san(move)
            diff = best_eval - line.eval_cp
            if abs(diff) < 5:
                alts.append(f"{san} (equally good)")
            elif diff > 0:
                alts.append(f"{san} (slightly worse, {diff}cp)")
            else:
                alts.append(f"{san} (also strong)")

        if not alts:
            return None
        return "Other ideas: " + ", ".join(alts) + "."
    except (ValueError, chess.InvalidMoveError):
        return None


def _board_tensions_text(report: PositionReport) -> str | None:
    """Describe key board tensions from the threat map.

    Only mentions squares that are genuinely contested (attacked by both
    sides) or where a piece is under-defended.
    """
    if not report.threat_map:
        return None

    contested = []
    under_defended = []

    for entry in report.threat_map:
        w_atk = entry.white_attackers
        b_atk = entry.black_attackers

        # Genuinely contested: both sides attack the square
        if w_atk > 0 and b_atk > 0:
            contested.append(entry.square)

        # Piece under attack with insufficient defense
        if entry.piece and entry.net_attacked:
            under_defended.append(f"{entry.piece} on {entry.square}")

    parts = []
    if under_defended:
        parts.append("Under-defended: " + ", ".join(under_defended))
    if contested:
        squares = ", ".join(contested)
        parts.append(f"Contested squares: {squares}")

    if not parts:
        return None
    return "Board tensions: " + ". ".join(parts) + "."
