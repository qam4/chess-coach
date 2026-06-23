"""Tests for prompt construction."""

from __future__ import annotations

import pytest

from chess_coach.prompts import SYSTEM_PROMPT, build_coaching_prompt

SAMPLE_ANALYSIS = (
    "Side to move: White\n"
    "Material: White: Q R B N (5 pawns) | Black: Q R B N (5 pawns)\n"
    "Position: Normal\n"
    "Top line: 1. e4 e5 2. Nf3 (+0.35, depth 18)"
)

LEVELS = ["beginner", "intermediate", "advanced"]


class TestBuildCoachingPrompt:
    """Tests for build_coaching_prompt."""

    @pytest.mark.parametrize("level", LEVELS)
    def test_includes_analysis_text(self, level: str) -> None:
        result = build_coaching_prompt(SAMPLE_ANALYSIS, level)
        assert SAMPLE_ANALYSIS in result

    @pytest.mark.parametrize("level", LEVELS)
    def test_includes_level_string(self, level: str) -> None:
        result = build_coaching_prompt(SAMPLE_ANALYSIS, level)
        assert level in result

    @pytest.mark.parametrize("level", LEVELS)
    def test_includes_system_prompt(self, level: str) -> None:
        result = build_coaching_prompt(SAMPLE_ANALYSIS, level)
        assert SYSTEM_PROMPT in result

    @pytest.mark.parametrize("level", LEVELS)
    def test_includes_word_limit_guidance(self, level: str) -> None:
        result = build_coaching_prompt(SAMPLE_ANALYSIS, level)
        assert "200 words" in result

    @pytest.mark.parametrize("level", LEVELS)
    def test_returns_nonempty_string(self, level: str) -> None:
        result = build_coaching_prompt(SAMPLE_ANALYSIS, level)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_default_level_is_intermediate(self) -> None:
        result = build_coaching_prompt(SAMPLE_ANALYSIS)
        assert "intermediate" in result


# --------------------------------------------------------------------------
# BUG-011 regression: the rich prompts must state side-to-move / student color
# --------------------------------------------------------------------------

from chess_coach.models import (  # noqa: E402
    ComparisonReport,
    EvalBreakdown,
    KingSafety,
    PawnFeatures,
    PositionReport,
)
from chess_coach.prompts import (  # noqa: E402
    _format_perspective,
    _uci_line_to_san,
    _uci_to_san,
    build_rich_coaching_prompt,
    build_rich_move_evaluation_prompt,
)

WHITE_TO_MOVE_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
# After 1.e4 e5 2.Qh5 — Black to move (the BUG-011 repro position).
BLACK_TO_MOVE_FEN = "rnbqkbnr/pppp1ppp/8/4p2Q/4P3/8/PPPP1PPP/RNB1KBNR b KQkq - 1 2"


def _position_report(fen: str) -> PositionReport:
    """Minimal valid PositionReport for prompt construction."""
    empty_pawns = PawnFeatures([], [], [])
    return PositionReport(
        fen=fen,
        eval_cp=17,
        eval_breakdown=EvalBreakdown(material=0, mobility=0, king_safety=0, pawn_structure=0),
        hanging_pieces={"white": [], "black": []},
        threats={"white": [], "black": []},
        pawn_structure={"white": empty_pawns, "black": empty_pawns},
        king_safety={"white": KingSafety(0, ""), "black": KingSafety(0, "")},
        top_lines=[],
        tactics=[],
        threat_map=[],
        threat_map_summary=None,
        critical_moment=False,
        critical_reason=None,
    )


def _comparison_report(fen: str) -> ComparisonReport:
    """Minimal valid ComparisonReport for prompt construction."""
    return ComparisonReport(
        fen=fen,
        user_move="g8f6",
        user_eval_cp=0,
        best_move="b8c6",
        best_eval_cp=17,
        eval_drop_cp=17,
        classification="good",
        nag="!?",
        best_move_idea="develop and defend",
        refutation_line=None,
        missed_tactics=[],
        top_lines=[],
        critical_moment=False,
        critical_reason=None,
    )


