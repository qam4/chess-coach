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


# --------------------------------------------------------------------------
# Config knobs: guidance + template_only wired into the live Coach
# --------------------------------------------------------------------------


class TestCoachKnobs:
    """The live Coach honors the coaching.guidance / coaching.template_only knobs."""

    def test_guidance_off_is_default_and_injects_no_block(self):
        from chess_coach.pedagogy.inject import GUIDANCE_BLOCK_HEADER

        coach = Coach(engine=_mock_coaching_engine(), llm=_mock_llm())  # guidance defaults off
        resp = coach.explain(STARTING_FEN)
        assert GUIDANCE_BLOCK_HEADER not in resp.llm_prompt

    def test_guidance_on_injects_guidance_block(self):
        from chess_coach.pedagogy.inject import GUIDANCE_BLOCK_HEADER

        coach = Coach(engine=_mock_coaching_engine(), llm=_mock_llm(), guidance=True)
        # Resource loaded at construction; explain should inject guidance.
        assert coach.guidance is True
        resp = coach.explain(STARTING_FEN)
        assert GUIDANCE_BLOCK_HEADER in resp.llm_prompt

    def test_template_only_skips_the_llm(self):
        llm = _mock_llm()
        coach = Coach(engine=_mock_coaching_engine(), llm=llm, template_only=True)
        resp = coach.explain(STARTING_FEN)
        llm.generate.assert_not_called()
        assert resp.coaching_text  # deterministic template still produced text

    def test_default_does_use_the_llm(self):
        llm = _mock_llm()
        coach = Coach(engine=_mock_coaching_engine(), llm=llm)
        coach.explain(STARTING_FEN)
        llm.generate.assert_called_once()


# --------------------------------------------------------------------------
# Output verification on the SEND path (not just the eval scoreboard).
# --------------------------------------------------------------------------
#
# The deterministic checker existed for a long time but only ever fed an eval
# scoreboard, so a response contradicting the board still reached the student. An
# external audit of coaching quality made truth a GATE rather than a weighted
# quality: a false claim is worse than silence, because a 1200 cannot detect it.
# The concrete case was v26 ply 36 — a capture described as taking a bishop when
# it took a knight, with the bishop still sitting there twelve plies later.

# Black to move; the black d4 pawn captures the white KNIGHT on e3 (dxe3).
_VERIFY_FEN = "4k3/8/8/8/3p4/4N3/8/4K3 b - - 0 1"
_FALSE_CLAIM = "Nice — you capture the pawn with dxe3, winning material."
_TRUE_CLAIM = "Good, you take the knight with dxe3."


def _verify_report():
    from chess_coach.models import ComparisonReport

    return ComparisonReport(
        fen=_VERIFY_FEN,
        user_move="d4e3",
        user_eval_cp=0,
        best_move="d4e3",
        best_eval_cp=0,
        eval_drop_cp=0,
        classification="good",
        nag="",
        best_move_idea="material gain — winning capture",
        refutation_line=None,
        missed_tactics=[],
        top_lines=[],
        critical_moment=False,
        critical_reason=None,
    )


def _noop_trace(*_args, **_kwargs) -> None:
    return None


class TestVerifiedMoveFeedback:
    def test_clean_response_passes_through_with_one_call(self):
        llm = _mock_llm()
        llm.generate.return_value = _TRUE_CLAIM
        coach = Coach(engine=_mock_engine(), llm=llm)
        out = coach._verified_move_feedback("prompt", _verify_report(), max_tokens=100, trace=_noop_trace)
        assert out == _TRUE_CLAIM
        assert llm.generate.call_count == 1

    def test_false_claim_is_regenerated_once(self):
        llm = _mock_llm()
        llm.generate.side_effect = [_FALSE_CLAIM, _TRUE_CLAIM]
        coach = Coach(engine=_mock_engine(), llm=llm)
        out = coach._verified_move_feedback("prompt", _verify_report(), max_tokens=100, trace=_noop_trace)
        assert out == _TRUE_CLAIM
        assert llm.generate.call_count == 2

    def test_persistent_false_claim_falls_back_to_composed_text(self):
        # Degraded, not wrong — the template is built from engine facts and cannot
        # invent a piece. That is the right way round.
        llm = _mock_llm()
        llm.generate.side_effect = [_FALSE_CLAIM, _FALSE_CLAIM]
        coach = Coach(engine=_mock_engine(), llm=llm)
        out = coach._verified_move_feedback("prompt", _verify_report(), max_tokens=100, trace=_noop_trace)
        assert out != _FALSE_CLAIM
        assert "capture the pawn" not in out
        assert out.strip()
        assert llm.generate.call_count == 2

    def test_switch_off_sends_the_first_draft_unchecked(self):
        # The knob has to actually disable the gate so the change can be A/B'd.
        llm = _mock_llm()
        llm.generate.return_value = _FALSE_CLAIM
        coach = Coach(engine=_mock_engine(), llm=llm, verify_output=False)
        out = coach._verified_move_feedback("prompt", _verify_report(), max_tokens=100, trace=_noop_trace)
        assert out == _FALSE_CLAIM
        assert llm.generate.call_count == 1

    def test_zero_retries_falls_back_immediately(self):
        llm = _mock_llm()
        llm.generate.return_value = _FALSE_CLAIM
        coach = Coach(engine=_mock_engine(), llm=llm, verify_retries=0)
        out = coach._verified_move_feedback("prompt", _verify_report(), max_tokens=100, trace=_noop_trace)
        assert out != _FALSE_CLAIM
        assert llm.generate.call_count == 1

    def test_empty_response_still_raises_for_the_existing_fallback(self):
        # evaluate_move catches this and uses the template path; the verification
        # wrapper must not swallow it.
        import pytest

        llm = _mock_llm()
        llm.generate.return_value = "   "
        coach = Coach(engine=_mock_engine(), llm=llm)
        with pytest.raises(ValueError, match="Empty LLM response"):
            coach._verified_move_feedback("prompt", _verify_report(), max_tokens=100, trace=_noop_trace)
