"""Tests for the repeated-run aggregation instrument (eval/aggregate.py)."""

from __future__ import annotations

import math

import pytest

from chess_coach.eval import (
    ModelSummary,
    aggregate_model,
    aggregate_runs,
    aggregate_values,
    compare_metric,
    compare_off_on,
    render_aggregate,
    render_comparison,
)


def _summary(
    model: str = "m",
    *,
    factual: float = 0.30,
    pass_rate: float = 0.0,
    coverage: float = 0.30,
    hall: int = 0,
    illegal: int = 0,
    direction: int = 0,
    latency: float = 7.0,
    words: float = 160.0,
    quality: float | None = 0.26,
) -> ModelSummary:
    return ModelSummary(
        model=model,
        n=9,
        factual_mean=factual,
        factual_pass_rate=pass_rate,
        coverage_mean=coverage,
        total_hallucinations=hall,
        total_illegal_moves=illegal,
        direction_contradictions=direction,
        avg_latency_s=latency,
        avg_word_count=words,
        judged_n=9 if quality is not None else 0,
        quality_mean=quality,
        errors=0,
    )


# --------------------------------------------------------------- aggregate_values


def test_aggregate_values_empty_is_zero_n() -> None:
    s = aggregate_values([])
    assert s.n == 0
    assert s.mean == 0.0
    assert s.std == 0.0
    assert s.values == ()
    assert s.assessable_spread is False


def test_aggregate_values_single_has_zero_std_and_unassessable() -> None:
    s = aggregate_values([0.45])
    assert s.n == 1
    assert s.mean == 0.45
    assert s.std == 0.0
    assert s.minimum == s.maximum == 0.45
    assert s.assessable_spread is False


def test_aggregate_values_multiple_mean_std_range() -> None:
    s = aggregate_values([0.40, 0.45, 0.50])
    assert s.n == 3
    assert s.mean == pytest.approx(0.45)
    # sample std (ddof=1) of {0.40,0.45,0.50} == 0.05
    assert s.std == pytest.approx(0.05, abs=1e-4)
    assert s.minimum == 0.40
    assert s.maximum == 0.50
    assert s.assessable_spread is True


# --------------------------------------------------------------- aggregate_model


def test_aggregate_model_rolls_each_metric() -> None:
    runs = [_summary(factual=0.30, quality=0.40), _summary(factual=0.34, quality=0.50)]
    agg = aggregate_model("m", runs)
    assert agg.model == "m"
    assert agg.n_runs == 2
    assert agg.metrics["factual"].mean == pytest.approx(0.32)
    assert agg.metrics["quality"].mean == pytest.approx(0.45)
    assert agg.metrics["quality"].n == 2


def test_aggregate_model_skips_unjudged_quality() -> None:
    # One run judged, one not (quality None) -> quality stat over 1 value only.
    runs = [_summary(quality=0.40), _summary(quality=None)]
    agg = aggregate_model("m", runs)
    assert agg.metrics["quality"].n == 1
    assert agg.metrics["quality"].mean == pytest.approx(0.40)
    # other metrics still see both runs
    assert agg.metrics["factual"].n == 2


def test_aggregate_model_all_unjudged_quality_is_empty() -> None:
    agg = aggregate_model("m", [_summary(quality=None), _summary(quality=None)])
    assert agg.metrics["quality"].n == 0


# --------------------------------------------------------------- aggregate_runs


def test_aggregate_runs_groups_by_model_sorted() -> None:
    summaries = [
        _summary("zeta", factual=0.2),
        _summary("alpha", factual=0.3),
        _summary("zeta", factual=0.4),
    ]
    models = aggregate_runs(summaries)
    assert [m.model for m in models] == ["alpha", "zeta"]
    zeta = next(m for m in models if m.model == "zeta")
    assert zeta.n_runs == 2
    assert zeta.metrics["factual"].mean == pytest.approx(0.3)


# --------------------------------------------------------------- compare_metric


def test_compare_metric_unassessable_when_single_run_each() -> None:
    off = aggregate_values([0.26])
    on = aggregate_values([0.45])
    c = compare_metric("quality", off, on)
    assert c.delta == pytest.approx(0.19)
    assert c.clears_noise is None
    assert c.verdict == "need >=2 runs/group"


