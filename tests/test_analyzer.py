"""Tests for chess_coach.analyzer — formatting and analysis bridge."""

from __future__ import annotations

from unittest.mock import MagicMock

import chess

from chess_coach.analyzer import (
    _material_summary,
    _pv_to_san,
    analyze_position,
    format_analysis_for_llm,
)
from chess_coach.engine import AnalysisLine, AnalysisResult, EngineProtocol

# ---------------------------------------------------------------------------
# Known FEN positions
# ---------------------------------------------------------------------------

STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
# Black king in check: 1.e4 f5 2.Qh5+ (queen checks king on e8-h5 diagonal)
CHECK_FEN = "rnbqkbnr/ppppp1pp/8/5p1Q/4P3/8/PPPP1PPP/RNB1KBNR b KQkq - 1 2"
# Fool's mate: black delivers checkmate (Qh4#)
CHECKMATE_FEN = "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"
# Stalemate: black king on a8, white king on a6 + white pawn on a7
STALEMATE_FEN = "k7/P7/K7/8/8/8/8/8 b - - 0 1"


def _make_line(depth=12, score_cp=35, pv=None):
    """Helper to create an AnalysisLine with defaults."""
    return AnalysisLine(
        depth=depth,
        score_cp=score_cp,
        nodes=50000,
        time_ms=500,
        pv=pv or ["e2e4", "e7e5"],
    )


def _make_result(fen, lines=None, best_move=""):
    """Helper to create an AnalysisResult."""
    return AnalysisResult(fen=fen, lines=lines or [], best_move=best_move)


# ---------------------------------------------------------------------------
# format_analysis_for_llm tests
# ---------------------------------------------------------------------------


class TestFormatAnalysisForLLM:
    def test_starting_position_basics(self):
        """Starting position: White to move, move 1, no check/checkmate."""
        result = _make_result(STARTING_FEN, [_make_line(pv=["e2e4", "e7e5"])], "e2e4")
        text = format_analysis_for_llm(result)

        assert "Side to move: White" in text
        assert "Move number: 1" in text
        assert STARTING_FEN in text
        # No check/checkmate/stalemate status for normal position
        assert "IN CHECK" not in text
        assert "CHECKMATE" not in text
        assert "STALEMATE" not in text

    def test_check_position(self):
        """Position where Black is in check should show IN CHECK status."""
        result = _make_result(CHECK_FEN, [_make_line(score_cp=-200, pv=["g8f6"])], "g8f6")
        text = format_analysis_for_llm(result)

        assert "Side to move: Black" in text
        assert "IN CHECK" in text

    def test_checkmate_position(self):
        """Checkmate position should show CHECKMATE status."""
        result = _make_result(CHECKMATE_FEN, [], "")
        text = format_analysis_for_llm(result)

        assert "Side to move: White" in text
        assert "CHECKMATE" in text

    def test_stalemate_position(self):
        """Stalemate position should show STALEMATE status."""
        result = _make_result(STALEMATE_FEN, [], "")
        text = format_analysis_for_llm(result)

        assert "Side to move: Black" in text
        assert "STALEMATE" in text

    def test_engine_lines_in_output(self):
        """Engine analysis lines should appear with SAN notation."""
        lines = [
            _make_line(depth=12, score_cp=35, pv=["e2e4", "e7e5", "g1f3"]),
            _make_line(depth=12, score_cp=25, pv=["d2d4", "d7d5"]),
        ]
        result = _make_result(STARTING_FEN, lines, "e2e4")
        text = format_analysis_for_llm(result)

        assert "Engine analysis:" in text
        assert "Line 1:" in text
        assert "Line 2:" in text
        # SAN notation should appear (e4, e5, Nf3 instead of e2e4, e7e5, g1f3)
        assert "e4" in text
        assert "Nf3" in text

    def test_material_in_output(self):
        """Material summary should be present in the output."""
        result = _make_result(STARTING_FEN, [_make_line()], "e2e4")
        text = format_analysis_for_llm(result)

        assert "Material:" in text
        assert "White:" in text
        assert "Black:" in text

    def test_no_lines(self):
        """Formatting with no engine lines should still produce valid output."""
        result = _make_result(STARTING_FEN, [], "")
        text = format_analysis_for_llm(result)

        assert "Engine analysis:" in text
        assert "Side to move: White" in text


# ---------------------------------------------------------------------------
# _material_summary tests
# ---------------------------------------------------------------------------


