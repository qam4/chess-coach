"""Coaching evaluation harness.

Three layers (see `.kiro/specs/coaching-eval/`):

1. Objective, engine-grounded checks (`objective.py`) — hallucination,
   illegal moves, eval direction, key-fact coverage. Deterministic,
   no LLM, no cost.
2. Frontier LLM-as-judge (`judge.py`) — coaching-quality rubric,
   grounded in the engine report.
3. Human calibration — seed ratings + judge-agreement reporting.

This module exposes the benchmark data model; the layers build on it.
"""

from __future__ import annotations

from .aggregate import (
    AggregatedModel,
    MetricComparison,
    MetricStats,
    aggregate_model,
    aggregate_runs,
    aggregate_values,
    compare_metric,
    compare_off_on,
    render_aggregate,
    render_comparison,
)
from .benchmark import (
    BenchmarkError,
    BenchmarkPosition,
    GroundTruthPoint,
    load_benchmark,
)
from .calibrate import AgreementReport, compute_agreement, load_seed_ratings
from .judge import (
    JudgeRubric,
    JudgeVerdict,
    VerdictParseError,
    build_judge_prompt,
    judge_response,
    load_rubric,
    parse_verdict,
)
from .objective import ObjectiveResult, evaluate_objective
from .scoring import (
    ModelSummary,
    ResponseEval,
    RunConfig,
    Scoreboard,
    persist_results,
)

__all__ = [
    "AgreementReport",
    "AggregatedModel",
    "BenchmarkError",
    "BenchmarkPosition",
    "GroundTruthPoint",
    "JudgeRubric",
    "JudgeVerdict",
    "MetricComparison",
    "MetricStats",
    "ModelSummary",
    "ObjectiveResult",
    "ResponseEval",
    "RunConfig",
    "Scoreboard",
    "VerdictParseError",
    "aggregate_model",
    "aggregate_runs",
    "aggregate_values",
    "build_judge_prompt",
    "compare_metric",
    "compare_off_on",
    "compute_agreement",
    "evaluate_objective",
    "judge_response",
    "load_benchmark",
    "load_rubric",
    "load_seed_ratings",
    "parse_verdict",
    "persist_results",
    "render_aggregate",
    "render_comparison",
]
