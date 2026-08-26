"""Tests for Play vs Engine backend — Coach.evaluate_move and classification."""

from __future__ import annotations

from unittest.mock import MagicMock

from chess_coach.coach import (
    Coach,
    MoveEvaluation,
)
from chess_coach.coaching_phrases import (
    DUBIOUS_MAX_DROP_CP,
    EQUAL_MAX_DROP_CP,
    SOUND_MAX_DROP_CP,
)
from chess_coach.engine import AnalysisLine, AnalysisResult, EngineProtocol
from chess_coach.llm.base import LLMProvider

STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
# A middlegame position not in the opening book — used for threshold tests
MIDDLEGAME_FEN = "r1bq1rk1/ppp2ppp/2np1n2/2b1p3/2B1P3/3P1N2/PPP2PPP/RNBQ1RK1 w - - 4 7"


def _make_line(score_cp: int, depth: int = 12, pv: list[str] | None = None):
    return AnalysisLine(
        depth=depth,
        score_cp=score_cp,
        nodes=50000,
        time_ms=500,
        pv=pv or ["e2e4", "e7e5"],
    )


def _mock_engine():
    engine = MagicMock(spec=EngineProtocol)
    engine.is_ready.return_value = True
    return engine


def _mock_llm():
    llm = MagicMock(spec=LLMProvider)
    llm.is_available.return_value = True
    llm.generate.return_value = "Good move."
    return llm


def _make_coach(
    eval_before_cp: int,
    eval_after_cp: int,
) -> Coach:
    """Create a Coach with mocked engine returning specific evals.

    eval_before_cp: eval from side-to-move perspective before user move.
    eval_after_cp: eval from side-to-move perspective AFTER user move
        (from the opponent's view, so the engine returns -eval_after_cp).
    """
    engine = _mock_engine()
    # First call: analyze before user's move
    result_before = AnalysisResult(
        fen=STARTING_FEN,
        lines=[_make_line(score_cp=eval_before_cp)],
        best_move="e2e4",
    )
    # Second call: analyze after user's move (opponent's perspective)
    result_after = AnalysisResult(
        fen=STARTING_FEN,
        lines=[_make_line(score_cp=-eval_after_cp)],
        best_move="e7e5",
    )
    engine.analyze.side_effect = [result_before, result_after]
    return Coach(engine=engine, llm=_mock_llm(), depth=12)


# -------------------------------------------------------------------
# classify_move static method tests
# -------------------------------------------------------------------


class TestClassifyMove:
    """Direct tests for Coach.classify_move thresholds.

    Keyed to the constants rather than to literals. They were literals (50/51/100/101)
    and every one of them broke when the engine's output scale changed and the bands
    were halved — which told us nothing about the classifier and cost a round of
    edits. What matters is the behaviour AT each boundary, whatever the boundary is.
    """

    def test_good_zero_drop(self):
        assert Coach.classify_move(0) == "good"

    def test_good_at_boundary(self):
        assert Coach.classify_move(SOUND_MAX_DROP_CP) == "good"

    def test_inaccuracy_just_above_good(self):
        assert Coach.classify_move(SOUND_MAX_DROP_CP + 1) == "inaccuracy"

    def test_inaccuracy_at_boundary(self):
        assert Coach.classify_move(DUBIOUS_MAX_DROP_CP) == "inaccuracy"

    def test_blunder_just_above_inaccuracy(self):
        assert Coach.classify_move(DUBIOUS_MAX_DROP_CP + 1) == "blunder"

    def test_blunder_large_drop(self):
        assert Coach.classify_move(DUBIOUS_MAX_DROP_CP * 5) == "blunder"

    def test_good_negative_drop(self):
        # Negative drop means the move improved the position
        assert Coach.classify_move(-SOUND_MAX_DROP_CP) == "good"

    def test_bands_are_ordered(self):
        # A rescale that accidentally inverted or collapsed the bands would leave every
        # test above still passing. This is the invariant that actually holds.
        assert 0 < EQUAL_MAX_DROP_CP < SOUND_MAX_DROP_CP < DUBIOUS_MAX_DROP_CP


# -------------------------------------------------------------------
# evaluate_move integration tests with mocked engine
# -------------------------------------------------------------------


