"""Tests for pedagogy-layer eval integration: the --guidance A/B (Task 7).

Covers the pure delta/exclusion helpers (Property 14), a mock-judge
integration run with guidance ON (coach/judge parity + Layer 1 & 2 scores
+ teaches_principle reported), the resource-load-failure path (Req 7.5),
and the offline selection timing smoke (Req 7.3).

The orchestrator script is loaded via importlib, mirroring
``tests/test_eval_run.py``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from chess_coach.eval.benchmark import BenchmarkPosition, GroundTruthPoint
from chess_coach.eval.judge import default_rubric_path, load_rubric
from chess_coach.eval.objective import ObjectiveResult
from chess_coach.eval.scoring import ResponseEval, aggregate_quality, quality_delta
from chess_coach.models import (
    EvalBreakdown,
    KingSafety,
    PawnFeatures,
    PositionReport,
)
from chess_coach.pedagogy.resource import (
    GuidanceEntry,
    KnowledgeResource,
    PedagogyError,
    default_resource_path,
    load_resource,
)
from chess_coach.pedagogy.selector import guidance_for_position

# Load scripts/eval_run.py as a module (same pattern as test_eval_run.py).
_EVAL_RUN_PATH = Path(__file__).resolve().parent.parent / "scripts" / "eval_run.py"
_spec = importlib.util.spec_from_file_location("eval_run", _EVAL_RUN_PATH)
assert _spec and _spec.loader
eval_run = importlib.util.module_from_spec(_spec)
sys.modules["eval_run"] = eval_run
_spec.loader.exec_module(eval_run)

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
TEACHES_PRINCIPLE = "teaches_principle"


# --------------------------------------------------------------- helpers


def _objective(score: float) -> ObjectiveResult:
    return ObjectiveResult(
        hallucinations=[],
        illegal_moves=[],
        eval_direction_ok=None,
        coverage_hits=[],
        coverage_total=1,
        factual_score=score,
    )


class _Verdict:
    """Minimal Layer-2 verdict satisfying the scoreboard's quality view."""

    def __init__(self, quality_score: float) -> None:
        self.quality_score = quality_score


def _eval(
    pid: str,
    *,
    factual: float = 1.0,
    quality: float | None = None,
    error: str | None = None,
) -> ResponseEval:
    return ResponseEval(
        position_id=pid,
        model="m",
        response="text",
        word_count=2,
        latency_s=0.1,
        objective=_objective(factual),
        judge=_Verdict(quality) if quality is not None else None,
        error=error,
    )


# --------------------------------------------------------------- Property 14


# Feature: pedagogy-layer, Property 14: Teaching-quality delta arithmetic and aggregate exclusion
@settings(max_examples=200)
@given(
    enabled=st.one_of(st.none(), st.floats(min_value=0, max_value=1, allow_nan=False)),
    disabled=st.one_of(st.none(), st.floats(min_value=0, max_value=1, allow_nan=False)),
)
def test_property_14_delta_arithmetic(enabled: float | None, disabled: float | None) -> None:
    """The reported delta equals enabled - disabled (rounded), or None when
    either aggregate is missing.

    Validates: Requirements 5.4
    """
    delta = quality_delta(enabled, disabled)
    if enabled is None or disabled is None:
        assert delta is None
    else:
        assert delta == round(enabled - disabled, 4)


@st.composite
def _eval_batch(draw: st.DrawFn) -> list[ResponseEval]:
    """A batch mixing scorable responses, generation errors, and unjudged
    responses — each kind tagged by its position id so exclusions are
    checkable."""
    n = draw(st.integers(min_value=0, max_value=8))
    evals: list[ResponseEval] = []
    for idx in range(n):
        kind = draw(st.sampled_from(["scored", "error", "unjudged"]))
        if kind == "scored":
            evals.append(_eval(f"ok{idx}", quality=draw(st.floats(min_value=0, max_value=1, allow_nan=False))))
        elif kind == "error":
            evals.append(_eval(f"err{idx}", quality=None, error="gen boom"))
        else:
            evals.append(_eval(f"unj{idx}", quality=None))
    return evals


# Feature: pedagogy-layer, Property 14: Teaching-quality delta arithmetic and aggregate exclusion
@settings(max_examples=200)
@given(evals=_eval_batch())
def test_property_14_aggregate_excludes_and_reports(evals: list[ResponseEval]) -> None:
    """Any response missing a Layer 1 or Layer 2 score (generation error or
    no judge verdict) is excluded from the aggregate AND reported.

    Validates: Requirements 5.5
    """
    mean, excluded = aggregate_quality(evals)

    expected_excluded = {e.position_id for e in evals if e.error is not None or e.judge is None}
    assert set(excluded) == expected_excluded

    scored = [e.judge.quality_score for e in evals if e.error is None and e.judge is not None]
    if scored:
        assert mean == round(sum(scored) / len(scored), 4)
    else:
        assert mean is None
    # An excluded response never contributes to the aggregate.
    assert all(pid in expected_excluded for pid in excluded)


