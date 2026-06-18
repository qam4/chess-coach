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

# Two-sided 95% critical t-values by degrees of freedom. With only a handful
# of runs the t-distribution has fat tails, so "significant" must clear a far
# higher bar than the large-sample |t|>=1.96: at df=2 it is 4.30, at df=3 it
# is 3.18. A flat |t|>=2 rule (the previous heuristic) over-calls small-n
# results as significant; this table makes the verdict honest about df.
_CRITICAL_T_95: dict[int, float] = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
    11: 2.201,
    12: 2.179,
    13: 2.160,
    14: 2.145,
    15: 2.131,
    16: 2.120,
    17: 2.110,
    18: 2.101,
    19: 2.093,
    20: 2.086,
}
_CRITICAL_T_95_LARGE = 1.96  # df > 20: normal-approximation tail


def _critical_t_95(df: float) -> float:
    """Two-sided 95% critical t for ``df`` degrees of freedom.

    Non-integer Welch df is floored (conservative — a lower df has a higher
    critical value), clamped to ``>= 1``, and falls back to the
    normal-approximation 1.96 beyond the table.
    """
    d = max(1, int(df))
    return _CRITICAL_T_95.get(d, _CRITICAL_T_95_LARGE)


def _welch_df(off: MetricStats, on: MetricStats) -> float:
    """Welch-Satterthwaite degrees of freedom for two samples of unequal
    variance. Both groups must have ``n >= 2``."""
    a = off.std**2 / off.n
    b = on.std**2 / on.n
    denom = (a**2) / (off.n - 1) + (b**2) / (on.n - 1)
    if denom == 0.0:
        # Both variances zero -> handled by the deterministic branch upstream;
        # return n-1 as a harmless fallback.
        return float(off.n + on.n - 2)
    return (a + b) ** 2 / denom


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
    is the gap" measure. ``significance`` labels it with a **df-aware Welch
    t-test**: ``significant`` (``|t| >= t_crit`` for the Welch-Satterthwaite
    ``df`` at two-sided 95% — far above 1.96 at small n), ``suggestive``
    (``|t| >= 1`` but below that bar), ``ns`` (smaller), ``deterministic``
    (zero variance but a real reproducible delta, e.g. a temp-0 factual
    gain), ``no change`` (zero delta, zero variance), or ``need >=2
    runs/group`` when under-powered. ``t_ratio``, ``df`` and ``t_crit`` are
    ``None`` whenever undefined (under-powered or zero variance).

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
    df: float | None
    t_crit: float | None

    @property
    def verdict(self) -> str:
        """Short human label for the conservative per-run-spread band."""
        if self.clears_noise is None:
            return "need >=2 runs/group"
        if not self.clears_noise:
            return "within noise"
        return "improves" if self.delta > 0 else "regresses"


def _significance(
    delta: float, sem_diff: float, off: MetricStats, on: MetricStats
) -> tuple[float | None, str, float | None, float | None]:
    """Classify a delta with a df-aware Welch t-test.

    Returns ``(t_ratio, label, df, t_crit)``. ``significant`` requires
    ``|t| >= t_crit(df)`` (the proper two-sided 95% critical value for the
    Welch-Satterthwaite degrees of freedom, which is much larger than 1.96
    at small n); ``suggestive`` is ``|t| >= 1`` but below that bar; ``ns``
    is smaller. ``deterministic`` / ``no change`` cover zero variance, and
    ``need >=2 runs/group`` covers the under-powered case.
    """
    if not (off.assessable_spread and on.assessable_spread):
        return None, "need >=2 runs/group", None, None
    if sem_diff == 0.0:
        # Zero variance in both groups: the delta (if any) is perfectly
        # reproducible, not a noisy estimate -- label it as such rather than
        # dividing by zero.
        return None, ("no change" if delta == 0.0 else "deterministic"), None, None
    t = round(delta / sem_diff, 2)
    df = _welch_df(off, on)
    t_crit = _critical_t_95(df)
    magnitude = abs(t)
    if magnitude >= t_crit:
        label = "significant"
    elif magnitude >= 1.0:
        label = "suggestive"
    else:
        label = "ns"
    return t, label, round(df, 1), round(t_crit, 2)


