"""Light tests for the profiler producer's reachability gate (scripts/profile_model.py).

The pure core (data model, recommend mapping, render) is covered in
test_eval_profile.py; here we verify only the producer's cheapest-first gate:
the reachability dimension maps the provider's status correctly, which is what
short-circuits the run before the expensive dimensions.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "profile_model.py"


def _load_producer():
    spec = importlib.util.spec_from_file_location("profile_model", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pm = _load_producer()


def _model(reachable: bool, model_found: bool, gen: str = "hi") -> MagicMock:
    m = MagicMock()
    m.base_url = "http://localhost:11435"
    m.model = "test-model"
    m.check_status.return_value = (reachable, model_found)
    m.generate.return_value = gen
    return m


class TestReachabilityGate:
    def test_unreachable_fails(self) -> None:
        r = pm._dim_reachability(_model(False, False))
        assert r.status == "fail"
        assert "unreachable" in r.notes

    def test_model_not_loaded_fails(self) -> None:
        r = pm._dim_reachability(_model(True, False))
        assert r.status == "fail"
        assert "not loaded" in r.notes

    def test_empty_generation_fails(self) -> None:
        r = pm._dim_reachability(_model(True, True, gen="   "))
        assert r.status == "fail"
        assert "empty" in r.notes

    def test_healthy_passes(self) -> None:
        r = pm._dim_reachability(_model(True, True, gen="Hello there."))
        assert r.status == "pass"

    def test_generation_exception_fails(self) -> None:
        m = _model(True, True)
        m.generate.side_effect = RuntimeError("boom")
        r = pm._dim_reachability(m)
        assert r.status == "fail"
        assert "generation failed" in r.notes


def test_reachability_fail_recommendation_is_unusable() -> None:
    # Wiring check: a reachability-fail dimension drives an "unusable" config
    # recommendation and nothing downstream (the short-circuit contract).
    from datetime import datetime

    from chess_coach.eval.profile import CapabilityProfile, recommend

    profile = CapabilityProfile(
        model="m",
        captured_at=datetime(2026, 6, 23),
        dimensions=[pm._dim_reachability(_model(False, False))],
    )
    rec = recommend(profile)
    assert len(rec.suggestions) == 1
    assert rec.suggestions[0].value == "(unusable)"


class TestGuidanceCoverageGuard:
    """A mostly-failed guidance run must surface WHY, not a survivor win-rate."""

    def test_mostly_failed_run_reports_reason_not_winrate(self, monkeypatch) -> None:
        import random

        # 19/20 generations failed (dead tunnel); only 1 decisive comparison.
        skips = [{"id": f"s{i}", "stage": "gen", "error": "connection refused"} for i in range(19)]
        monkeypatch.setattr(pm, "run_move_feedback_pairwise", lambda *a, **k: (None, [], skips))
        dim = pm._dim_guidance(
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
            depth=8,
            multipv=3,
            guidance_max=3,
            temperature=0.0,
            judge_repeats=1,
            win_rate_min=0.6,
            rng=random.Random(0),
        )
        assert dim.status == "fail"
        assert "insufficient comparisons" in dim.notes
        assert "connection refused" in dim.notes  # the underlying reason bubbled up
        assert "on_win_rate" not in dim.metrics  # no confident verdict from a failed run

    def test_healthy_run_reports_winrate(self, monkeypatch) -> None:
        import random

        from chess_coach.eval import summarize_pairwise

        summary = summarize_pairwise(["on"] * 15 + ["off"] * 5, "off", "on")
        monkeypatch.setattr(pm, "run_move_feedback_pairwise", lambda *a, **k: (summary, [], []))
        dim = pm._dim_guidance(
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
            depth=8,
            multipv=3,
            guidance_max=3,
            temperature=0.0,
            judge_repeats=1,
            win_rate_min=0.6,
            rng=random.Random(0),
        )
        assert dim.status == "pass"
        assert dim.metrics["on_win_rate"] == 0.75


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
