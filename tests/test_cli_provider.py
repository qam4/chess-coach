"""Tests for chess_coach.llm.cli_provider — generic subprocess backend.

Uses the current Python interpreter as a stand-in CLI so the tests are
cross-platform and need no external tool installed.
"""

from __future__ import annotations

import sys

import pytest

from chess_coach.llm import CliProvider, create_provider


def _echo_upper_cmd() -> list[str]:
    # Reads stdin, writes it uppercased to stdout.
    return [sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read().upper())"]


def _arg_cmd() -> list[str]:
    # Prints its first argument (the substituted {prompt}).
    return [sys.executable, "-c", "import sys; sys.stdout.write(sys.argv[1])", "{prompt}"]


def test_generate_via_stdin() -> None:
    p = CliProvider(model="stub", command=_echo_upper_cmd())
    assert p.generate("hello world") == "HELLO WORLD"


def test_generate_via_prompt_placeholder() -> None:
    p = CliProvider(model="stub", command=_arg_cmd())
    # The prompt (with a space) is substituted into a single argv token.
    assert p.generate("find the key idea") == "find the key idea"


def test_nonzero_exit_raises() -> None:
    p = CliProvider(model="stub", command=[sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"])
    with pytest.raises(RuntimeError, match="exit 3"):
        p.generate("x")


def test_timeout_raises() -> None:
    import subprocess

    p = CliProvider(model="stub", command=[sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.5)
    with pytest.raises(subprocess.TimeoutExpired):
        p.generate("x")


def test_is_available_true_for_real_executable() -> None:
    assert CliProvider(model="stub", command=[sys.executable, "-c", "pass"]).is_available() is True


def test_is_available_false_for_missing_executable() -> None:
    assert CliProvider(model="stub", command=["definitely-not-a-real-command-xyz"]).is_available() is False


def test_empty_command_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty 'command'"):
        CliProvider(model="stub", command=[])


def test_factory_creates_cli_provider() -> None:
    p = create_provider("cli", model="kiro-cli", command=[sys.executable, "-c", "pass"])
    assert isinstance(p, CliProvider)
    assert p.model == "kiro-cli"
