"""Tests for chess_coach.coach — Coach orchestrator."""

from __future__ import annotations

from unittest.mock import MagicMock

from chess_coach.coach import Coach, CoachingResponse
from chess_coach.engine import AnalysisLine, AnalysisResult, EngineProtocol
from chess_coach.llm.base import LLMProvider

STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def _make_line(depth=12, score_cp=35, pv=None):
    return AnalysisLine(
        depth=depth,
        score_cp=score_cp,
        nodes=50000,
        time_ms=500,
        pv=pv or ["e2e4", "e7e5"],
    )


def _mock_engine(is_ready=True):
    engine = MagicMock(spec=EngineProtocol)
    engine.is_ready.return_value = is_ready
    engine.analyze.return_value = AnalysisResult(
        fen=STARTING_FEN,
        lines=[_make_line(pv=["e2e4", "e7e5"])],
        best_move="e2e4",
    )
    return engine


def _mock_llm(is_available=True):
    llm = MagicMock(spec=LLMProvider)
    llm.is_available.return_value = is_available
    llm.generate.return_value = "White has a slight edge."
    return llm


class TestCoachExplain:
    """Coach.explain() calls the full pipeline and returns CoachingResponse."""

    def test_returns_coaching_response(self):
        coach = Coach(engine=_mock_engine(), llm=_mock_llm())
        resp = coach.explain(STARTING_FEN)

        assert isinstance(resp, CoachingResponse)
        assert resp.fen == STARTING_FEN
        assert resp.coaching_text == "White has a slight edge."
        assert resp.best_move == "e2e4"

    def test_calls_engine_analyze(self):
        engine = _mock_engine()
        coach = Coach(engine=engine, llm=_mock_llm(), depth=20)
        coach.explain(STARTING_FEN)

        engine.analyze.assert_called_once()
        call_kwargs = engine.analyze.call_args
        assert call_kwargs[1]["depth"] == 20

    def test_calls_llm_generate(self):
        llm = _mock_llm()
        coach = Coach(engine=_mock_engine(), llm=llm)
        coach.explain(STARTING_FEN)

        llm.generate.assert_called_once()

    def test_analysis_text_populated(self):
        coach = Coach(engine=_mock_engine(), llm=_mock_llm())
        resp = coach.explain(STARTING_FEN)

        assert resp.analysis_text  # non-empty
        assert STARTING_FEN in resp.analysis_text

    def test_score_from_top_line(self):
        coach = Coach(engine=_mock_engine(), llm=_mock_llm())
        resp = coach.explain(STARTING_FEN)

        assert resp.score == "+0.35"  # 35 cp

    def test_score_fallback_no_lines(self):
        engine = _mock_engine()
        engine.analyze.return_value = AnalysisResult(
            fen=STARTING_FEN,
            lines=[],
            best_move="",
        )
        coach = Coach(engine=engine, llm=_mock_llm())
        resp = coach.explain(STARTING_FEN)

        assert resp.score == "?"


class TestCoachCheck:
    """Coach.check() returns correct status dict."""

    def test_both_available(self):
        coach = Coach(engine=_mock_engine(True), llm=_mock_llm(True))
        status = coach.check()

        assert status == {"engine": True, "llm": True}

    def test_engine_down(self):
        coach = Coach(engine=_mock_engine(False), llm=_mock_llm(True))
        status = coach.check()

        assert status == {"engine": False, "llm": True}

    def test_llm_down(self):
        coach = Coach(engine=_mock_engine(True), llm=_mock_llm(False))
        status = coach.check()

        assert status == {"engine": True, "llm": False}

    def test_both_down(self):
        coach = Coach(engine=_mock_engine(False), llm=_mock_llm(False))
        status = coach.check()

        assert status == {"engine": False, "llm": False}


# --------------------------------------------------------------------------
# Socratic mode wiring (rich coaching-protocol path)
# --------------------------------------------------------------------------


def _coaching_report():
    from chess_coach.models import (
        EvalBreakdown,
        KingSafety,
        PawnFeatures,
        PositionReport,
    )

    empty = PawnFeatures([], [], [])
    return PositionReport(
        fen=STARTING_FEN,
        eval_cp=20,
        eval_breakdown=EvalBreakdown(0, 0, 0, 0),
        hanging_pieces={"white": [], "black": []},
        threats={"white": [], "black": []},
        pawn_structure={"white": empty, "black": empty},
        king_safety={"white": KingSafety(0, ""), "black": KingSafety(0, "")},
        top_lines=[],
        tactics=[],
        threat_map=[],
        threat_map_summary=None,
        critical_moment=False,
        critical_reason=None,
    )


def _mock_coaching_engine():
    from chess_coach.engine import CoachingEngine

    engine = MagicMock(spec=CoachingEngine)
    engine.coaching_available = True
    engine.is_ready.return_value = True
    engine.get_position_report.return_value = _coaching_report()
    return engine


class TestCoachSocratic:
    """explain(socratic=True) routes to the Socratic prompt, else the explainer."""

    def test_socratic_uses_socratic_prompt(self):
        coach = Coach(engine=_mock_coaching_engine(), llm=_mock_llm())
        resp = coach.explain(STARTING_FEN, socratic=True)
        assert "SOCRATIC INSTRUCTIONS" in resp.llm_prompt
        assert "guiding questions" in resp.llm_prompt

    def test_non_socratic_uses_explain_prompt(self):
        coach = Coach(engine=_mock_coaching_engine(), llm=_mock_llm())
        resp = coach.explain(STARTING_FEN, socratic=False)
        assert "COACHING INSTRUCTIONS" in resp.llm_prompt
        assert "SOCRATIC INSTRUCTIONS" not in resp.llm_prompt
