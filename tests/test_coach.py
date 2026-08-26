"""Tests for chess_coach.coach — Coach orchestrator."""

from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock

import pytest

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

        llm = _mock_llm()
        llm.generate.return_value = "   "
        coach = Coach(engine=_mock_engine(), llm=llm)
        with pytest.raises(ValueError, match="Empty LLM response"):
            coach._verified_move_feedback("prompt", _verify_report(), max_tokens=100, trace=_noop_trace)


# --------------------------------------------------------------------------
# A move that ends the game always gets a word.
# --------------------------------------------------------------------------
#
# The skip rules look only at the eval drop, and checkmate has a drop of zero — so
# the student delivered mate and the coach said NOTHING. Found the moment the report
# card started calling evaluate_move instead of rebuilding it: the curated Ra8#
# position went silent. It also reframes the mate-labelling defect a reviewer called
# its decisive item; that only appeared because the harness forced commentary on a
# good move, so in production the coach was not wrong about mate, it was absent.

# White to move; Ra8 is checkmate against a king on g8 boxed in by its own pawns.
_MATE_FEN = "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1"
# Same shape but the g7 pawn is gone, so after Ra8 the king escapes to g7: check,
# not mate. (A first version of this test used a position with an extra white rook,
# which is still mate — the king is boxed in by its OWN pawns, so no amount of extra
# white material changes it.)
_QUIET_FEN = "6k1/5p1p/8/8/8/8/5PPP/R5K1 w - - 0 1"


def test_move_ends_game_detects_mate() -> None:
    from chess_coach.coach import _move_ends_game

    assert _move_ends_game(_MATE_FEN, "a1a8") is True
    assert _move_ends_game(_QUIET_FEN, "a1a8") is False


def test_move_ends_game_is_total() -> None:
    # A bad position or move must fall back to the ordinary skip rules, never raise
    # inside coaching.
    from chess_coach.coach import _move_ends_game

    assert _move_ends_game("not a fen", "a1a8") is False
    assert _move_ends_game(_MATE_FEN, "zz99") is False
    assert _move_ends_game(_MATE_FEN, "a1a2a3") is False
    # Legal square syntax, illegal move in this position.
    assert _move_ends_game(_MATE_FEN, "h2h8") is False


def test_stalemate_also_ends_the_game() -> None:
    # Black Ka8, White Kb6 + Qc1: Qc7 is stalemate, not a win — and a student who
    # accidentally stalemates most needs to hear about it.
    from chess_coach.coach import _move_ends_game

    assert _move_ends_game("k7/8/1K6/8/8/8/8/2Q5 w - - 0 1", "c1c7") is True


# --------------------------------------------------------------------------
# Lesson memory across turns (the half the prompt tests cannot prove)
# --------------------------------------------------------------------------
#
# The prompt builder does the right thing when TOLD a lesson has recurred. These
# tests cover the part that actually failed in v33: nobody was counting. The coach
# taught "going after a piece that has too few defenders" five times in one game
# because it had no memory at all.


_REPEAT_FEN = "r1b1k1r1/pppp1p1p/8/4p1P1/1b1B4/1P2P3/P1P1B1nP/RN1K3R w q - 0 16"


def _comparison_with_repeatable_lesson(drop: int = 200):
    """A comparison whose best move attacks an under-defended piece (the v33 shape)."""
    from chess_coach.models import ComparisonReport, PVLine

    return ComparisonReport(
        fen=_REPEAT_FEN,
        user_move="e2c4",
        user_eval_cp=0,
        best_move="d4c3",
        best_eval_cp=0,
        eval_drop_cp=drop,
        classification="mistake",
        nag="?",
        best_move_idea="piece activity — improving piece placement",
        refutation_line=None,
        missed_tactics=[],
        top_lines=[PVLine(depth=8, eval_cp=0, moves=["d4c3"], theme="king attack")],
        critical_moment=False,
        critical_reason=None,
    )


def _coach_with_repeating_engine(feedback: str = "Bc3 was stronger. Worth remembering: count defenders."):
    engine = _mock_coaching_engine()
    engine.get_comparison_report.return_value = _comparison_with_repeatable_lesson()
    llm = _mock_llm()
    llm.generate.return_value = feedback
    # verify_output off: the gate is orthogonal here and a mocked response would trip it.
    return Coach(engine=engine, llm=llm, verify_output=False)