# --------------------------------------------------------------- integration


class _FakeEngine:
    def get_position_report(self, fen: str, multipv: int = 3, depth: int | None = None) -> PositionReport:
        empty = {"white": [], "black": []}
        return PositionReport(
            fen=fen,
            eval_cp=0,
            eval_breakdown=EvalBreakdown(material=0, mobility=0, king_safety=0, pawn_structure=0),
            hanging_pieces=dict(empty),
            threats=dict(empty),
            pawn_structure={"white": PawnFeatures([], [], []), "black": PawnFeatures([], [], [])},
            king_safety={"white": KingSafety(0, ""), "black": KingSafety(0, "")},
            top_lines=[],
            tactics=[],
            threat_map=[],
            threat_map_summary=None,
            critical_moment=False,
            critical_reason=None,
        )


class _SpyProvider:
    """Records every prompt it generates for; always available."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def is_available(self) -> bool:
        return True

    def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7) -> str:
        self.prompts.append(prompt)
        return "Fight for the center."


class _SpyJudge:
    """Records prompts; replies with an all-pass verdict for the v2 rubric."""

    def __init__(self, keys: list[str]) -> None:
        self.model = "spy-judge"
        self.prompts: list[str] = []
        self._keys = keys

    def generate(self, prompt: str, max_tokens: int = 900, temperature: float = 0.0) -> str:
        self.prompts.append(prompt)
        return json.dumps(
            {
                "criteria": {k: {"pass": True, "reason": "ok"} for k in self._keys},
                "contradictions": [],
                "notes": "",
            }
        )


def _positions() -> list[BenchmarkPosition]:
    return [
        BenchmarkPosition(
            id="start", fen=START_FEN, level="beginner", phase="opening", points=(GroundTruthPoint("free", "center"),)
        ),
    ]


def _resource() -> KnowledgeResource:
    entry = GuidanceEntry(
        id="principle.center",
        type="principle",
        theme="THEMETOKEN center control",
        focus="focus",
        how_to_apply="APPLYTOKEN occupy a central square",
        levels=frozenset({"beginner", "intermediate", "advanced"}),
        features=frozenset({"phase:opening"}),
        eco_codes=frozenset(),
        citation="Silman",
        example=None,
    )
    return KnowledgeResource(
        entries=(entry,),
        feature_vocab=frozenset({"phase:opening"}),
        eco_vocab=frozenset(),
        levels=frozenset({"beginner", "intermediate", "advanced"}),
    )


def test_guidance_on_integration_parity_and_scores() -> None:
    """With guidance ON: coach and judge receive the same guidance, both
    Layer 1 and Layer 2 scores are produced, and teaches_principle is
    reported (Req 5.1, 5.3, 4.5)."""
    positions = _positions()
    reports = eval_run._analyze_positions(_FakeEngine(), positions, 3, None)
    resource = _resource()

    # One selection per position, shared by both prompts (mirrors main()).
    guidance_by_id = {
        pid: guidance_for_position(resource, rep, {p.id: p for p in positions}[pid].level, 3)
        for pid, rep in reports.items()
    }
    assert guidance_by_id["start"], "fallback should select the level-appropriate principle"

    provider = _SpyProvider()
    evals = eval_run._run_model(provider, "m", positions, reports, guidance_by_id=guidance_by_id)

    rubric = load_rubric(default_rubric_path().parent / "rubric.v2.yaml")
    judge = _SpyJudge([k for k in rubric.keys()])
    by_id = {p.id: p for p in positions}
    eval_run._judge_evals(evals, by_id, reports, rubric, judge, guidance_by_id=guidance_by_id)

    e = evals[0]
    # Layer 1 produced ...
    assert e.objective is not None
    # ... and Layer 2 produced, with teaches_principle graded (guidance present).
    assert e.judge is not None
    assert e.judge.is_graded(TEACHES_PRINCIPLE) is True
    assert TEACHES_PRINCIPLE in e.judge.criteria

    # Parity: the guidance theme appears in BOTH the coach and judge prompts.
    assert any("THEMETOKEN" in p for p in provider.prompts)
    assert any("THEMETOKEN" in p for p in judge.prompts)


# --------------------------------------------------------------- 7.4


def test_missing_resource_raises_pedagogy_error(tmp_path: Path) -> None:
    """A missing knowledge resource fails fast with PedagogyError — the
    mechanism eval_run surfaces as 'Knowledge_Resource unavailable' (Req
    7.5); no external fetch is attempted."""
    with pytest.raises(PedagogyError):
        load_resource(tmp_path / "does_not_exist.yaml")


def test_selection_over_seed_is_fast() -> None:
    """Offline selection over the shipped seed returns well within the 5s
    bound (Req 7.3) — it is pure logic."""
    resource = load_resource(default_resource_path())
    report = _FakeEngine().get_position_report(START_FEN)
    t0 = time.perf_counter()
    guidance_for_position(resource, report, "beginner", 3)
    assert time.perf_counter() - t0 < 5.0
