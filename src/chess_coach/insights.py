"""Move insight extraction — the 'why' behind engine recommendations.

Analyzes position reports before and after a move to extract structured
reasons why a move is good or bad. This is the reasoning layer that
sits between raw engine data and coaching text.

The output is a structured MoveInsight that can be rendered into
coaching text at any level (beginner/intermediate/advanced).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import chess

from chess_coach.models import EvalBreakdown, PositionReport


# ---------------------------------------------------------------------------
# Data structures for move insights
# ---------------------------------------------------------------------------

_FACTOR_LABELS = {
    "material": "material",
    "mobility": "piece activity",
    "king_safety": "king safety",
    "pawn_structure": "pawn structure",
}


@dataclass
class FactorChange:
    """A change in one eval component caused by a move."""

    factor: str  # "material", "mobility", "king_safety", "pawn_structure"
    label: str  # human-readable: "piece activity", "pawn structure"
    delta_cp: int  # positive = improved, negative = worsened
    before_cp: int
    after_cp: int

    @property
    def improved(self) -> bool:
        return self.delta_cp > 0

    @property
    def worsened(self) -> bool:
        return self.delta_cp < 0


@dataclass
class ThreatInfo:
    """A threat on the board — either an opportunity or a problem."""

    type: str  # "pin", "fork", "skewer", "capture", "check", etc.
    description: str
    source_square: str
    target_squares: list[str]
    is_opponent_threat: bool  # True = threat against us, False = our opportunity


@dataclass
class MoveInsight:
    """Structured reasoning about why a move is good or bad."""

    move_uci: str
    move_san: str

    # What the move changes in the eval breakdown
    factor_changes: list[FactorChange] = field(default_factory=list)

    # Threats the move creates (new threats after the move)
    threats_created: list[ThreatInfo] = field(default_factory=list)

    # Threats the move resolves (threats that existed before but not after)
    threats_resolved: list[ThreatInfo] = field(default_factory=list)

    # Threats that remain (still present after the move)
    threats_remaining: list[ThreatInfo] = field(default_factory=list)

    # Pieces attacked by this move
    pieces_attacked: list[str] = field(default_factory=list)

    # Is this a capture? What was captured?
    capture: str | None = None  # e.g. "bishop", "pawn"

    # The engine's follow-up plan (next 2-3 moves from PV)
    plan: list[str] = field(default_factory=list)

    # Overall eval change
    eval_before_cp: int = 0
    eval_after_cp: int = 0

    def to_dict(self) -> dict:
        return {
            "move_uci": self.move_uci,
            "move_san": self.move_san,
            "factor_changes": [
                {
                    "factor": fc.factor,
                    "label": fc.label,
                    "delta_cp": fc.delta_cp,
                    "improved": fc.improved,
                }
                for fc in self.factor_changes
            ],
            "threats_created": len(self.threats_created),
            "threats_resolved": len(self.threats_resolved),
            "threats_remaining": len(self.threats_remaining),
            "pieces_attacked": self.pieces_attacked,
            "capture": self.capture,
            "plan": self.plan,
            "eval_before_cp": self.eval_before_cp,
            "eval_after_cp": self.eval_after_cp,
        }


# ---------------------------------------------------------------------------
# Extraction functions
# ---------------------------------------------------------------------------


def extract_factor_changes(
    before: EvalBreakdown, after: EvalBreakdown, min_delta: int = 5
) -> list[FactorChange]:
    """Compare eval breakdowns and return significant changes.

    After a move, the eval perspective flips (opponent's turn), so
    we negate the after values to keep them from the mover's perspective.
    """
    changes: list[FactorChange] = []
    for factor in ("material", "mobility", "king_safety", "pawn_structure"):
        before_val = getattr(before, factor)
        after_val = getattr(after, factor)
        delta = -(after_val) - before_val
        if abs(delta) >= min_delta:
            changes.append(
                FactorChange(
                    factor=factor,
                    label=_FACTOR_LABELS.get(factor, factor),
                    delta_cp=delta,
                    before_cp=before_val,
                    after_cp=after_val,
                )
            )
    changes.sort(key=lambda c: abs(c.delta_cp), reverse=True)
    return changes


def extract_threats(
    report: PositionReport, side_to_move: bool
) -> list[ThreatInfo]:
    """Extract threats from a position report, tagged by whose threat it is."""
    threats: list[ThreatInfo] = []
    for side_key in ("white", "black"):
        is_opponent = (side_key == "white") != side_to_move
        for t in report.threats.get(side_key, []):
            threats.append(
                ThreatInfo(
                    type=t.type,
                    description=t.description,
                    source_square=t.source_square,
                    target_squares=list(t.target_squares),
                    is_opponent_threat=is_opponent,
                )
            )
    return threats


def diff_threats(
    before: list[ThreatInfo], after: list[ThreatInfo]
) -> tuple[list[ThreatInfo], list[ThreatInfo], list[ThreatInfo]]:
    """Compare threats before and after a move.

    Returns (created, resolved, remaining).
    """
    def _key(t: ThreatInfo) -> str:
        return f"{t.type}:{t.source_square}:{','.join(t.target_squares)}"

    before_keys = {_key(t): t for t in before}
    after_keys = {_key(t): t for t in after}

    created = [after_keys[k] for k in after_keys if k not in before_keys]
    resolved = [before_keys[k] for k in before_keys if k not in after_keys]
    remaining = [after_keys[k] for k in after_keys if k in before_keys]

    return created, resolved, remaining


def extract_move_insight(
    report_before: PositionReport,
    report_after: PositionReport,
    move_uci: str,
    move_san: str = "",
) -> MoveInsight:
    """Extract a full MoveInsight from before/after position reports.

    This is the main entry point for the insight extraction layer.
    """
    try:
        board_before = chess.Board(report_before.fen)
        side_to_move = board_before.turn  # chess.WHITE or chess.BLACK
    except ValueError:
        side_to_move = chess.WHITE

    # Compute SAN if not provided
    if not move_san:
        try:
            board = chess.Board(report_before.fen)
            move_san = board.san(chess.Move.from_uci(move_uci))
        except (ValueError, chess.InvalidMoveError):
            move_san = move_uci

    # Factor changes
    factor_changes = extract_factor_changes(
        report_before.eval_breakdown, report_after.eval_breakdown
    )

    # Threat analysis
    threats_before = extract_threats(report_before, side_to_move)
    threats_after = extract_threats(report_after, not side_to_move)
    created, resolved, remaining = diff_threats(threats_before, threats_after)

    # Capture detection
    capture = None
    try:
        board = chess.Board(report_before.fen)
        move = chess.Move.from_uci(move_uci)
        captured_piece = board.piece_at(move.to_square)
        if captured_piece:
            names = {
                chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop",
                chess.ROOK: "rook", chess.QUEEN: "queen",
            }
            capture = names.get(captured_piece.piece_type, "piece")
    except (ValueError, chess.InvalidMoveError):
        pass

    # Pieces attacked by this move (check what the moved piece attacks)
    pieces_attacked: list[str] = []
    try:
        board = chess.Board(report_before.fen)
        move = chess.Move.from_uci(move_uci)
        board.push(move)
        moved_piece = board.piece_at(move.to_square)
        if moved_piece:
            attacks = board.attacks(move.to_square)
            for sq in attacks:
                target = board.piece_at(sq)
                if target and target.color != moved_piece.color:
                    sq_name = chess.square_name(sq)
                    piece_name = chess.piece_name(target.piece_type)
                    pieces_attacked.append(f"{piece_name} on {sq_name}")
    except (ValueError, chess.InvalidMoveError):
        pass

    # Plan from PV (next 2-3 moves after this one)
    plan: list[str] = []
    if report_after.top_lines:
        pv = report_after.top_lines[0].moves
        try:
            board = chess.Board(report_after.fen)
            for uci in pv[:3]:
                m = chess.Move.from_uci(uci)
                if m in board.legal_moves:
                    plan.append(board.san(m))
                    board.push(m)
                else:
                    break
        except (ValueError, chess.InvalidMoveError):
            pass

    return MoveInsight(
        move_uci=move_uci,
        move_san=move_san,
        factor_changes=factor_changes,
        threats_created=created,
        threats_resolved=resolved,
        threats_remaining=[t for t in remaining if t.is_opponent_threat],
        pieces_attacked=pieces_attacked,
        capture=capture,
        plan=plan,
        eval_before_cp=report_before.eval_cp,
        eval_after_cp=report_after.eval_cp,
    )
