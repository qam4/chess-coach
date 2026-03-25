"""Tests for mobile/Android support: NullProvider, template_only mode."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from chess_coach.llm import create_provider
from chess_coach.llm.null import NullProvider

# ---------------------------------------------------------------------------
# NullProvider tests (task 2.4)
# ---------------------------------------------------------------------------


class TestNullProvider:
    def test_generate_returns_empty(self) -> None:
        p = NullProvider()
        assert p.generate("anything") == ""

    def test_generate_with_params_returns_empty(self) -> None:
        p = NullProvider()
        assert p.generate("prompt", max_tokens=1024, temperature=0.5) == ""

    def test_is_available_returns_false(self) -> None:
        p = NullProvider()
        assert p.is_available() is False

    def test_smoke_test_returns_ok(self) -> None:
        p = NullProvider()
        ok, msg = p.smoke_test()
        assert ok is True
        assert "template" in msg.lower() or "disabled" in msg.lower()

    def test_model_is_none(self) -> None:
        p = NullProvider()
        assert p.model == "none"

    def test_factory_creates_null_provider(self) -> None:
        p = create_provider(provider="none")
        assert isinstance(p, NullProvider)

    def test_factory_none_ignores_model_param(self) -> None:
        p = create_provider(provider="none", model="should-be-ignored")
        assert isinstance(p, NullProvider)
        assert p.model == "none"


# ---------------------------------------------------------------------------
# Coach template_only tests (task 2.5)
# ---------------------------------------------------------------------------


class TestTemplateOnlyCoach:
    """Test that Coach with template_only=True never calls LLM."""

    def test_evaluate_move_skips_llm_for_bad_move(self) -> None:
        """When template_only=True, evaluate_move uses template feedback, not LLM."""
        from chess_coach.coach import Coach
        from chess_coach.models import ComparisonReport, PVLine

        mock_engine = MagicMock()
        mock_engine.coaching_available = True
        mock_engine.__class__ = type("CoachingEngine", (), {})

        mock_llm = MagicMock(spec=NullProvider)

        # Patch isinstance check for CoachingEngine
        with patch("chess_coach.coach.isinstance", side_effect=lambda obj, cls: True):
            with patch("chess_coach.coach.CoachingEngine"):
                coach = Coach(
                    engine=mock_engine,
                    llm=mock_llm,
                    template_only=True,
                )
                # Force coaching available
                coach._coaching_available = True

                # Mock comparison report for a bad move
                report = ComparisonReport(
                    fen="r1bqkbnr/pppppppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 8",
                    user_move="f2f3",
                    user_eval_cp=-120,
                    best_move="d2d4",
                    best_eval_cp=0,
                    eval_drop_cp=120,
                    classification="mistake",
                    nag="?",
                    best_move_idea="Controls the center",
                    refutation_line=None,
                    missed_tactics=[],
                    top_lines=[
                        PVLine(depth=8, eval_cp=0, moves=["d2d4"], theme="open game")
                    ],
                    critical_moment=False,
                    critical_reason=None,
                )
                mock_engine.get_comparison_report.return_value = report

                result = coach.evaluate_move(
                    "r1bqkbnr/pppppppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 8",
                    "f2f3",
                )

                # LLM should NOT have been called
                mock_llm.generate.assert_not_called()
                # But we should still get a classification
                assert result.classification == "mistake"
                assert result.eval_drop_cp == 120


# ---------------------------------------------------------------------------
# Mobile entry config loading tests (task 3.4)
# ---------------------------------------------------------------------------


class TestMobileEntry:
    def test_load_mobile_config_resolves_placeholders(self, tmp_path: Path) -> None:
        from chess_coach.mobile_entry import load_mobile_config

        config = tmp_path / "config.yaml"
        config.write_text(
            "engine:\n"
            '  path: "{APP_DATA}/engine/blunder"\n'
            '  book: "{APP_DATA}/books/gm.bin"\n'
            "llm:\n"
            '  provider: "none"\n'
        )
        cfg = load_mobile_config(str(config), app_data_dir="/data/app")
        assert cfg["engine"]["path"] == "/data/app/engine/blunder"
        assert cfg["engine"]["book"] == "/data/app/books/gm.bin"
        assert cfg["llm"]["provider"] == "none"

    def test_load_mobile_config_defaults_to_config_dir(self, tmp_path: Path) -> None:
        from chess_coach.mobile_entry import load_mobile_config

        config = tmp_path / "config.yaml"
        config.write_text(
            "engine:\n"
            '  path: "{APP_DATA}/blunder"\n'
        )
        cfg = load_mobile_config(str(config))
        # Should resolve to the directory containing config.yaml
        assert cfg["engine"]["path"] == f"{tmp_path}/blunder"

    def test_resolve_placeholders_nested(self) -> None:
        from chess_coach.mobile_entry import _resolve_placeholders

        data = {
            "a": "{X}/foo",
            "b": ["{X}/bar", "plain"],
            "c": {"d": "{X}/baz", "e": 42},
        }
        result = _resolve_placeholders(data, {"X": "/root"})
        assert result["a"] == "/root/foo"
        assert result["b"] == ["/root/bar", "plain"]
        assert result["c"]["d"] == "/root/baz"
        assert result["c"]["e"] == 42