class TestMaterialSummary:
    def test_starting_position(self):
        """Starting position has equal material."""
        board = chess.Board(STARTING_FEN)
        summary = _material_summary(board)

        assert "White:" in summary
        assert "Black:" in summary
        # Both sides: 8 pawns, 2 knights, 2 bishops, 2 rooks, 1 queen
        assert "Px8" in summary
        assert "Nx2" in summary
        assert "Bx2" in summary
        assert "Rx2" in summary
        assert "Qx1" in summary

    def test_imbalanced_material(self):
        """Position with material imbalance."""
        # White has king + queen, Black has king only
        board = chess.Board("4k3/8/8/8/8/8/8/4K2Q w - - 0 1")
        summary = _material_summary(board)

        assert "White: Qx1" in summary
        # Black should have no pieces listed (only king, which isn't counted)
        assert "Black:" in summary

    def test_bare_kings(self):
        """Position with only kings — no material to list."""
        board = chess.Board("4k3/8/8/8/8/8/8/4K3 w - - 0 1")
        summary = _material_summary(board)

        assert "White:" in summary
        assert "Black:" in summary


# ---------------------------------------------------------------------------
# _pv_to_san tests
# ---------------------------------------------------------------------------


class TestPvToSan:
    def test_basic_conversion(self):
        """Convert simple opening moves to SAN."""
        board = chess.Board(STARTING_FEN)
        san = _pv_to_san(board, ["e2e4", "e7e5", "g1f3"])

        assert san == "e4 e5 Nf3"

    def test_empty_pv(self):
        """Empty PV returns empty string."""
        board = chess.Board(STARTING_FEN)
        assert _pv_to_san(board, []) == ""

    def test_invalid_move_stops(self):
        """Invalid move in PV stops conversion at that point."""
        board = chess.Board(STARTING_FEN)
        san = _pv_to_san(board, ["e2e4", "zzzz", "g1f3"])

        # Should stop at the invalid move
        assert san == "e4"

    def test_illegal_move_stops(self):
        """Illegal move in PV stops conversion."""
        board = chess.Board(STARTING_FEN)
        # e7e5 is illegal for White (it's Black's pawn)
        san = _pv_to_san(board, ["e7e5"])
        assert san == ""

    def test_long_pv_truncated(self):
        """PV longer than 8 moves is truncated."""
        board = chess.Board(STARTING_FEN)
        long_pv = [
            "e2e4",
            "e7e5",
            "g1f3",
            "b8c6",
            "f1b5",
            "a7a6",
            "b5a4",
            "g8f6",
            "e1g1",
            "f8e7",  # moves 9 and 10 — should be cut
        ]
        san = _pv_to_san(board, long_pv)
        moves = san.split()
        assert len(moves) == 8

    def test_does_not_mutate_board(self):
        """_pv_to_san should not modify the original board."""
        board = chess.Board(STARTING_FEN)
        original_fen = board.fen()
        _pv_to_san(board, ["e2e4", "e7e5", "g1f3"])
        assert board.fen() == original_fen


# ---------------------------------------------------------------------------
# analyze_position tests (mocked engine)
# ---------------------------------------------------------------------------


class TestAnalyzePosition:
    def test_calls_engine_analyze(self):
        """analyze_position should call engine.analyze with correct args."""
        mock_engine = MagicMock(spec=EngineProtocol)
        mock_engine.analyze.return_value = AnalysisResult(
            fen=STARTING_FEN,
            lines=[
                _make_line(depth=12, score_cp=35, pv=["e2e4"]),
                _make_line(depth=12, score_cp=25, pv=["d2d4"]),
                _make_line(depth=12, score_cp=20, pv=["c2c4"]),
            ],
            best_move="e2e4",
        )

        result = analyze_position(mock_engine, STARTING_FEN, depth=12, time_limit=5.0)

        mock_engine.analyze.assert_called_once_with(STARTING_FEN, depth=12, time_limit=5.0)
        assert result.fen == STARTING_FEN
        assert result.best_move == "e2e4"

    def test_trims_to_top_n(self):
        """analyze_position keeps only the deepest line (single PV until MultiPV is supported)."""
        mock_engine = MagicMock(spec=EngineProtocol)
        mock_engine.analyze.return_value = AnalysisResult(
            fen=STARTING_FEN,
            lines=[
                _make_line(depth=12, score_cp=35, pv=["e2e4"]),
                _make_line(depth=12, score_cp=25, pv=["d2d4"]),
                _make_line(depth=12, score_cp=20, pv=["c2c4"]),
                _make_line(depth=12, score_cp=15, pv=["g1f3"]),
            ],
            best_move="e2e4",
        )

        result = analyze_position(mock_engine, STARTING_FEN, depth=12, top_n=2)

        assert len(result.lines) == 1
        assert result.lines[0].pv == ["e2e4"]

    def test_fewer_lines_than_top_n(self):
        """If engine returns fewer lines than top_n, return all of them."""
        mock_engine = MagicMock(spec=EngineProtocol)
        mock_engine.analyze.return_value = AnalysisResult(
            fen=STARTING_FEN,
            lines=[_make_line(depth=12, score_cp=35, pv=["e2e4"])],
            best_move="e2e4",
        )

        result = analyze_position(mock_engine, STARTING_FEN, depth=12, top_n=3)

        assert len(result.lines) == 1
