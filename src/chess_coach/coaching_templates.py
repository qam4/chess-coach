"""Template-based coaching text generator.

Produces factual coaching text directly from structured engine data.
No LLM needed — instant, deterministic, never hallucinates.

This is Layer 1 of the hybrid coaching approach. The output can be
used standalone or passed to an LLM for tone/personality rephrasing.
"""

from __future__ import annotations

import chess

from chess_coach.models import ComparisonReport, PositionReport
from chess_coach.openings import OpeningInfo


def generate_position_coaching(
    report: PositionReport,
    level: str = "intermediate",
    opening: OpeningInfo | None = None,
) -> str:
    """Generate coaching text from a PositionReport without an LLM.

    Returns a multi-paragraph coaching explanation built entirely from
    the structured engine data.
    """
    sections: list[str] = []

    # Opening
    if opening:
        sections.append(f"This is the {opening.name} ({opening.eco}).")

    # Overall eval
    sections.append(_eval_summary(report))

    # Hanging pieces — most urgent for beginners
    hanging = _hanging_pieces_text(report)
    if hanging:
        sections.append(hanging)

    # Threats
    threats = _threats_text(report)
    if threats:
        sections.append(threats)

    # King safety
    king = _king_safety_text(report, level)
    if king:
        sections.append(king)

    # Pawn structure
    pawns = _pawn_structure_text(report, level)
    if pawns:
        sections.append(pawns)

    # Best move recommendation
    best = _best_move_text(report)
    if best:
        sections.append(best)

    return "\n\n".join(sections)


def generate_move_coaching(
    report: ComparisonReport,
    level: str = "intermediate",
) -> str:
    """Generate move evaluation coaching from a ComparisonReport."""
    sections: list[str] = []

    # Classification
    cls = report.classification
    drop = abs(report.eval_drop_cp)

    if cls == "good":
        sections.append("Good move! That's in line with what the engine recommends.")
    elif cls == "inaccuracy":
        sections.append(
            f"That's a small inaccuracy — you lost about {drop / 100:.1f} pawns "
            f"of advantage compared to the best move."
        )
    elif cls == "mistake":
        sections.append(
            f"That's a mistake — it costs about {drop / 100:.1f} pawns. "
            f"The engine had a better idea."
        )
    elif cls == "blunder":
        sections.append(
            f"That's a blunder — it drops {drop / 100:.1f} pawns. Let's look at what went wrong."
        )

    # What the engine preferred
    if report.best_move and cls != "good":
        sections.append(
            f"The engine preferred {report.best_move} (eval: {report.best_eval_cp / 100:+.2f})."
        )

    # Missed tactics
    if report.missed_tactics:
        for tactic in report.missed_tactics:
            sections.append(f"You missed a {tactic.type}: {tactic.description}")

    # Refutation line
    if report.refutation_line and cls in ("mistake", "blunder"):
        moves = " ".join(report.refutation_line)
        sections.append(f"The opponent can punish this with: {moves}")

    return "\n\n".join(sections)


# -------------------------------------------------------------------
# Internal helpers
# -------------------------------------------------------------------


def _eval_summary(report: PositionReport) -> str:
    """Summarize the overall evaluation in plain language."""
    cp = report.eval_cp
    abs_cp = abs(cp)

    if abs_cp < 30:
        assessment = "The position is roughly equal."
    elif abs_cp < 100:
        side = "White" if cp > 0 else "Black"
        assessment = f"{side} has a slight edge ({cp / 100:+.2f} pawns)."
    elif abs_cp < 300:
        side = "White" if cp > 0 else "Black"
        assessment = f"{side} has a clear advantage ({cp / 100:+.2f} pawns)."
    else:
        side = "White" if cp > 0 else "Black"
        assessment = f"{side} is winning ({cp / 100:+.2f} pawns)."

    # Add mobility context if the breakdown is available
    mob = report.eval_breakdown.mobility
    if abs(mob) > 100:
        better = "White" if mob > 0 else "Black"
        assessment += f" {better}'s pieces are more active and control more squares."

    return assessment


def _hanging_pieces_text(report: PositionReport) -> str | None:
    """Describe hanging pieces."""
    pieces = []
    for hp in report.hanging_pieces.get("white", []):
        pieces.append(f"White's {hp.piece} on {hp.square} is undefended")
    for hp in report.hanging_pieces.get("black", []):
        pieces.append(f"Black's {hp.piece} on {hp.square} is undefended")

    if not pieces:
        return None
    return "Piece safety: " + ". ".join(pieces) + "."


