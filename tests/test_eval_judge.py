"""Tests for the Layer 2 judge: rubric, prompt, verdict parser (Task 5)."""

from __future__ import annotations

import json

import pytest

from chess_coach.eval.benchmark import BenchmarkPosition, GroundTruthPoint
from chess_coach.eval.judge import (
    JudgeRubric,
    VerdictParseError,
    build_judge_prompt,
    default_rubric_path,
    format_engine_report,
    judge_response,
    load_rubric,
    parse_verdict,
)
from chess_coach.models import (
    EvalBreakdown,
    HangingPiece,
    KingSafety,
    PawnFeatures,
    PositionReport,
)

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def _report(fen: str = START_FEN, eval_cp: int = 0, hanging: list[HangingPiece] | None = None):
    return PositionReport(
        fen=fen,
        eval_cp=eval_cp,
        eval_breakdown=EvalBreakdown(material=0, mobility=20, king_safety=0, pawn_structure=0),
        hanging_pieces={"white": [], "black": hanging or []},
        threats={"white": [], "black": []},
        pawn_structure={"white": PawnFeatures([], [], []), "black": PawnFeatures([], [], [])},
        king_safety={"white": KingSafety(0, ""), "black": KingSafety(0, "")},
        top_lines=[],
        tactics=[],
        threat_map=[],
        threat_map_summary=None,
        critical_moment=False,
        critical_reason=None,
    )


def _pos() -> BenchmarkPosition:
    return BenchmarkPosition(
        id="t",
        fen=START_FEN,
        level="beginner",
        phase="opening",
        points=(GroundTruthPoint("free", "center"),),
    )


def _rubric() -> JudgeRubric:
    return load_rubric(default_rubric_path())


# --------------------------------------------------------------- rubric


def test_default_rubric_loads() -> None:
    r = _rubric()
    assert r.version == "v1"
    keys = r.keys()
    assert "key_idea" in keys
    assert "grounded" in keys
    assert r.total_weight() > 0


def test_rubric_rejects_duplicate_keys(tmp_path) -> None:
    from chess_coach.eval.judge import RubricError

    p = tmp_path / "r.yaml"
    p.write_text(
        "version: v9\ncriteria:\n  - {key: a, description: x}\n  - {key: a, description: y}\n",
        encoding="utf-8",
    )
    with pytest.raises(RubricError, match="duplicate"):
        load_rubric(p)


# --------------------------------------------------------------- P3: grounding


def test_judge_prompt_contains_report_and_grounding() -> None:
    report = _report(eval_cp=150, hanging=[HangingPiece("e4", "knight", "black")])
    prompt = build_judge_prompt("some coaching", report, _pos(), _rubric())
    # Engine ground truth present.
    assert report.fen in prompt
    assert "GROUND TRUTH" in prompt
    assert "knight on e4" in prompt
    # Grounding instruction present.
    assert "Do NOT use your own chess" in prompt
    # Rubric keys present.
    assert "key_idea" in prompt
    assert "grounded" in prompt
    # The coaching text is included.
    assert "some coaching" in prompt


def test_format_report_omits_empty_sections() -> None:
    text = format_engine_report(_report())
    assert "Evaluation" in text
    assert "Hanging pieces" not in text  # none present
    assert "Tactics" not in text


# --------------------------------------------------------------- P4: parsing


def _verdict_json(passes: dict[str, bool], contradictions: list[str] | None = None) -> str:
    return json.dumps(
        {
            "criteria": {k: {"pass": v, "reason": "because"} for k, v in passes.items()},
            "contradictions": contradictions or [],
            "notes": "ok",
        }
    )


def _all_pass() -> dict[str, bool]:
    return {k: True for k in _rubric().keys()}


def test_parse_complete_verdict() -> None:
    r = _rubric()
    v = parse_verdict(_verdict_json(_all_pass()), r, judge_model="claude")
    assert v.judge_model == "claude"
    assert v.rubric_version == "v1"
    assert v.quality_score == 1.0
    assert set(v.criteria) == set(r.keys())


def test_parse_tolerates_markdown_fence_and_prose() -> None:
    r = _rubric()
    raw = "Sure, here is my assessment:\n```json\n" + _verdict_json(_all_pass()) + "\n```\nDone."
    v = parse_verdict(raw, r, judge_model="m")
    assert v.quality_score == 1.0


def test_parse_missing_criterion_raises() -> None:
    r = _rubric()
    passes = _all_pass()
    del passes["actionable"]
    with pytest.raises(VerdictParseError, match="missing criterion 'actionable'"):
        parse_verdict(_verdict_json(passes), r, judge_model="m")


def test_parse_no_json_raises() -> None:
    with pytest.raises(VerdictParseError, match="no JSON object"):
        parse_verdict("I think it was pretty good overall.", _rubric(), judge_model="m")


def test_parse_invalid_json_raises() -> None:
    with pytest.raises(VerdictParseError, match="not valid JSON"):
        parse_verdict("{ this is not json }", _rubric(), judge_model="m")


