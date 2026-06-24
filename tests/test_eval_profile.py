"""Tests for the model-capability profiler pure core (eval/profile.py)."""

from __future__ import annotations

from datetime import datetime

from chess_coach.eval.profile import (
    CapabilityProfile,
    DimensionResult,
    ProfileThresholds,
    recommend,
    render_profile,
    render_recommendation,
)

_TS = datetime(2026, 6, 23, 12, 0, 0)


def _profile(*dims: DimensionResult) -> CapabilityProfile:
    return CapabilityProfile(model="test-model", captured_at=_TS, dimensions=list(dims))


# --------------------------------------------------------------- data model


class TestDataModel:
    def test_dimension_round_trip(self) -> None:
        d = DimensionResult(
            name="factual",
            status="pass",
            metrics={"factual": 0.33, "hallucinations": 0.0},
            latency_s=7.2,
            samples=9,
            notes="ok",
        )
        assert DimensionResult.from_dict(d.to_dict()) == d

    def test_profile_round_trip(self) -> None:
        p = _profile(
            DimensionResult("reachability", "pass", samples=1),
            DimensionResult("latency", "info", latency_s=6.5, samples=5),
        )
        assert CapabilityProfile.from_dict(p.to_dict()) == p

    def test_dimension_lookup(self) -> None:
        p = _profile(DimensionResult("factual", "pass", {"factual": 0.5}))
        assert p.dimension("factual") is not None
        assert p.dimension("missing") is None

    def test_dimensions_are_a_list_extensible(self) -> None:
        # Appending a novel dimension needs no model change.
        p = _profile(DimensionResult("some_future_dim", "info", {"x": 1.0}))
        assert CapabilityProfile.from_dict(p.to_dict()).dimensions[0].name == "some_future_dim"


# --------------------------------------------------- recommend (mapping)


class TestRecommend:
    def test_low_factual_suggests_template_only(self) -> None:
        p = _profile(DimensionResult("factual", "fail", {"factual": 0.30, "hallucinations": 0.0}))
        rec = recommend(p, ProfileThresholds(factual_min=0.50))
        s = {x.key: x.value for x in rec.suggestions}
        assert s["coaching.template_only"] == "true"

    def test_hallucinations_suggest_template_only_even_if_score_ok(self) -> None:
        p = _profile(DimensionResult("factual", "pass", {"factual": 0.80, "hallucinations": 2.0}))
        rec = recommend(p)
        s = {x.key: x.value for x in rec.suggestions}
        assert s["coaching.template_only"] == "true"

    def test_illegal_moves_suggest_template_only(self) -> None:
        p = _profile(DimensionResult("factual", "pass", {"factual": 0.90, "illegal_moves": 1.0}))
        rec = recommend(p)
        s = {x.key: x.value for x in rec.suggestions}
        assert s["coaching.template_only"] == "true"

    def test_grounded_suggests_trust_llm(self) -> None:
        p = _profile(DimensionResult("factual", "pass", {"factual": 0.70, "hallucinations": 0.0, "illegal_moves": 0.0}))
        rec = recommend(p)
        s = {x.key: x.value for x in rec.suggestions}
        assert s["coaching.template_only"] == "false"

    def test_guidance_on_when_win_rate_high(self) -> None:
        p = _profile(DimensionResult("guidance", "pass", {"on_win_rate": 0.75}))
        rec = recommend(p, ProfileThresholds(guidance_win_rate_min=0.60))
        s = {x.key: x.value for x in rec.suggestions}
        assert s["coaching.guidance"] == "on"

    def test_guidance_off_when_win_rate_low(self) -> None:
        p = _profile(DimensionResult("guidance", "info", {"on_win_rate": 0.50}))
        rec = recommend(p, ProfileThresholds(guidance_win_rate_min=0.60))
        s = {x.key: x.value for x in rec.suggestions}
        assert s["coaching.guidance"] == "off"

    def test_latency_never_yields_a_suggestion(self) -> None:
        p = _profile(DimensionResult("latency", "info", latency_s=40.0, samples=5))
        rec = recommend(p)
        assert rec.suggestions == []

    def test_reachability_fail_short_circuits(self) -> None:
        # Even if other (stale) dimensions are present, a reachability fail
        # yields only the "unusable" suggestion.
        p = _profile(
            DimensionResult("reachability", "fail", notes="endpoint unreachable"),
            DimensionResult("factual", "pass", {"factual": 0.9}),
        )
        rec = recommend(p)
        assert len(rec.suggestions) == 1
        assert rec.suggestions[0].key == "model"
        assert "unreachable" in rec.suggestions[0].reason

    def test_reasons_cite_numbers(self) -> None:
        p = _profile(
            DimensionResult("factual", "fail", {"factual": 0.30}),
            DimensionResult("guidance", "pass", {"on_win_rate": 0.75}),
        )
        rec = recommend(p)
        joined = " ".join(s.reason for s in rec.suggestions)
        assert "0.30" in joined
        assert "75%" in joined


# --------------------------------------------------------------- rendering


class TestRender:
    def test_render_profile_shows_each_dimension(self) -> None:
        p = _profile(
            DimensionResult("factual", "pass", {"factual": 0.33}, samples=9),
            DimensionResult("latency", "info", latency_s=7.2, samples=5),
        )
        out = render_profile(p)
        assert "factual" in out
        assert "latency" in out
        assert "test-model" in out

    def test_render_recommendation_is_pasteable_with_reasons(self) -> None:
        p = _profile(DimensionResult("guidance", "pass", {"on_win_rate": 0.75}))
        out = render_recommendation(recommend(p))
        assert "coaching.guidance: on" in out
        assert "Why:" in out

    def test_render_recommendation_empty(self) -> None:
        out = render_recommendation(recommend(_profile()))
        assert "No config recommendations" in out