def _threats_text(report: PositionReport) -> str | None:
    """Describe active threats with piece names."""
    items = []
    board = chess.Board(report.fen)

    for t in report.threats.get("white", []):
        # Enrich with piece name from the board
        piece_name = _piece_name_at(board, t.source_square)
        if piece_name:
            items.append(f"White's {piece_name} on {t.source_square}: {t.description}")
        else:
            items.append(f"White: {t.description}")
    for t in report.threats.get("black", []):
        piece_name = _piece_name_at(board, t.source_square)
        if piece_name:
            items.append(f"Black's {piece_name} on {t.source_square}: {t.description}")
        else:
            items.append(f"Black: {t.description}")

    if not items:
        return None
    return "Threats: " + ". ".join(items) + "."


def _piece_name_at(board: chess.Board, square_name: str) -> str | None:
    """Get the piece name at a square, or None."""
    try:
        sq = chess.parse_square(square_name)
        piece = board.piece_at(sq)
        if piece is None:
            return None
        names = {
            chess.PAWN: "pawn",
            chess.KNIGHT: "knight",
            chess.BISHOP: "bishop",
            chess.ROOK: "rook",
            chess.QUEEN: "queen",
            chess.KING: "king",
        }
        return names.get(piece.piece_type)
    except ValueError:
        return None


def _king_safety_text(report: PositionReport, level: str) -> str | None:
    """Describe king safety concerns."""
    parts = []
    w = report.king_safety.get("white")
    b = report.king_safety.get("black")

    if w and w.score < -10:
        parts.append(f"White's king: {w.description}.")
    if b and b.score < -10:
        parts.append(f"Black's king: {b.description}.")

    if not parts:
        return None

    text = " ".join(parts)
    if level == "beginner":
        # Only suggest castling if both sides still have castling rights
        try:
            board = chess.Board(report.fen)
            if board.has_castling_rights(chess.WHITE) or board.has_castling_rights(chess.BLACK):
                text += " Try to castle early to keep your king safe."
        except ValueError:
            pass
    return text


def _pawn_structure_text(report: PositionReport, level: str) -> str | None:
    """Describe notable pawn structure features."""
    if level == "beginner":
        return None  # Too advanced for beginners

    parts = []
    for side_name, side_key in [("White", "white"), ("Black", "black")]:
        features = report.pawn_structure.get(side_key)
        if not features:
            continue
        if features.isolated:
            files = ", ".join(features.isolated)
            parts.append(f"{side_name} has isolated pawns on the {files}-file(s)")
        if features.doubled:
            files = ", ".join(features.doubled)
            parts.append(f"{side_name} has doubled pawns on the {files}-file")
        if features.passed:
            files = ", ".join(features.passed)
            parts.append(f"{side_name} has a passed pawn on the {files}-file")

    if not parts:
        return None
    return "Pawn structure: " + ". ".join(parts) + "."


def _best_move_text(report: PositionReport) -> str | None:
    """Recommend the best move with context about what it does."""
    if not report.top_lines or not report.top_lines[0].moves:
        return None

    line = report.top_lines[0]
    uci_move = line.moves[0]

    try:
        board = chess.Board(report.fen)
        move = chess.Move.from_uci(uci_move)
        san = board.san(move)
        piece = board.piece_at(move.from_square)

        # Describe what the move does
        context_parts = []
        if san in ("O-O", "O-O-O"):
            context_parts.append("getting the king to safety")
        elif (
            piece
            and piece.piece_type in (chess.KNIGHT, chess.BISHOP)
            and board.fullmove_number <= 10
        ):
            context_parts.append("developing a piece toward the center")
        if board.is_capture(move):
            captured = board.piece_at(move.to_square)
            if captured:
                names = {1: "pawn", 2: "knight", 3: "bishop", 4: "rook", 5: "queen"}
                cap_name = names.get(captured.piece_type, "piece")
                context_parts.append(f"capturing the {cap_name}")

        # Check if the move defends a hanging piece
        for hp in report.hanging_pieces.get("white", []) + report.hanging_pieces.get("black", []):
            if move.to_square == chess.parse_square(hp.square):
                context_parts.append(f"defending the {hp.piece}")

        rec = f"The engine recommends {san} (eval: {line.eval_cp / 100:+.2f})"
        if context_parts:
            rec += " — " + ", ".join(context_parts)
        return rec + "."
    except (ValueError, chess.InvalidMoveError):
        return f"The engine recommends {uci_move} (eval: {line.eval_cp / 100:+.2f})."