def test_quality_score_weighted() -> None:
    r = _rubric()
    # Fail only the two weight-2 criteria (key_idea, grounded).
    passes = _all_pass()
    passes["key_idea"] = False
    # grounded will be forced False via contradictions below.
    raw = _verdict_json(passes, contradictions=["claims knight on h4 — empty"])
    v = parse_verdict(raw, r, judge_model="m")
    # earned = total - weight(key_idea) - weight(grounded) = total - 4
    expected = round((r.total_weight() - 4.0) / r.total_weight(), 4)
    assert v.quality_score == expected


# --------------------------------------------------------------- P5: grounded


def test_grounded_fails_iff_contradictions() -> None:
    r = _rubric()
    # Model claims grounded passes, but reports a contradiction ->
    # we override grounded to False.
    passes = _all_pass()
    raw = _verdict_json(passes, contradictions=["claims bishop on e4 — empty"])
    v = parse_verdict(raw, r, judge_model="m")
    assert v.criteria["grounded"][0] is False

    # No contradictions -> grounded passes even if model said false.
    passes2 = _all_pass()
    passes2["grounded"] = False
    raw2 = _verdict_json(passes2, contradictions=[])
    v2 = parse_verdict(raw2, r, judge_model="m")
    assert v2.criteria["grounded"][0] is True


# --------------------------------------------------------------- judge_response


class _FakeProvider:
    def __init__(self, replies: list[str]):
        self.replies = replies
        self.model = "fake-judge"
        self.calls = 0

    def generate(self, prompt: str, max_tokens: int = 900, temperature: float = 0.0) -> str:
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return reply


def test_judge_response_happy_path() -> None:
    r = _rubric()
    provider = _FakeProvider([_verdict_json(_all_pass())])
    v = judge_response(provider, "coaching", _report(), _pos(), r)
    assert v.quality_score == 1.0
    assert provider.calls == 1


def test_judge_response_retries_once_then_succeeds() -> None:
    r = _rubric()
    provider = _FakeProvider(["garbage no json", _verdict_json(_all_pass())])
    v = judge_response(provider, "coaching", _report(), _pos(), r)
    assert v.quality_score == 1.0
    assert provider.calls == 2


def test_judge_response_raises_after_double_failure() -> None:
    r = _rubric()
    provider = _FakeProvider(["garbage", "still garbage"])
    with pytest.raises(VerdictParseError, match="after retry"):
        judge_response(provider, "coaching", _report(), _pos(), r)
    assert provider.calls == 2


# --------------------------------------------------------------- v2 gated scoring


def _v2_rubric() -> JudgeRubric:
    return load_rubric(default_rubric_path().parent / "rubric.v2.yaml")


def test_v2_rubric_loads_with_gates() -> None:
    r = _v2_rubric()
    assert r.version == "v2"
    assert "teaches_principle" in r.keys()
    gate_keys = {k for k, _ in r.gates}
    assert gate_keys == {"grounded", "key_idea"}


def test_v1_has_no_gates() -> None:
    assert _rubric().gates == ()


def test_v2_grounded_gate_multiplies_score() -> None:
    r = _v2_rubric()
    passes = {k: True for k in r.keys()}
    # A contradiction forces grounded False (Property 5) and trips its gate.
    raw = _verdict_json(passes, contradictions=["claims a knight that isn't there"])
    v = parse_verdict(raw, r, judge_model="m")
    base = (r.total_weight() - r.weight_of("grounded")) / r.total_weight()
    assert v.quality_score == round(base * 0.3, 4)


def test_v2_key_idea_gate_multiplies_score() -> None:
    r = _v2_rubric()
    passes = {k: True for k in r.keys()}
    passes["key_idea"] = False
    raw = _verdict_json(passes, contradictions=[])  # grounded stays True
    v = parse_verdict(raw, r, judge_model="m")
    base = (r.total_weight() - r.weight_of("key_idea")) / r.total_weight()
    assert v.quality_score == round(base * 0.5, 4)


def test_v2_gates_compound() -> None:
    r = _v2_rubric()
    passes = {k: True for k in r.keys()}
    passes["key_idea"] = False
    raw = _verdict_json(passes, contradictions=["fabricated piece"])  # grounded -> False too
    v = parse_verdict(raw, r, judge_model="m")
    base = (r.total_weight() - r.weight_of("key_idea") - r.weight_of("grounded")) / r.total_weight()
    assert v.quality_score == round(base * 0.3 * 0.5, 4)


def test_v2_all_pass_is_one() -> None:
    r = _v2_rubric()
    v = parse_verdict(_verdict_json({k: True for k in r.keys()}), r, judge_model="m")
    assert v.quality_score == 1.0


def test_gate_rejects_unknown_criterion(tmp_path) -> None:
    from chess_coach.eval.judge import RubricError

    p = tmp_path / "r.yaml"
    p.write_text(
        "version: v9\n"
        "criteria:\n  - {key: a, description: x}\n"
        "scoring:\n  gates:\n    - {criterion: nope, on_fail: 0.5}\n",
        encoding="utf-8",
    )
    with pytest.raises(RubricError, match="unknown criterion"):
        load_rubric(p)
