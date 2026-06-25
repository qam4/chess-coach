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
    PairwiseSummary,
    aggregate_model,
    aggregate_runs,
    aggregate_values,
    compare_metric,
    compare_off_on,
    render_aggregate,
    render_comparison,
    render_pairwise,
    summarize_pairwise,
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
    build_move_feedback_pairwise_prompt,
    judge_response,
    load_rubric,
    pairwise_compare_move,
    parse_verdict,
)
from .move_feedback import (
    MoveFeedbackError,
    MoveFeedbackScenario,
    default_move_feedback_path,
    load_move_feedback_scenarios,
    run_move_feedback_pairwise,
    summarize_skips,
)
from .objective import ObjectiveResult, evaluate_objective
from .profile import (
    CapabilityProfile,
    ConfigRecommendation,
    ConfigSuggestion,
    DimensionResult,
    ProfileThresholds,
    recommend,
    render_profile,
    render_recommendation,
)
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
    "CapabilityProfile",
    "ConfigRecommendation",
    "ConfigSuggestion",
    "DimensionResult",
    "GroundTruthPoint",
    "JudgeRubric",
    "JudgeVerdict",
    "MetricComparison",
    "MetricStats",
    "ModelSummary",
    "MoveFeedbackError",
    "MoveFeedbackScenario",
    "ObjectiveResult",
    "PairwiseSummary",
    "ProfileThresholds",
    "ResponseEval",
    "RunConfig",
    "Scoreboard",
    "VerdictParseError",
    "aggregate_model",
    "aggregate_runs",
    "aggregate_values",
    "build_judge_prompt",
    "build_move_feedback_pairwise_prompt",
    "compare_metric",
    "compare_off_on",
    "compute_agreement",
    "default_move_feedback_path",
    "evaluate_objective",
    "judge_response",
    "load_benchmark",
    "load_move_feedback_scenarios",
    "load_rubric",
    "load_seed_ratings",
    "pairwise_compare_move",
    "parse_verdict",
    "persist_results",
    "recommend",
    "render_aggregate",
    "render_comparison",
    "render_pairwise",
    "render_profile",
    "render_recommendation",
    "run_move_feedback_pairwise",
    "summarize_pairwise",
    "summarize_skips",
]
