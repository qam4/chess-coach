"""Position analyzer: runs engine analysis and structures results for the LLM."""

from __future__ import annotations

import chess

from chess_coach.engine import AnalysisResult, EngineProtocol


def analyze_position(
    engine: EngineProtocol,
    fen: str,
    depth: int = 18,
    top_n: int = 3,
    time_limit: float | None = None,
) -> AnalysisResult:
    """Analyze a position and return structured results."""
    result = engine.analyze(fen, depth=depth, time_limit=time_limit)

    # Keep only top N lines by depth (deepest first)
    result.lines = result.lines[:top_n]

    return result


def format_analysis_for_llm(result: AnalysisResult, level: str = "intermediate") -> str:
    """Format engine analysis into a structured text block for the LLM prompt."""
    board = chess.Board(result.fen)
    side = "White" if board.turn == chess.WHITE else "Black"

    parts = [
        f"Position (FEN): {result.fen}",
        f"Side to move: {side}",
        f"Move number: {board.fullmove_number}",
        "",
    ]

    # Material count
    material = _material_summary(board)
    parts.append(f"Material: {material}")

    # Check/game state — check checkmate/stalemate before check,
    # since checkmate implies check.
    if board.is_checkmate():
        parts.append("Status: CHECKMATE")
    elif board.is_stalemate():
        parts.append("Status: STALEMATE")
    elif board.is_check():
        parts.append("Status: IN CHECK")
    parts.append("")

    # Engine lines
    parts.append("Engine analysis:")
    for i, line in enumerate(result.lines, 1):
        san_pv = _pv_to_san(board, line.pv)
        parts.append(f"  Line {i}: {line.score_str} (depth {line.depth})   {san_pv}")

    return "\n".join(parts)


def _pv_to_san(board: chess.Board, pv: list[str]) -> str:
    """Convert a PV in coordinate notation to SAN."""
    b = board.copy()
    san_moves: list[str] = []
    for uci_move in pv[:8]:  # Limit to 8 moves for readability
        try:
            move = chess.Move.from_uci(uci_move)
            if move in b.legal_moves:
                san_moves.append(b.san(move))
                b.push(move)
            else:
                break
        except (ValueError, chess.InvalidMoveError):
            break
    return " ".join(san_moves)


def _material_summary(board: chess.Board) -> str:
    """Summarize material for both sides."""
    piece_values = {
        chess.PAWN: "P",
        chess.KNIGHT: "N",
        chess.BISHOP: "B",
        chess.ROOK: "R",
        chess.QUEEN: "Q",
    }
    parts = []
    for color, name in [(chess.WHITE, "White"), (chess.BLACK, "Black")]:
        pieces = []
        for pt, sym in piece_values.items():
            count = len(board.pieces(pt, color))
            if count > 0:
                pieces.append(f"{sym}x{count}")
        parts.append(f"{name}: {' '.join(pieces)}")
    return " | ".join(parts)
