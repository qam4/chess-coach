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

    # Tactics (forks, pins, skewers, etc.)
    tactics = _tactics_text(report)
    if tactics:
        sections.append(tactics)

    # Threat map summary (from Blunder)
    if report.threat_map_summary:
        sections.append(f"Board tensions: {report.threat_map_summary}")

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
        try:
            board = chess.Board(report.fen)
            move = chess.Move.from_uci(report.best_move)
            best_san = board.san(move)
        except (ValueError, chess.InvalidMoveError):
            best_san = report.best_move
        sections.append(
            f"The engine preferred {best_san} (eval: {report.best_eval_cp / 100:+.2f})."
        )

    # Missed tactics
    if report.missed_tactics:
        for tactic in report.missed_tactics:
            sections.append(f"You missed a {tactic.type}: {tactic.description}")

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
    """Describe active threats using board state and structured data."""
    items = []
    try:
        board = chess.Board(report.fen)
    except ValueError:
        return None

    for side_key, side_name in [("white", "White"), ("black", "Black")]:
        for t in report.threats.get(side_key, []):
            piece_name = _piece_name_at(board, t.source_square)
            source = f"{side_name}'s {piece_name} on {t.source_square}" if piece_name else side_name

            # Build description from structured fields when possible
            if t.type == "check" and t.target_squares:
                items.append(f"{source} can give check.")
            elif t.type == "capture" and t.target_squares:
                targets = ", ".join(t.target_squares)
                items.append(f"{source} threatens to capture on {targets}.")
            elif t.description:
                # Fallback to engine description for types we don't handle yet
                items.append(f"{source}: {t.description}")
            else:
                items.append(f"{source} has a threat ({t.type}).")

    if not items:
        return None
    return "Threats: " + " ".join(items)


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
    """Describe king safety concerns using board state, not engine descriptions.

    Suppresses warnings in the early opening (first ~8 moves) when not
    castling is normal. Only warns when the king is actually in danger.
    """
    try:
        board = chess.Board(report.fen)
    except ValueError:
        return None

    move_number = board.fullmove_number
    parts = []

    for color, side_name in [(chess.WHITE, "White"), (chess.BLACK, "Black")]:
        ks = report.king_safety.get(side_name.lower())
        if not ks or ks.score >= -10:
            continue

        king_sq = board.king(color)
        if king_sq is None:
            continue

        has_castling = board.has_castling_rights(color)
        king_rank = chess.square_rank(king_sq)
        home_rank = 0 if color == chess.WHITE else 7
        is_on_home_rank = king_rank == home_rank

        # Early opening: don't nag about not castling yet
        if move_number <= 8 and is_on_home_rank and has_castling:
            continue

        # Build a context-aware description
        if not is_on_home_rank:
            parts.append(
                f"{side_name}'s king has been displaced to "
                f"{chess.square_name(king_sq)} — be careful."
            )
        elif move_number > 8 and has_castling:
            parts.append(f"{side_name}'s king is still in the center. Consider castling soon.")
        elif not has_castling and is_on_home_rank:
            # Lost castling rights but king is still on home rank
            parts.append(f"{side_name}'s king can no longer castle — keep it protected.")
        elif ks.score < -30:
            # Significant danger — use a stronger warning
            parts.append(f"{side_name}'s king is exposed and vulnerable.")

    if not parts:
        return None
    return " ".join(parts)


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


def _tactics_text(report: PositionReport) -> str | None:
    """Describe detected tactical motifs."""
    if not report.tactics:
        return None
    items = []
    for t in report.tactics:
        items.append(f"{t.type}: {t.description}")
    return "Tactics: " + ". ".join(items) + "."


def _best_move_text(report: PositionReport) -> str | None:
    """Position-aware advice without revealing the specific best move.

    The hint button is for concrete move suggestions. The coaching text
    should focus on what to think about, not what to play.
    """
    if not report.top_lines or not report.top_lines[0].moves:
        return None

    try:
        board = chess.Board(report.fen)
        move = chess.Move.from_uci(report.top_lines[0].moves[0])
        piece = board.piece_at(move.from_square)

        # Give positional guidance based on what the best move does
        if board.san(move) in ("O-O", "O-O-O"):
            return "Consider castling to get your king to safety."

        if piece and piece.piece_type in (chess.KNIGHT, chess.BISHOP):
            back_rank = 0 if board.turn == chess.WHITE else 7
            if chess.square_rank(move.from_square) == back_rank:
                return "Look for ways to develop your remaining pieces."

        if board.is_capture(move):
            return "There's a tactical opportunity — look for captures."

        # Check if there are hanging pieces to address
        side = "white" if board.turn == chess.WHITE else "black"
        if report.hanging_pieces.get(side):
            return "You have an undefended piece — address that first."

        return None
    except (ValueError, chess.InvalidMoveError):
        return None
