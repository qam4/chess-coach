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
    "BenchmarkError",
    "BenchmarkPosition",
    "GroundTruthPoint",
    "JudgeRubric",
    "JudgeVerdict",
    "ModelSummary",
    "ObjectiveResult",
    "ResponseEval",
    "RunConfig",
    "Scoreboard",
    "VerdictParseError",
    "build_judge_prompt",
    "compute_agreement",
    "evaluate_objective",
    "judge_response",
    "load_benchmark",
    "load_rubric",
    "load_seed_ratings",
    "parse_verdict",
    "persist_results",
]