def _prompts_from(coach, turns: int) -> list[str]:
    seen: list[str] = []

    def on_debug(step):
        if step.step == "eval_llm_start":
            seen.append(step.detail.get("llm_prompt", ""))

    for _ in range(turns):
        coach.evaluate_move(_REPEAT_FEN, "e2c4", on_debug=on_debug)
    return seen


class TestLessonMemory:
    def test_same_lesson_escalates_then_retires_across_turns(self):
        coach = _coach_with_repeating_engine()
        prompts = _prompts_from(coach, 4)
        assert len(prompts) == 4

        # 1st: teach it.
        assert "CLOSE with one transferable takeaway on THIS lesson" in prompts[0]
        # 2nd: name the recurrence rather than teaching it again.
        assert "SAME idea as earlier in the game" in prompts[1]
        assert "CLOSE with one transferable takeaway on THIS lesson" not in prompts[1]
        # 3rd and 4th: nothing. This is the v33 defect — by the third telling the
        # student has been given the same maxim twice and it is not landing.
        for p in prompts[2:]:
            assert "CLOSE" not in p
            assert "SAME idea as earlier" not in p

    def test_silent_turns_do_not_consume_the_ladder(self):
        # A turn the coach says nothing on teaches nothing. Counting it would retire a
        # lesson the student has never been told — which is worse than repeating it.
        coach = _coach_with_repeating_engine()
        engine = coach.engine
        # A drop inside the "good move, stay silent" band.
        engine.get_comparison_report.return_value = _comparison_with_repeatable_lesson(drop=0)
        coach.evaluate_move(_REPEAT_FEN, "e2c4")
        coach.evaluate_move(_REPEAT_FEN, "e2c4")
        assert sum(coach._lessons_taught.values()) == 0

        # Now a turn worth coaching: it must still be the FIRST telling.
        engine.get_comparison_report.return_value = _comparison_with_repeatable_lesson(drop=200)
        prompts = _prompts_from(coach, 1)
        assert "CLOSE with one transferable takeaway on THIS lesson" in prompts[0]

    def test_template_fallback_still_consumes_the_ladder(self):
        # An empty LLM response falls back to the template, which produces text but no
        # takeaway — so strictly the lesson was not delivered, and this still counts it.
        # Pinned because it is a deliberate imprecision, not an oversight: over-counting
        # retires a lesson one turn early, which errs toward less repetition. The
        # opposite error would let a lesson repeat indefinitely whenever generation was
        # flaky. If this assertion ever needs to change, change it knowingly.
        coach = _coach_with_repeating_engine(feedback="   ")
        _prompts_from(coach, 2)
        assert sum(coach._lessons_taught.values()) == 2

    def test_new_game_forgets_the_history(self):
        coach = _coach_with_repeating_engine()
        _prompts_from(coach, 3)
        assert coach._lessons_taught

        coach.new_game()
        assert not coach._lessons_taught
        assert coach._last_position_report is None
        # A fresh student gets taught from scratch.
        prompts = _prompts_from(coach, 1)
        assert "CLOSE with one transferable takeaway on THIS lesson" in prompts[0]

    def test_different_lessons_are_tracked_independently(self):
        # Retiring one lesson must not silence an unrelated one.
        from chess_coach.prompts import composed_lesson

        coach = _coach_with_repeating_engine()
        _prompts_from(coach, 3)  # retire the attack lesson

        # Bxe5 is a capture from this position, so it composes a different effect
        # category (and therefore a different lesson) from the attack on b4.
        other = dataclasses.replace(_comparison_with_repeatable_lesson(), best_move="d4e5")
        key_other, lesson_other = composed_lesson(other)
        key_attack, _ = composed_lesson(_comparison_with_repeatable_lesson())
        assert key_other and key_other != key_attack, (
            f"test needs two distinct effects; got {key_other!r} vs {key_attack!r}"
        )

        coach.engine.get_comparison_report.return_value = other
        prompts = _prompts_from(coach, 1)
        assert "CLOSE with one transferable takeaway on THIS lesson" in prompts[0]
        assert lesson_other in prompts[0]
