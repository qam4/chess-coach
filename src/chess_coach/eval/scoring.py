"""Aggregation, scoreboard, and run recording for the eval harness.

Takes the per-response Layer 1 (and optional Layer 2) results and
rolls them into a per-model `Scoreboard`, then persists the full run
(config + every response) to disk so prompt changes can be diffed
over time.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .objective import PASS_THRESHOLD, ObjectiveResult


class _QualityVerdict(Protocol):
    """Structural view of the Layer 2 verdict the scoreboard needs.

    The full `JudgeVerdict` (judge.py, Task 5) satisfies this — typing
    against the protocol lets scoring.py land before the judge does,
    with no forward import."""

    quality_score: float


# --------------------------------------------------------------- per response


@dataclass
class ResponseEval:
    """Everything we computed for one (position, model) coaching
    response. ``judge`` is None until Layer 2 runs."""

    position_id: str
    model: str
    response: str
    word_count: int
    latency_s: float
    objective: ObjectiveResult
    judge: _QualityVerdict | None = None
    error: str | None = None  # set when generation/judging failed


# --------------------------------------------------------------- per model


@dataclass
class ModelSummary:
    model: str
    n: int
    factual_mean: float
    factual_pass_rate: float
    coverage_mean: float
    total_hallucinations: int
    total_illegal_moves: int
    direction_contradictions: int
    avg_latency_s: float
    avg_word_count: float
    judged_n: int
    quality_mean: float | None  # None when no judge verdicts present
    errors: int


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def aggregate_quality(evals: list[ResponseEval]) -> tuple[float | None, list[str]]:
    """Aggregate Layer-2 quality over scorable responses (Req 5.5).

    A response is EXCLUDED from the aggregate when it is missing a Layer 1
    or Layer 2 score — i.e. generation failed (``error`` set, so its
    factual score is a placeholder zero) or it was never judged
    (``judge is None``). Returns ``(mean_or_None, excluded_position_ids)``
    so the caller can both report the aggregate and name what was left out.
    """
    excluded = [e.position_id for e in evals if e.error is not None or e.judge is None]
    scored = [e.judge.quality_score for e in evals if e.error is None and e.judge is not None]
    mean = round(_mean(scored), 4) if scored else None
    return mean, excluded


def quality_delta(enabled_mean: float | None, disabled_mean: float | None) -> float | None:
    """The teaching-quality delta (enabled minus disabled), or None (Req 5.4).

    Returns ``None`` when either aggregate is missing (no judged responses
    in that run), so a delta is reported only when both runs produced a
    quality score over the identical scenario set.
    """
    if enabled_mean is None or disabled_mean is None:
        return None
    return round(enabled_mean - disabled_mean, 4)


def summarize_model(model: str, evals: list[ResponseEval]) -> ModelSummary:
    """Roll up one model's responses. ``evals`` must all share
    ``model``; callers group first."""
    n = len(evals)
    factual_scores = [e.objective.factual_score for e in evals]
    passed = [e for e in evals if e.objective.passed]
    judged = [e for e in evals if e.judge is not None]
    quality_scores = [e.judge.quality_score for e in judged if e.judge is not None]

    return ModelSummary(
        model=model,
        n=n,
        factual_mean=round(_mean(factual_scores), 4),
        factual_pass_rate=round(len(passed) / n, 4) if n else 0.0,
        coverage_mean=round(_mean([e.objective.coverage_fraction for e in evals]), 4),
        total_hallucinations=sum(len(e.objective.hallucinations) for e in evals),
        total_illegal_moves=sum(len(e.objective.illegal_moves) for e in evals),
        direction_contradictions=sum(1 for e in evals if e.objective.eval_direction_ok is False),
        avg_latency_s=round(_mean([e.latency_s for e in evals]), 2),
        avg_word_count=round(_mean([float(e.word_count) for e in evals]), 1),
        judged_n=len(judged),
        quality_mean=round(_mean(quality_scores), 4) if quality_scores else None,
        errors=sum(1 for e in evals if e.error),
    )


# --------------------------------------------------------------- scoreboard


@dataclass
class Scoreboard:
    summaries: list[ModelSummary] = field(default_factory=list)

    @classmethod
    def from_response_evals(cls, evals: list[ResponseEval]) -> Scoreboard:
        by_model: dict[str, list[ResponseEval]] = {}
        for e in evals:
            by_model.setdefault(e.model, []).append(e)
        summaries = [summarize_model(m, es) for m, es in by_model.items()]
        # Stable, useful ordering: best factual mean first.
        summaries.sort(key=lambda s: (-s.factual_mean, s.model))
        return cls(summaries=summaries)

    def render(self) -> str:
        if not self.summaries:
            return "(no results)"
        lines = [
            "=" * 78,
            "COACHING EVAL SCOREBOARD",
            "=" * 78,
            f"{'model':<24} {'fact':>6} {'pass%':>6} {'cov':>6} "
            f"{'hall':>5} {'illeg':>6} {'dir!':>5} {'qual':>6} {'lat':>7} {'words':>6}",
            "-" * 78,
        ]
        for s in self.summaries:
            quality = f"{s.quality_mean:.2f}" if s.quality_mean is not None else "  n/a"
            lines.append(
                f"{s.model:<24} {s.factual_mean:>6.2f} {s.factual_pass_rate * 100:>5.0f}% "
                f"{s.coverage_mean:>6.2f} {s.total_hallucinations:>5} "
                f"{s.total_illegal_moves:>6} {s.direction_contradictions:>5} "
                f"{quality:>6} {s.avg_latency_s:>6.1f}s {s.avg_word_count:>6.0f}"
            )
        lines.append("-" * 78)
        lines.append(
            "fact=mean factual score  pass%=share >= "
            f"{PASS_THRESHOLD:.2f}  cov=key-fact coverage  "
            "hall/illeg/dir!=factual errors  qual=judge score"
        )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {"summaries": [asdict(s) for s in self.summaries]}


# --------------------------------------------------------------- run recording


BENCHMARK_VERSION = 1


@dataclass
class RunConfig:
    """Captured with every run so results are reproducible/auditable."""

    models: list[str]
    judge_model: str | None
    rubric_version: str | None
    benchmark_version: int
    timestamp: str
    benchmark_path: str = ""
    temperature: float = 0.0
    # Pedagogy-layer guidance injection mode (Req 5): "on" injects the
    # selected guidance into both the coach and judge prompts, "off" is the
    # baseline. ``guidance_max`` is the per-position selection cap.
    guidance: str = "off"
    guidance_max: int = 0

    @classmethod
    def create(
        cls,
        *,
        models: list[str],
        judge_model: str | None = None,
        rubric_version: str | None = None,
        benchmark_path: str = "",
        benchmark_version: int = BENCHMARK_VERSION,
        temperature: float = 0.0,
        guidance: str = "off",
        guidance_max: int = 0,
    ) -> RunConfig:
        return cls(
            models=list(models),
            judge_model=judge_model,
            rubric_version=rubric_version,
            benchmark_version=benchmark_version,
            timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
            benchmark_path=benchmark_path,
            temperature=temperature,
            guidance=guidance,
            guidance_max=guidance_max,
        )


def _verdict_to_dict(judge: _QualityVerdict | None) -> dict[str, Any] | None:
    if judge is None:
        return None
    if is_dataclass(judge) and not isinstance(judge, type):
        return asdict(judge)
    # Fallback for non-dataclass verdicts (shouldn't happen in practice).
    return {"quality_score": judge.quality_score}


def _response_to_dict(e: ResponseEval) -> dict[str, Any]:
    return {
        "position_id": e.position_id,
        "model": e.model,
        "response": e.response,
        "word_count": e.word_count,
        "latency_s": e.latency_s,
        "objective": asdict(e.objective),
        "judge": _verdict_to_dict(e.judge),
        "error": e.error,
    }


def persist_results(
    out_dir: str | Path,
    config: RunConfig,
    evals: list[ResponseEval],
    scoreboard: Scoreboard,
) -> tuple[Path, Path]:
    """Write the full run to ``results.json`` and a human-readable
    ``summary.txt``. Returns the two paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {
        "run": asdict(config),
        "scoreboard": scoreboard.to_dict(),
        "responses": [_response_to_dict(e) for e in evals],
    }
    results_path = out_dir / "results.json"
    results_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    summary_path = out_dir / "summary.txt"
    header = (
        f"Run: {config.timestamp}\n"
        f"Models: {', '.join(config.models)}\n"
        f"Judge: {config.judge_model or '(none)'}  "
        f"Rubric: {config.rubric_version or '(none)'}  "
        f"Benchmark v{config.benchmark_version}\n"
        f"Guidance: {config.guidance}"
        f"{f' (max {config.guidance_max})' if config.guidance == 'on' else ''}\n\n"
    )
    summary_path.write_text(header + scoreboard.render() + "\n", encoding="utf-8")

    return results_path, summary_path
