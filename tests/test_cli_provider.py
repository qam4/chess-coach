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


def test_decodes_utf8_output_regardless_of_platform_default() -> None:
    # A "thinking" model's output routinely contains non-Latin-1 bytes
    # (em dashes, sqrt, accents). The child writes raw UTF-8 bytes; the
    # provider must decode them as UTF-8, not the Windows cp1252 default.
    cmd = [sys.executable, "-c", r"import sys; sys.stdout.buffer.write('caf\u00e9 \u2014 \u221a'.encode('utf-8'))"]
    p = CliProvider(model="stub", command=cmd)
    assert p.generate("x") == "café — √"


def test_invalid_bytes_do_not_crash_the_judge() -> None:
    # 0x8f is the exact byte that crashed the qwen judge run under cp1252.
    # With errors="replace" the provider must return a string (one stray
    # byte never aborts a run), not raise UnicodeDecodeError.
    cmd = [sys.executable, "-c", r"import sys; sys.stdout.buffer.write(b'\x8f ok')"]
    p = CliProvider(model="stub", command=cmd)
    out = p.generate("x")
    assert "ok" in out