def test_compare_metric_clears_noise_when_delta_exceeds_band() -> None:
    off = aggregate_values([0.25, 0.26, 0.27])  # tiny spread
    on = aggregate_values([0.44, 0.45, 0.46])  # tiny spread, big shift
    c = compare_metric("quality", off, on)
    assert c.clears_noise is True
    assert c.verdict == "improves"
    expected_noise = math.hypot(off.std, on.std)
    assert c.noise == pytest.approx(round(expected_noise, 4))


def test_compare_metric_within_noise_when_overlapping() -> None:
    off = aggregate_values([0.20, 0.40, 0.60])  # big spread
    on = aggregate_values([0.25, 0.45, 0.65])  # small shift vs spread
    c = compare_metric("quality", off, on)
    assert c.clears_noise is False
    assert c.verdict == "within noise"


def test_compare_metric_regresses_label() -> None:
    off = aggregate_values([0.50, 0.51, 0.52])
    on = aggregate_values([0.20, 0.21, 0.22])
    c = compare_metric("factual", off, on)
    assert c.clears_noise is True
    assert c.delta < 0
    assert c.verdict == "regresses"


# --------------------------------------------------------------- significance (SEM/t)


def test_sem_shrinks_with_n() -> None:
    # Same spread, more runs -> smaller SEM.
    few = aggregate_values([0.2, 0.4])  # std ~0.1414, n2
    many = aggregate_values([0.2, 0.4, 0.2, 0.4])  # same-ish std, n4
    assert many.sem < few.sem


def test_significance_unassessable_single_run() -> None:
    c = compare_metric("quality", aggregate_values([0.26]), aggregate_values([0.45]))
    assert c.t_ratio is None
    assert c.significance == "need >=2 runs/group"


def test_significance_deterministic_when_zero_variance() -> None:
    # Temp-0 factual: identical every run, but a real reproducible delta.
    off = aggregate_values([0.30, 0.30, 0.30])
    on = aggregate_values([0.33, 0.33, 0.33])
    c = compare_metric("factual", off, on)
    assert c.sem_diff == 0.0
    assert c.t_ratio is None
    assert c.significance == "deterministic"


def test_significance_no_change_when_zero_variance_zero_delta() -> None:
    same = aggregate_values([0.30, 0.30, 0.30])
    c = compare_metric("factual", same, same)
    assert c.significance == "no change"


def test_significance_significant_when_t_large() -> None:
    off = aggregate_values([0.25, 0.26, 0.27])  # tiny SEM
    on = aggregate_values([0.50, 0.51, 0.52])  # tiny SEM, big gap
    c = compare_metric("quality", off, on)
    assert c.t_ratio is not None and abs(c.t_ratio) >= 2.0
    assert c.significance == "significant"


def test_significance_ns_when_noisy_and_small() -> None:
    # The real gemma-shaped case: modest delta swamped by on-group noise.
    off = aggregate_values([0.26, 0.32, 0.25])
    on = aggregate_values([0.43, 0.55, 0.27])
    c = compare_metric("quality", off, on)
    assert c.t_ratio is not None
    # delta ~0.14, SE_diff ~0.084 -> t ~1.6 -> suggestive, not significant
    assert c.significance in {"suggestive", "ns"}
    assert c.significance != "significant"


# --------------------------------------------------------------- compare_off_on


def test_compare_off_on_quality_is_last() -> None:
    off = aggregate_model("m", [_summary(quality=0.26), _summary(quality=0.27)])
    on = aggregate_model("m", [_summary(quality=0.45), _summary(quality=0.46)])
    comps = compare_off_on(off, on)
    assert comps[-1].metric == "quality"
    assert {c.metric for c in comps} >= {"factual", "coverage", "quality"}


# --------------------------------------------------------------- rendering


def test_render_aggregate_contains_model_and_metric() -> None:
    out = render_aggregate(aggregate_runs([_summary("gemma", quality=0.45)]))
    assert "gemma" in out
    assert "quality" in out
    assert "1 run" in out


def test_render_aggregate_empty() -> None:
    assert render_aggregate([]) == "(no runs)"


def test_render_comparison_contains_verdict_legend() -> None:
    off = aggregate_model("m", [_summary(quality=0.26), _summary(quality=0.27)])
    on = aggregate_model("m", [_summary(quality=0.45), _summary(quality=0.46)])
    out = render_comparison("m", compare_off_on(off, on))
    assert "OFF vs ON" in out
    assert "delta" in out
    assert "SE_diff" in out
    assert "significance" in out
