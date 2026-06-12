"""Integration test for the Layer 1 orchestrator (Task 4).

The coaching-capable Blunder build isn't available on every dev box
(the local Windows dev build returns coaching_available=False), so we
exercise the orchestrator's wiring with a stub engine + stub provider.
This is deterministic and proves the full generate -> objective ->
scoreboard pipeline without an engine or an LLM.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from chess_coach.eval import Scoreboard
from chess_coach.eval.benchmark import BenchmarkPosition, GroundTruthPoint
from chess_coach.models import (
    EvalBreakdown,
    KingSafety,
    PawnFeatures,
    PositionReport,
)

# Load scripts/eval_run.py as a module.
_EVAL_RUN_PATH = Path(__file__).resolve().parent.parent / "scripts" / "eval_run.py"
_spec = importlib.util.spec_from_file_location("eval_run", _EVAL_RUN_PATH)
assert _spec and _spec.loader
eval_run = importlib.util.module_from_spec(_spec)
sys.modules["eval_run"] = eval_run
_spec.loader.exec_module(eval_run)


START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
HANGING_FEN = "r1bqkb1r/pppppppp/2n5/4N3/4n3/8/PPPP1PPP/RNBQKB1R w KQkq - 0 4"


def _mk_report(fen: str, eval_cp: int = 0) -> PositionReport:
    eb = EvalBreakdown(material=0, mobility=0, king_safety=0, pawn_structure=0)
    empty = {"white": [], "black": []}
    return PositionReport(
        fen=fen,
        eval_cp=eval_cp,
        eval_breakdown=eb,
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


class _FakeEngine:
    """Returns canned reports; raises on a configured 'bad' fen."""

    def __init__(self, bad_fen: str | None = None) -> None:
        self.bad_fen = bad_fen

    def get_position_report(self, fen: str, multipv: int = 3, depth: int | None = None) -> PositionReport:
        if fen == self.bad_fen:
            raise RuntimeError("engine boom")
        return _mk_report(fen)


class _FakeProvider:
    def __init__(self, text: str = "coaching", available: bool = True, raises: bool = False):
        self.text = text
        self.available = available
        self.raises = raises

    def is_available(self) -> bool:
        return self.available

    def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7) -> str:
        if self.raises:
            raise RuntimeError("gen boom")
        return self.text


def _positions() -> list[BenchmarkPosition]:
    return [
        BenchmarkPosition(
            id="start",
            fen=START_FEN,
            level="beginner",
            phase="opening",
            points=(GroundTruthPoint("free", "center"),),
        ),
        BenchmarkPosition(
            id="hang",
            fen=HANGING_FEN,
            level="intermediate",
            phase="opening",
            points=(GroundTruthPoint("hanging_piece", "e4"),),
        ),
    ]


# --------------------------------------------------------------- analyze


def test_analyze_positions_caches_reports() -> None:
    positions = _positions()
    reports = eval_run._analyze_positions(_FakeEngine(), positions, 3, None)
    assert set(reports) == {"start", "hang"}


def test_analyze_positions_skips_engine_errors() -> None:
    positions = _positions()
    reports = eval_run._analyze_positions(_FakeEngine(bad_fen=START_FEN), positions, 3, None)
    # The bad position is skipped; the good one survives.
    assert set(reports) == {"hang"}


# --------------------------------------------------------------- run model


def test_run_model_scores_responses() -> None:
    positions = _positions()
    reports = eval_run._analyze_positions(_FakeEngine(), positions, 3, None)
    # Response references the center (start) but not e4 (hang).
    provider = _FakeProvider(text="Fight for the center with your pieces.")
    evals = eval_run._run_model(provider, "fake", positions, reports)

    assert len(evals) == 2
    by_id = {e.position_id: e for e in evals}
    # 'start' covers 'center' -> full credit, no errors.
    assert by_id["start"].objective.factual_score == 1.0
    # 'hang' misses the e4 hanging piece -> coverage 0.
    assert by_id["hang"].objective.factual_score == 0.0


def test_run_model_full_coverage_on_hanging() -> None:
    positions = _positions()
    reports = eval_run._analyze_positions(_FakeEngine(), positions, 3, None)
    provider = _FakeProvider(text="Center matters. Your knight on e4 is hanging.")
    evals = eval_run._run_model(provider, "fake", positions, reports)
    by_id = {e.position_id: e for e in evals}
    assert by_id["hang"].objective.factual_score == 1.0


def test_run_model_unavailable_returns_empty() -> None:
    positions = _positions()
    reports = eval_run._analyze_positions(_FakeEngine(), positions, 3, None)
    evals = eval_run._run_model(_FakeProvider(available=False), "fake", positions, reports)
    assert evals == []


def test_run_model_generation_error_records_zero() -> None:
    positions = _positions()
    reports = eval_run._analyze_positions(_FakeEngine(), positions, 3, None)
    evals = eval_run._run_model(_FakeProvider(raises=True), "fake", positions, reports)
    assert len(evals) == 2
    assert all(e.error is not None for e in evals)
    assert all(e.objective.factual_score == 0.0 for e in evals)


def test_pipeline_to_scoreboard() -> None:
    positions = _positions()
    reports = eval_run._analyze_positions(_FakeEngine(), positions, 3, None)
    evals = eval_run._run_model(_FakeProvider(text="Center. Knight on e4 hangs."), "fake", positions, reports)
    sb = Scoreboard.from_response_evals(evals)
    assert len(sb.summaries) == 1
    assert sb.summaries[0].model == "fake"
    assert "SCOREBOARD" in sb.render()


def test_zero_objective_counts_referenceable_total() -> None:
    pos = BenchmarkPosition(
        id="x",
        fen=START_FEN,
        level="beginner",
        phase="endgame",
        points=(
            GroundTruthPoint("free", "king"),
            GroundTruthPoint("phase", "endgame"),  # not referenceable -> excluded
        ),
    )
    zero = eval_run._zero_objective(pos)
    assert zero.factual_score == 0.0
    assert zero.coverage_total == 1  # only the free point counts


# --------------------------------------------------------------- judge wiring (Task 6)


def _valid_verdict_json() -> str:
    import json

    from chess_coach.eval.judge import default_rubric_path, load_rubric

    keys = load_rubric(default_rubric_path()).keys()
    return json.dumps(
        {
            "criteria": {k: {"pass": True, "reason": "ok"} for k in keys},
            "contradictions": [],
            "notes": "",
        }
    )


class _FakeJudge:
    def __init__(self, reply: str, raises: bool = False):
        self.reply = reply
        self.raises = raises
        self.model = "fake-judge"

    def generate(self, prompt: str, max_tokens: int = 900, temperature: float = 0.0) -> str:
        if self.raises:
            raise RuntimeError("judge endpoint down")
        return self.reply


def test_judge_evals_sets_verdicts() -> None:
    from chess_coach.eval.judge import default_rubric_path, load_rubric

    positions = _positions()
    reports = eval_run._analyze_positions(_FakeEngine(), positions, 3, None)
    evals = eval_run._run_model(_FakeProvider(text="Center."), "fake", positions, reports)
    rubric = load_rubric(default_rubric_path())
    by_id = {p.id: p for p in positions}

    eval_run._judge_evals(evals, by_id, reports, rubric, _FakeJudge(_valid_verdict_json()))
    assert all(e.judge is not None for e in evals)
    assert all(e.judge.quality_score == 1.0 for e in evals)
    sb = Scoreboard.from_response_evals(evals)
    assert sb.summaries[0].quality_mean == 1.0


def test_judge_failure_leaves_layer1_intact() -> None:
    from chess_coach.eval.judge import default_rubric_path, load_rubric

    positions = _positions()
    reports = eval_run._analyze_positions(_FakeEngine(), positions, 3, None)
    evals = eval_run._run_model(_FakeProvider(text="Center."), "fake", positions, reports)
    layer1_scores = [e.objective.factual_score for e in evals]
    rubric = load_rubric(default_rubric_path())
    by_id = {p.id: p for p in positions}

    eval_run._judge_evals(evals, by_id, reports, rubric, _FakeJudge("", raises=True))
    assert all(e.judge is None for e in evals)
    assert [e.objective.factual_score for e in evals] == layer1_scores


def test_judge_skips_generation_failures() -> None:
    from chess_coach.eval.judge import default_rubric_path, load_rubric

    positions = _positions()
    reports = eval_run._analyze_positions(_FakeEngine(), positions, 3, None)
    evals = eval_run._run_model(_FakeProvider(raises=True), "fake", positions, reports)
    rubric = load_rubric(default_rubric_path())
    by_id = {p.id: p for p in positions}
    eval_run._judge_evals(evals, by_id, reports, rubric, _FakeJudge(_valid_verdict_json()))
    assert all(e.judge is None for e in evals)
