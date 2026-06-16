"""Aggregate repeated eval runs into mean +/- std (noise control).

A single eval run (one ``results.json``) is a point estimate: one model,
one off/on pass, nine positions, judged once. The backlog's standing
caveat is that such a run sits *within judge noise* -- we cannot tell a
real teaching delta from sampling jitter off a single number. The fix is
to run the benchmark several times and look at the spread.

This module is the instrument for that. It rolls a list of per-run
:class:`~chess_coach.eval.scoring.ModelSummary` objects (one per run, same
model) into per-metric :class:`MetricStats` (mean, sample std, n, range),
and compares an *off* group against an *on* group with an explicit
**noise band** so a reported delta is only called real when it clears the
combined spread of the two groups.

It is pure (no I/O, no LLM): the thin ``scripts/eval_aggregate.py`` CLI
loads the ``results.json`` files and hands the parsed summaries here.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from .scoring import ModelSummary

# The numeric metrics we aggregate across runs, in scoreboard order. Each
# maps a stable key to the ``ModelSummary`` attribute it reads. ``quality``
# is special-cased (it can be ``None`` for an unjudged run) and handled in
# :func:`aggregate_model`.
_METRIC_ATTRS: dict[str, str] = {
    "factual": "factual_mean",
    "pass_rate": "factual_pass_rate",
    "coverage": "coverage_mean",
    "hallucinations": "total_hallucinations",
    "illegal_moves": "total_illegal_moves",
    "direction_contradictions": "direction_contradictions",
    "latency_s": "avg_latency_s",
    "word_count": "avg_word_count",
}


@dataclass(frozen=True)
class MetricStats:
    """Mean / spread of one metric across N runs.

    ``std`` is the *sample* standard deviation (``ddof=1``) and is only
    meaningful once ``n >= 2``; for ``n < 2`` it is ``0.0`` and callers
    should treat the spread as unknown rather than zero. ``values`` keeps
    the raw per-run numbers so nothing is hidden behind the summary.
    """

    n: int
    mean: float
    std: float
    minimum: float
    maximum: float
    values: tuple[float, ...]

    @property
    def assessable_spread(self) -> bool:
        """True when there are enough runs (``n >= 2``) for ``std`` to mean
        something."""
        return self.n >= 2


def aggregate_values(values: list[float]) -> MetricStats:
    """Roll a list of per-run values into a :class:`MetricStats`.

    An empty input yields an all-zero, ``n=0`` stat (used when a metric --
    e.g. quality -- was never recorded in any run). Sample std is computed
    only for ``n >= 2``.
    """
    if not values:
        return MetricStats(n=0, mean=0.0, std=0.0, minimum=0.0, maximum=0.0, values=())
    n = len(values)
    std = statistics.stdev(values) if n >= 2 else 0.0
    return MetricStats(
        n=n,
        mean=round(statistics.fmean(values), 4),
        std=round(std, 4),
        minimum=round(min(values), 4),
        maximum=round(max(values), 4),
        values=tuple(round(v, 4) for v in values),
    )


@dataclass(frozen=True)
class AggregatedModel:
    """All metrics for one model aggregated across its runs."""

    model: str
    n_runs: int
    metrics: dict[str, MetricStats]


def aggregate_model(model: str, summaries: list[ModelSummary]) -> AggregatedModel:
    """Aggregate one model's per-run summaries (all must share ``model``).

    Each numeric scoreboard metric becomes a :class:`MetricStats` over the
    runs. ``quality`` is included only over the runs that actually produced
    a judged score (``quality_mean is not None``); a run with no judge
    verdicts contributes nothing to the quality stat rather than a
    misleading zero.
    """
    metrics: dict[str, MetricStats] = {}
    for key, attr in _METRIC_ATTRS.items():
        metrics[key] = aggregate_values([float(getattr(s, attr)) for s in summaries])
    quality_values = [s.quality_mean for s in summaries if s.quality_mean is not None]
    metrics["quality"] = aggregate_values(quality_values)
    return AggregatedModel(model=model, n_runs=len(summaries), metrics=metrics)


def aggregate_runs(summaries: list[ModelSummary]) -> list[AggregatedModel]:
    """Group a flat list of per-run summaries by model and aggregate each.

    ``summaries`` is the concatenation of every run's per-model rollups
    (each run contributes one :class:`ModelSummary` per model). Results are
    ordered by model name for a stable report.
    """
    by_model: dict[str, list[ModelSummary]] = {}
    for s in summaries:
        by_model.setdefault(s.model, []).append(s)
    return [aggregate_model(m, by_model[m]) for m in sorted(by_model)]


@dataclass(frozen=True)
class MetricComparison:
    """An off-vs-on comparison for one metric, with a noise band.

    ``delta`` is ``on.mean - off.mean``. ``noise`` is the combined spread
    of the two groups (root-sum-square of the sample stds) -- the band a
    real effect must clear. ``clears_noise`` is ``True``/``False`` once both
    groups have ``n >= 2``, and ``None`` when the spread cannot be assessed
    (fewer than two runs in either group), so an under-powered comparison
    is reported honestly rather than as a spurious "significant" result.
    """

    metric: str
    off: MetricStats
    on: MetricStats
    delta: float
    noise: float
    clears_noise: bool | None

    @property
    def verdict(self) -> str:
        """Short human label for the comparison outcome."""
        if self.clears_noise is None:
            return "need >=2 runs/group"
        if not self.clears_noise:
            return "within noise"
        return "improves" if self.delta > 0 else "regresses"


def compare_metric(metric: str, off: MetricStats, on: MetricStats) -> MetricComparison:
    """Build the off-vs-on :class:`MetricComparison` for one metric."""
    delta = round(on.mean - off.mean, 4)
    noise = round(math.hypot(off.std, on.std), 4)
    if off.assessable_spread and on.assessable_spread:
        clears: bool | None = abs(delta) > noise
    else:
        clears = None
    return MetricComparison(metric=metric, off=off, on=on, delta=delta, noise=noise, clears_noise=clears)


def compare_off_on(off: AggregatedModel, on: AggregatedModel) -> list[MetricComparison]:
    """Compare two aggregated groups (off vs on) across every shared metric.

    Metrics are compared in scoreboard order with ``quality`` last (the
    headline teaching axis). A metric present in one group but not the
    other is skipped.
    """
    order = [*_METRIC_ATTRS.keys(), "quality"]
    return [
        compare_metric(key, off.metrics[key], on.metrics[key])
        for key in order
        if key in off.metrics and key in on.metrics
    ]


def render_aggregate(models: list[AggregatedModel]) -> str:
    """Render per-model ``mean +/- std (n)`` for each metric."""
    if not models:
        return "(no runs)"
    lines: list[str] = []
    for m in models:
        lines.append("=" * 78)
        lines.append(f"{m.model}  ({m.n_runs} run{'s' if m.n_runs != 1 else ''})")
        lines.append("=" * 78)
        lines.append(f"{'metric':<26} {'mean':>8} {'std':>8} {'min':>8} {'max':>8} {'n':>4}")
        lines.append("-" * 78)
        for key, stats in m.metrics.items():
            lines.append(
                f"{key:<26} {stats.mean:>8.3f} {stats.std:>8.3f} "
                f"{stats.minimum:>8.3f} {stats.maximum:>8.3f} {stats.n:>4}"
            )
        lines.append("")
    return "\n".join(lines).rstrip()


def render_comparison(model: str, comparisons: list[MetricComparison]) -> str:
    """Render an off-vs-on comparison table with deltas and noise band."""
    lines = [
        "=" * 78,
        f"OFF vs ON  -  {model}",
        "=" * 78,
        f"{'metric':<26} {'off':>9} {'on':>9} {'delta':>9} {'noise':>9}  verdict",
        "-" * 78,
    ]
    for c in comparisons:
        off_cell = f"{c.off.mean:.3f}"
        on_cell = f"{c.on.mean:.3f}"
        lines.append(f"{c.metric:<26} {off_cell:>9} {on_cell:>9} {c.delta:>+9.3f} {c.noise:>9.3f}  {c.verdict}")
    lines.append("-" * 78)
    lines.append("delta = on - off;  noise = combined sample std (root-sum-square)")
    lines.append("'within noise' = |delta| <= noise;  needs >=2 runs per group to assess")
    return "\n".join(lines)