def compare_metric(metric: str, off: MetricStats, on: MetricStats) -> MetricComparison:
    """Build the off-vs-on :class:`MetricComparison` for one metric."""
    delta = round(on.mean - off.mean, 4)
    noise = round(math.hypot(off.std, on.std), 4)
    if off.assessable_spread and on.assessable_spread:
        clears: bool | None = abs(delta) > noise
    else:
        clears = None
    sem_diff = round(math.hypot(off.sem, on.sem), 4)
    t_ratio, significance, df, t_crit = _significance(delta, sem_diff, off, on)
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
        df=df,
        t_crit=t_crit,
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
    """Render an off-vs-on comparison table with delta and a df-aware
    Welch-t significance verdict."""
    lines = [
        "=" * 92,
        f"OFF vs ON  -  {model}",
        "=" * 92,
        f"{'metric':<26} {'off':>8} {'on':>8} {'delta':>8} {'t':>6} {'df':>5} {'t*.95':>6}  significance",
        "-" * 92,
    ]
    for c in comparisons:
        t_cell = f"{c.t_ratio:>6.2f}" if c.t_ratio is not None else f"{'--':>6}"
        df_cell = f"{c.df:>5.1f}" if c.df is not None else f"{'--':>5}"
        crit_cell = f"{c.t_crit:>6.2f}" if c.t_crit is not None else f"{'--':>6}"
        lines.append(
            f"{c.metric:<26} {c.off.mean:>8.3f} {c.on.mean:>8.3f} "
            f"{c.delta:>+8.3f} {t_cell} {df_cell} {crit_cell}  {c.significance}"
        )
    lines.append("-" * 92)
    lines.append("t = delta / SE_diff (Welch);  significant |t| >= t*.95 (critical t for df)")
    lines.append("suggestive |t| >= 1 but below t*.95;  ns smaller;  small n -> high t*.95")
    lines.append("'deterministic' = nonzero delta with zero variance (e.g. temp-0 factual)")
    return "\n".join(lines)


# --------------------------------------------------------------- pairwise A/B


@dataclass(frozen=True)
class PairwiseSummary:
    """Win/loss/tie tally of a pairwise A-vs-B judging run, with a sign test.

    Pairwise judging asks the judge "which of these two is better?" rather than
    scoring each absolutely -- removing the absolute-anchoring noise that makes
    small teaching deltas invisible. ``win_rate_b`` is over *decisive*
    comparisons (ties excluded); ``p_value`` is a two-sided exact sign test of
    "B is preferred at rate 0.5" (the null = no real difference).
    """

    label_a: str
    label_b: str
    n: int
    wins_a: int
    wins_b: int
    ties: int
    n_decisive: int
    win_rate_b: float
    p_value: float
    significant: bool

    @property
    def verdict(self) -> str:
        if self.n_decisive == 0:
            return "no decisive comparisons"
        if self.wins_a == self.wins_b:
            return f"tied ({self.wins_a}-{self.wins_b}, {self.ties} ties)"
        winner = self.label_b if self.wins_b > self.wins_a else self.label_a
        tail = "significant" if self.significant else "not significant"
        return f"{winner} wins ({self.wins_b}-{self.wins_a}, p={self.p_value:.3f}, {tail})"


def _sign_test_p(wins_a: int, wins_b: int) -> float:
    """Two-sided exact sign test of fairness given decisive trials.

    Under the null (no preference) decisive outcomes are Binom(n, 0.5). The
    two-sided p-value sums the probability of every outcome at least as extreme
    as the observed split. Stdlib only.
    """
    n = wins_a + wins_b
    if n == 0:
        return 1.0
    observed = math.comb(n, max(wins_a, wins_b))
    tail = sum(math.comb(n, i) for i in range(n + 1) if math.comb(n, i) <= observed)
    p: float = tail / (2**n)
    return min(1.0, p)


def summarize_pairwise(winners: list[str], label_a: str, label_b: str) -> PairwiseSummary:
    """Tally pairwise winners (each ``label_a`` / ``label_b`` / ``"tie"``)."""
    wins_a = sum(1 for w in winners if w == label_a)
    wins_b = sum(1 for w in winners if w == label_b)
    ties = sum(1 for w in winners if w == "tie")
    n_decisive = wins_a + wins_b
    p = _sign_test_p(wins_a, wins_b)
    return PairwiseSummary(
        label_a=label_a,
        label_b=label_b,
        n=len(winners),
        wins_a=wins_a,
        wins_b=wins_b,
        ties=ties,
        n_decisive=n_decisive,
        win_rate_b=round(wins_b / n_decisive, 4) if n_decisive else 0.0,
        p_value=round(p, 4),
        significant=p < 0.05,
    )


def render_pairwise(summary: PairwiseSummary) -> str:
    """Render the pairwise A/B result."""
    s = summary
    lines = [
        "=" * 70,
        f"PAIRWISE  {s.label_a}  vs  {s.label_b}",
        "=" * 70,
        f"comparisons : {s.n}  (decisive {s.n_decisive}, ties {s.ties})",
        f"{s.label_a} wins : {s.wins_a}",
        f"{s.label_b} wins : {s.wins_b}",
        f"{s.label_b} win-rate (of decisive): {s.win_rate_b:.0%}",
        f"two-sided sign test p : {s.p_value:.3f}",
        "-" * 70,
        f"verdict: {s.verdict}",
        "-" * 70,
        "win-rate excludes ties; p<0.05 => the preference is unlikely to be chance",
    ]
    return "\n".join(lines)