class TestPerspective:
    """The rich prompts must make side-to-move explicit (BUG-011)."""

    def test_format_perspective_black_to_move(self) -> None:
        text = _format_perspective(BLACK_TO_MOVE_FEN)
        assert "Side to move: Black" in text
        assert "Black pieces" in text

    def test_format_perspective_white_to_move(self) -> None:
        text = _format_perspective(WHITE_TO_MOVE_FEN)
        assert "Side to move: White" in text
        assert "White pieces" in text

    def test_format_perspective_defaults_to_white_on_malformed_fen(self) -> None:
        # A FEN with no active-color field should not raise.
        assert "Side to move: White" in _format_perspective("8/8/8/8/8/8/8/8")

    def test_coaching_prompt_names_black_side_to_move(self) -> None:
        prompt = build_rich_coaching_prompt(_position_report(BLACK_TO_MOVE_FEN), "beginner")
        assert "Side to move: Black" in prompt
        assert "Black pieces" in prompt

    def test_coaching_prompt_names_white_side_to_move(self) -> None:
        prompt = build_rich_coaching_prompt(_position_report(WHITE_TO_MOVE_FEN), "beginner")
        assert "Side to move: White" in prompt

    def test_coaching_prompt_states_eval_is_white_relative(self) -> None:
        prompt = build_rich_coaching_prompt(_position_report(BLACK_TO_MOVE_FEN), "beginner")
        assert "White's perspective" in prompt

    def test_move_evaluation_prompt_names_black_side_to_move(self) -> None:
        prompt = build_rich_move_evaluation_prompt(_comparison_report(BLACK_TO_MOVE_FEN), "beginner")
        assert "Side to move: Black" in prompt
        assert "Black pieces" in prompt


# --------------------------------------------------------------------------
# Move-decoding fix: prompts should present moves in SAN (named piece), not
# raw UCI coordinates the model misreads (move-feedback eval finding).
# --------------------------------------------------------------------------

# After 1.e4 e5 2.Nf3 Nc6 3.Bc4 Bc5 — White to move, castling is legal here.
CASTLE_FEN = "r1bqk1nr/pppp1ppp/2n5/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"


def _move_eval_report(fen: str, user_move: str, best_move: str) -> ComparisonReport:
    return ComparisonReport(
        fen=fen,
        user_move=user_move,
        user_eval_cp=-50,
        best_move=best_move,
        best_eval_cp=20,
        eval_drop_cp=70,
        classification="mistake",
        nag="?",
        best_move_idea="develop a piece",
        refutation_line=None,
        missed_tactics=[],
        top_lines=[],
        critical_moment=False,
        critical_reason=None,
    )


class TestUciToSan:
    """UCI->SAN conversion with safe fallback."""

    def test_king_move(self) -> None:
        # Black to move (after 1.e4 e5 2.Qh5); e8e7 is a king move.
        assert _uci_to_san(BLACK_TO_MOVE_FEN, "e8e7") == "Ke7"

    def test_knight_move(self) -> None:
        assert _uci_to_san(BLACK_TO_MOVE_FEN, "b8c6") == "Nc6"

    def test_castling(self) -> None:
        assert _uci_to_san(CASTLE_FEN, "e1g1") == "O-O"

    def test_illegal_move_falls_back_to_uci(self) -> None:
        assert _uci_to_san(BLACK_TO_MOVE_FEN, "a1a8") == "a1a8"

    def test_garbage_falls_back(self) -> None:
        assert _uci_to_san(BLACK_TO_MOVE_FEN, "notamove") == "notamove"

    def test_line_converts_to_san(self) -> None:
        # b8c6 (Nc6) then f1c4 (Bc4) is a legal sequence from this position.
        assert _uci_line_to_san(BLACK_TO_MOVE_FEN, ["b8c6", "f1c4"]) == "Nc6 Bc4"

    def test_line_falls_back_at_illegal_move(self) -> None:
        # First move legal (Nc6), second illegal -> remainder emitted raw.
        out = _uci_line_to_san(BLACK_TO_MOVE_FEN, ["b8c6", "z9z9"])
        assert out == "Nc6 z9z9"


class TestMoveEvaluationUsesSan:
    """The move-evaluation prompt must name the moved piece, not show UCI."""

    def test_king_move_shown_as_san(self) -> None:
        report = _move_eval_report(BLACK_TO_MOVE_FEN, "e8e7", "b8c6")
        prompt = build_rich_move_evaluation_prompt(report, "beginner")
        assert "Ke7" in prompt  # student's move, named
        assert "Nc6" in prompt  # best move, named
        assert "e8e7" not in prompt  # raw UCI gone
        assert "b8c6" not in prompt

    def test_castling_shown_as_san(self) -> None:
        report = _move_eval_report(CASTLE_FEN, "e1g1", "d2d3")
        prompt = build_rich_move_evaluation_prompt(report, "beginner")
        assert "O-O" in prompt
        assert "e1g1" not in prompt
