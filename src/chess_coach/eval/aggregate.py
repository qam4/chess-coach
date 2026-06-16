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

    @property
    def sem(self) -> float:
        """Standard error of the mean (``std / sqrt(n)``).

        Unlike ``std`` (the per-run spread, which does not shrink with more
        runs), the SEM shrinks as ``1/sqrt(n)`` -- it is how tightly the
        *mean* is pinned down, and the right scale for asking whether a
        difference of means is real. ``0.0`` for ``n < 2``.
        """
        return round(self.std / math.sqrt(self.n), 4) if self.n >= 2 else 0.0


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
    """An off-vs-on comparison for one metric, with two views of the spread.

    ``delta`` is ``on.mean - off.mean``.

    *Conservative band:* ``noise`` is the combined per-run spread
    (root-sum-square of the sample stds) and ``clears_noise`` asks whether
    ``|delta|`` exceeds it -- i.e. is the effect bigger than how much a
    single run jitters. This does not shrink with more runs.

    *Significance:* ``sem_diff`` is the standard error of the difference of
    means (RSS of the two SEMs, which *does* shrink as ``1/sqrt(n)``), and
    ``t_ratio = delta / sem_diff`` is the standard "how many standard errors
    is the gap" measure. ``significance`` labels it: ``significant``
    (``|t| >= 2``), ``suggestive`` (``|t| >= 1``), ``ns`` (smaller),
    ``deterministic`` (zero variance but a real reproducible delta, e.g. a
    temp-0 factual gain), ``no change`` (zero delta, zero variance), or
    ``need >=2 runs/group`` when under-powered. ``t_ratio`` is ``None``
    whenever a numeric ratio is undefined (under-powered or zero variance).

    Both ``clears_noise`` and ``significance`` are ``None``/under-powered
    until each group has ``n >= 2``.
    """

    metric: str
    off: MetricStats
    on: MetricStats
    delta: float
    noise: float
    clears_noise: bool | None
    sem_diff: float
    t_ratio: float | None
    significance: str

    @property
    def verdict(self) -> str:
        """Short human label for the conservative per-run-spread band."""
        if self.clears_noise is None:
            return "need >=2 runs/group"
        if not self.clears_noise:
            return "within noise"
        return "improves" if self.delta > 0 else "regresses"


def _significance(delta: float, sem_diff: float, off: MetricStats, on: MetricStats) -> tuple[float | None, str]:
    """Classify a delta by its standard-error-of-the-difference ratio."""
    if not (off.assessable_spread and on.assessable_spread):
        return None, "need >=2 runs/group"
    if sem_diff == 0.0:
        # Zero variance in both groups: the delta (if any) is perfectly
        # reproducible, not a noisy estimate -- label it as such rather than
        # dividing by zero.
        return None, ("no change" if delta == 0.0 else "deterministic")
    t = round(delta / sem_diff, 2)
    magnitude = abs(t)
    if magnitude >= 2.0:
        label = "significant"
    elif magnitude >= 1.0:
        label = "suggestive"
    else:
        label = "ns"
    return t, label


def compare_metric(metric: str, off: MetricStats, on: MetricStats) -> MetricComparison:
    """Build the off-vs-on :class:`MetricComparison` for one metric."""
    delta = round(on.mean - off.mean, 4)
    noise = round(math.hypot(off.std, on.std), 4)
    if off.assessable_spread and on.assessable_spread:
        clears: bool | None = abs(delta) > noise
    else:
        clears = None
    sem_diff = round(math.hypot(off.sem, on.sem), 4)
    t_ratio, significance = _significance(delta, sem_diff, off, on)
    return MetricComparison(
        metric=metric,
        off=off,
        on=on,
        delta=delta,
        noise=noise,
        clears_noise=clears,
        sem_diff=sem_diff,
        t_ratio=t_ratio,
        significance=significance,
    )


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
    """Render an off-vs-on comparison table with delta, and a standard-
    error-based significance verdict."""
    lines = [
        "=" * 86,
        f"OFF vs ON  -  {model}",
        "=" * 86,
        f"{'metric':<26} {'off':>8} {'on':>8} {'delta':>8} {'SE_diff':>8} {'t':>6}  significance",
        "-" * 86,
    ]
    for c in comparisons:
        t_cell = f"{c.t_ratio:>6.2f}" if c.t_ratio is not None else f"{'--':>6}"
        lines.append(
            f"{c.metric:<26} {c.off.mean:>8.3f} {c.on.mean:>8.3f} "
            f"{c.delta:>+8.3f} {c.sem_diff:>8.3f} {t_cell}  {c.significance}"
        )
    lines.append("-" * 86)
    lines.append("delta = on - off;  SE_diff = std error of the difference (shrinks ~1/sqrt(n))")
    lines.append("t = delta / SE_diff;  significant |t|>=2, suggestive |t|>=1, ns otherwise")
    lines.append("'deterministic' = nonzero delta with zero variance (e.g. temp-0 factual)")
    return "\n".join(lines)