class TestEvaluateMove:
    """Coach.evaluate_move with mocked engine evals."""

    def test_good_move_small_drop(self):
        """eval_before=50, eval_after=40 => drop=10 => good."""
        coach = _make_coach(eval_before_cp=50, eval_after_cp=40)
        result = coach.evaluate_move(STARTING_FEN, "e2e4")

        assert isinstance(result, MoveEvaluation)
        assert result.classification == "good"
        assert result.eval_drop_cp == 10

    def test_good_move_zero_drop(self):
        """eval_before=50, eval_after=50 => drop=0 => good."""
        coach = _make_coach(eval_before_cp=50, eval_after_cp=50)
        result = coach.evaluate_move(STARTING_FEN, "e2e4")

        assert result.classification == "good"
        assert result.eval_drop_cp == 0

    def test_good_move_at_boundary(self):
        """A drop exactly at the sound boundary is still good."""
        drop = SOUND_MAX_DROP_CP
        coach = _make_coach(eval_before_cp=100, eval_after_cp=100 - drop)
        result = coach.evaluate_move(STARTING_FEN, "e2e4")

        assert result.classification == "good"
        assert result.eval_drop_cp == drop

    def test_inaccuracy_just_over_boundary(self):
        """One cp past the sound boundary becomes an inaccuracy."""
        drop = SOUND_MAX_DROP_CP + 1
        coach = _make_coach(eval_before_cp=100, eval_after_cp=100 - drop)
        result = coach.evaluate_move(MIDDLEGAME_FEN, "c4b5")

        assert result.classification == "inaccuracy"
        assert result.eval_drop_cp == drop

    def test_inaccuracy_at_upper_boundary(self):
        """A drop exactly at the dubious boundary is still an inaccuracy."""
        drop = DUBIOUS_MAX_DROP_CP
        coach = _make_coach(eval_before_cp=100, eval_after_cp=100 - drop)
        result = coach.evaluate_move(MIDDLEGAME_FEN, "c4b5")

        assert result.classification == "inaccuracy"
        assert result.eval_drop_cp == drop

    def test_blunder_just_over_boundary(self):
        """One cp past the dubious boundary becomes a blunder."""
        drop = DUBIOUS_MAX_DROP_CP + 1
        coach = _make_coach(eval_before_cp=100, eval_after_cp=100 - drop)
        result = coach.evaluate_move(MIDDLEGAME_FEN, "c4b5")

        assert result.classification == "blunder"
        assert result.eval_drop_cp == drop

    def test_blunder_large_drop(self):
        """eval_before=200, eval_after=-300 => drop=500 => blunder."""
        coach = _make_coach(eval_before_cp=200, eval_after_cp=-300)
        result = coach.evaluate_move(MIDDLEGAME_FEN, "c4b5")

        assert result.classification == "blunder"
        assert result.eval_drop_cp == 500

    def test_improving_move_clamped_to_good(self):
        """eval_before=50, eval_after=100 => drop=-50 clamped to 0 => good."""
        coach = _make_coach(eval_before_cp=50, eval_after_cp=100)
        result = coach.evaluate_move(STARTING_FEN, "e2e4")

        assert result.classification == "good"
        assert result.eval_drop_cp == 0

    def test_feedback_skipped_for_good_move(self):
        """Good moves skip LLM — feedback is empty."""
        coach = _make_coach(eval_before_cp=50, eval_after_cp=40)
        result = coach.evaluate_move(STARTING_FEN, "e2e4")

        assert result.feedback == ""

    def test_feedback_populated_for_inaccuracy(self):
        """Inaccuracies get LLM feedback."""
        coach = _make_coach(eval_before_cp=100, eval_after_cp=40)
        result = coach.evaluate_move(MIDDLEGAME_FEN, "c4b5")

        assert result.feedback == "Good move."

    def test_eval_values_stored(self):
        """eval_before and eval_after are stored correctly."""
        coach = _make_coach(eval_before_cp=50, eval_after_cp=40)
        result = coach.evaluate_move(STARTING_FEN, "e2e4")

        assert result.eval_before_cp == 50
        assert result.eval_after_cp == 40
