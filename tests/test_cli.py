"""Integration tests for chess_coach.cli using click.testing.CliRunner."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from chess_coach.cli import cli, load_config
from chess_coach.coach import CoachingResponse

STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

TEST_CONFIG = textwrap.dedent("""\
    engine:
      path: "/tmp/fake-engine"
      protocol: "xboard"
      args: []
      depth: 12
    llm:
      provider: "ollama"
      model: "test-model"
      base_url: "http://localhost:11434"
      max_tokens: 256
      temperature: 0.5
    coaching:
      top_moves: 3
      level: "intermediate"
""")


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def config_file(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(TEST_CONFIG)
    return cfg


class TestHelpOutput:
    """--help flags print usage and exit 0."""

    def test_cli_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Chess Coach" in result.output

    def test_explain_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["explain", "--help"])
        assert result.exit_code == 0
        assert "FEN" in result.output

    def test_check_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["check", "--help"])
        assert result.exit_code == 0
        assert "engine" in result.output.lower() or "LLM" in result.output


class TestConfigLoading:
    """Config loading and error handling."""

    def test_load_config_valid(self, config_file: Path) -> None:
        cfg = load_config(config_file)
        assert cfg["engine"]["depth"] == 12
        assert cfg["llm"]["provider"] == "ollama"

    def test_config_not_found(self, runner: CliRunner, tmp_path: Path) -> None:
        missing = tmp_path / "nope.yaml"
        result = runner.invoke(cli, ["--config", str(missing), "check"])
        assert result.exit_code != 0
        assert "Config not found" in result.output


class TestCheckCommand:
    """check command with mocked engine/LLM."""

    @patch("chess_coach.cli.create_provider")
    def test_check_all_ok(
        self,
        mock_create: MagicMock,
        runner: CliRunner,
        config_file: Path,
    ) -> None:
        mock_llm = MagicMock()
        mock_llm.is_available.return_value = True
        mock_llm.smoke_test.return_value = (True, "Hello!")
        mock_create.return_value = mock_llm

        # Create a fake engine binary so the path check passes
        engine_path = config_file.parent / "fake-engine"
        engine_path.touch()

        # Rewrite config to point at the fake engine (forward slashes for YAML compat)
        cfg_text = TEST_CONFIG.replace("/tmp/fake-engine", str(engine_path).replace("\\", "/"))
        config_file.write_text(cfg_text)

        result = runner.invoke(cli, ["--config", str(config_file), "check"])
        assert result.exit_code == 0
        assert "Binary found" in result.output
        assert "Model available" in result.output

    @patch("chess_coach.cli.create_provider")
    def test_check_engine_missing(
        self,
        mock_create: MagicMock,
        runner: CliRunner,
        config_file: Path,
    ) -> None:
        mock_llm = MagicMock()
        mock_llm.is_available.return_value = True
        mock_llm.smoke_test.return_value = (True, "Hello!")
        mock_create.return_value = mock_llm

        result = runner.invoke(cli, ["--config", str(config_file), "check"])
        assert result.exit_code == 0
        assert "not found" in result.output

    @patch("chess_coach.cli.create_provider")
    def test_check_llm_unreachable(
        self,
        mock_create: MagicMock,
        runner: CliRunner,
        config_file: Path,
    ) -> None:
        mock_llm = MagicMock()
        mock_llm.is_available.return_value = False
        mock_create.return_value = mock_llm

        result = runner.invoke(cli, ["--config", str(config_file), "check"])
        assert result.exit_code == 0
        assert "Not reachable" in result.output


class TestExplainCommand:
    """explain command with mocked Coach."""

    @patch("chess_coach.cli.Coach")
    @patch("chess_coach.cli.create_provider")
    @patch("chess_coach.cli.XboardEngine")
    def test_explain_prints_coaching(
        self,
        mock_engine_cls: MagicMock,
        mock_create: MagicMock,
        mock_coach_cls: MagicMock,
        runner: CliRunner,
        config_file: Path,
    ) -> None:
        mock_llm = MagicMock()
        mock_llm.is_available.return_value = True
        mock_llm.smoke_test.return_value = (True, "Hi")
        mock_create.return_value = mock_llm

        mock_coach = MagicMock()
        mock_coach.explain.return_value = CoachingResponse(
            fen=STARTING_FEN,
            analysis_text="Material: equal",
            coaching_text="Develop your pieces and control the center.",
            best_move="e4",
            score="+0.35",
        )
        mock_coach_cls.return_value = mock_coach

        result = runner.invoke(
            cli,
            ["--config", str(config_file), "explain", STARTING_FEN],
        )
        assert result.exit_code == 0
        assert "Develop your pieces" in result.output
        assert "Coach says" in result.output
        assert "e4" in result.output

    @patch("chess_coach.cli.Coach")
    @patch("chess_coach.cli.create_provider")
    @patch("chess_coach.cli.XboardEngine")
    def test_explain_with_depth_and_level(
        self,
        mock_engine_cls: MagicMock,
        mock_create: MagicMock,
        mock_coach_cls: MagicMock,
        runner: CliRunner,
        config_file: Path,
    ) -> None:
        mock_llm = MagicMock()
        mock_llm.is_available.return_value = True
        mock_llm.smoke_test.return_value = (True, "Hi")
        mock_create.return_value = mock_llm

        mock_coach = MagicMock()
        mock_coach.explain.return_value = CoachingResponse(
            fen=STARTING_FEN,
            analysis_text="Material: equal",
            coaching_text="Advanced analysis here.",
            best_move="e4",
            score="+0.20",
        )
        mock_coach_cls.return_value = mock_coach

        result = runner.invoke(
            cli,
            [
                "--config",
                str(config_file),
                "explain",
                STARTING_FEN,
                "--depth",
                "25",
                "--level",
                "advanced",
            ],
        )
        assert result.exit_code == 0

        # Verify Coach was constructed with overridden depth and level
        call_kwargs = mock_coach_cls.call_args[1]
        assert call_kwargs["depth"] == 25
        assert call_kwargs["level"] == "advanced"

    @patch("chess_coach.cli.create_provider")
    @patch("chess_coach.cli.XboardEngine")
    def test_explain_llm_unavailable(
        self,
        mock_engine_cls: MagicMock,
        mock_create: MagicMock,
        runner: CliRunner,
        config_file: Path,
    ) -> None:
        mock_llm = MagicMock()
        mock_llm.is_available.return_value = False
        mock_create.return_value = mock_llm

        result = runner.invoke(
            cli,
            ["--config", str(config_file), "explain", STARTING_FEN],
        )
        assert result.exit_code != 0
        assert "LLM not available" in result.output
