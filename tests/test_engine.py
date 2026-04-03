"""Tests for chess_coach.engine — XboardEngine with mock subprocess."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

from chess_coach.engine import AnalysisLine, AnalysisResult, XboardEngine

# ---------------------------------------------------------------------------
# AnalysisLine / AnalysisResult dataclass tests
# ---------------------------------------------------------------------------


class TestAnalysisLine:
    def test_score_str_positive(self):
        line = AnalysisLine(depth=12, score_cp=35, nodes=1000, time_ms=500, pv=["e2e4"])
        assert line.score_str == "+0.35"

    def test_score_str_negative(self):
        line = AnalysisLine(depth=12, score_cp=-120, nodes=1000, time_ms=500, pv=["e7e5"])
        assert line.score_str == "-1.20"

    def test_score_str_zero(self):
        line = AnalysisLine(depth=10, score_cp=0, nodes=500, time_ms=200, pv=["d2d4"])
        assert line.score_str == "+0.00"

    def test_score_str_mate_positive(self):
        line = AnalysisLine(depth=15, score_cp=20000, nodes=100, time_ms=50, pv=["h5f7"])
        assert line.score_str.startswith("#+")

    def test_score_str_mate_negative(self):
        line = AnalysisLine(depth=15, score_cp=-20000, nodes=100, time_ms=50, pv=["a1a2"])
        assert line.score_str.startswith("#-")


class TestAnalysisResult:
    def test_top_line_empty(self):
        result = AnalysisResult(fen="startpos")
        assert result.top_line is None

    def test_top_line_returns_first(self):
        line = AnalysisLine(depth=10, score_cp=50, nodes=100, time_ms=100, pv=["e2e4"])
        result = AnalysisResult(fen="startpos", lines=[line])
        assert result.top_line is line


# ---------------------------------------------------------------------------
# Helpers: fake subprocess that simulates an Xboard engine
# ---------------------------------------------------------------------------


class FakeStdin:
    """Captures commands sent to the engine."""

    def __init__(self) -> None:
        self.commands: list[str] = []

    def write(self, data: str) -> None:
        self.commands.append(data.rstrip("\n"))

    def flush(self) -> None:
        pass


class FakeStdout:
    """Feeds pre-scripted lines back to the engine reader."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)
        self._index = 0
        self._lock = threading.Lock()

    def readline(self) -> str:
        with self._lock:
            if self._index < len(self._lines):
                line = self._lines[self._index]
                self._index += 1
                return line + "\n"
        # Block briefly then return empty to simulate no more output
        time.sleep(0.05)
        return ""


def _make_fake_proc(
    stdout_lines: list[str],
    poll_return: int | None = None,
) -> tuple[MagicMock, FakeStdin, FakeStdout]:
    """Create a mock Popen with fake stdin/stdout."""
    fake_stdin = FakeStdin()
    fake_stdout = FakeStdout(stdout_lines)
    proc = MagicMock()
    proc.stdin = fake_stdin
    proc.stdout = fake_stdout
    proc.poll.return_value = poll_return  # None = still running
    proc.wait.return_value = 0
    return proc, fake_stdin, fake_stdout


def _setup_engine(stdout_lines: list[str], poll_return: int | None = None) -> tuple[XboardEngine, FakeStdin]:
    """Create an XboardEngine and inject a fake process (bypasses real start)."""
    proc, fake_stdin, fake_stdout = _make_fake_proc(stdout_lines, poll_return)
    engine = XboardEngine("/fake/engine")
    engine._proc = proc
    engine._stdin = fake_stdin
    engine._stdout = fake_stdout
    return engine, fake_stdin


# ---------------------------------------------------------------------------
# _parse_thinking_line tests (unit-level, no subprocess needed)
# ---------------------------------------------------------------------------


class TestParseThinkingLine:
    """Test the Xboard thinking output parser directly."""

    def setup_method(self):
        self.engine = XboardEngine("/fake/engine")

    def test_valid_line(self):
        line = "12 35 150 50000 e2e4 e7e5 g1f3"
        result = self.engine._parse_thinking_line(line)
        assert result is not None
        assert result.depth == 12
        assert result.score_cp == 35
        assert result.time_ms == 1500  # 150 centiseconds * 10
        assert result.nodes == 50000
        assert result.pv == ["e2e4", "e7e5", "g1f3"]

    def test_negative_score(self):
        line = "8 -120 50 10000 d7d5 e2e4"
        result = self.engine._parse_thinking_line(line)
        assert result is not None
        assert result.score_cp == -120

    def test_single_move_pv(self):
        line = "5 10 20 3000 e2e4"
        result = self.engine._parse_thinking_line(line)
        assert result is not None
        assert result.pv == ["e2e4"]

    def test_too_few_parts(self):
        assert self.engine._parse_thinking_line("12 35 150") is None
        assert self.engine._parse_thinking_line("12 35") is None
        assert self.engine._parse_thinking_line("") is None

    def test_non_numeric_depth(self):
        line = "abc 35 150 50000 e2e4"
        assert self.engine._parse_thinking_line(line) is None

    def test_non_numeric_score(self):
        line = "12 abc 150 50000 e2e4"
        assert self.engine._parse_thinking_line(line) is None

    def test_feature_line_ignored(self):
        """Feature lines from protover should not parse as thinking output."""
        assert self.engine._parse_thinking_line("feature done=1") is None

    def test_whitespace_handling(self):
        line = "  12  35  150  50000  e2e4  "
        result = self.engine._parse_thinking_line(line)
        assert result is not None
        assert result.depth == 12


# ---------------------------------------------------------------------------
# Start / stop lifecycle
# ---------------------------------------------------------------------------


class TestXboardEngineLifecycle:
    @patch("chess_coach.engine.subprocess.Popen")
    def test_start_sends_xboard_protocol(self, mock_popen_cls):
        """start() should send xboard + protover 2 + post."""
        fake_stdin = FakeStdin()
        fake_stdout = FakeStdout(["feature done=1"])
        proc = MagicMock()
        proc.stdin = fake_stdin
        proc.stdout = fake_stdout
        proc.poll.return_value = None
        mock_popen_cls.return_value = proc

        engine = XboardEngine("/fake/engine")
        engine.start()

        assert "xboard" in fake_stdin.commands
        assert "protover 2" in fake_stdin.commands
        assert "post" in fake_stdin.commands

    @patch("chess_coach.engine.subprocess.Popen")
    def test_stop_sends_quit(self, mock_popen_cls):
        """stop() should send quit and wait for process exit."""
        fake_stdin = FakeStdin()
        fake_stdout = FakeStdout(["feature done=1"])
        proc = MagicMock()
        proc.stdin = fake_stdin
        proc.stdout = fake_stdout
        proc.poll.return_value = None
        mock_popen_cls.return_value = proc

        engine = XboardEngine("/fake/engine")
        engine.start()
        engine.stop()

        assert "quit" in fake_stdin.commands
        proc.wait.assert_called_once()

    def test_is_ready_true_when_running(self):
        engine, _ = _setup_engine([], poll_return=None)
        assert engine.is_ready() is True

    def test_is_ready_false_before_start(self):
        engine = XboardEngine("/fake/engine")
        assert engine.is_ready() is False

    def test_is_ready_false_after_exit(self):
        engine, _ = _setup_engine([], poll_return=0)
        assert engine.is_ready() is False


# ---------------------------------------------------------------------------
# Analyze
# ---------------------------------------------------------------------------


class TestXboardEngineAnalyze:
    def test_analyze_collects_lines(self):
        """analyze() should parse thinking output and return best move."""
        fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        stdout_lines = [
            "8 25 50 10000 e2e4 e7e5",
            "10 30 100 30000 e2e4 e7e5 g1f3",
            "12 35 200 80000 d2d4 d7d5 c2c4",
        ]
        engine, fake_stdin = _setup_engine(stdout_lines)
        result = engine.analyze(fen, depth=12, time_limit=5.0)

        assert result.fen == fen
        assert len(result.lines) > 0
        assert result.best_move == "d2d4"  # deepest line's first PV move
        # Verify analyze mode commands were sent
        assert "force" in fake_stdin.commands
        assert f"setboard {fen}" in fake_stdin.commands
        assert "analyze" in fake_stdin.commands
        assert "exit" in fake_stdin.commands

    def test_analyze_stops_at_target_depth(self):
        """analyze() should stop once target depth is reached."""
        fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
        stdout_lines = [
            "5 -10 20 5000 e7e5",
            "6 -15 30 8000 e7e5 g1f3",
        ]
        engine, _ = _setup_engine(stdout_lines)
        result = engine.analyze(fen, depth=6, time_limit=5.0)

        assert result.best_move == "e7e5"
        depths = [line.depth for line in result.lines]
        assert 6 in depths

    def test_analyze_empty_output(self):
        """analyze() with no thinking output returns empty result."""
        fen = "8/8/8/8/8/8/8/4K3 w - - 0 1"
        engine, _ = _setup_engine([])  # No thinking output
        result = engine.analyze(fen, depth=10, time_limit=1.0)

        assert result.fen == fen
        assert result.lines == []
        assert result.best_move == ""

    def test_analyze_deduplicates_by_depth(self):
        """When multiple lines at the same depth arrive, keep only the latest."""
        fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        stdout_lines = [
            "8 25 50 10000 e2e4 e7e5",
            "8 30 60 12000 d2d4 d7d5",  # same depth, updated score
            "10 35 100 30000 d2d4 d7d5 c2c4",
        ]
        engine, _ = _setup_engine(stdout_lines)
        result = engine.analyze(fen, depth=10, time_limit=5.0)

        depth_8_lines = [ln for ln in result.lines if ln.depth == 8]
        assert len(depth_8_lines) == 1
        assert depth_8_lines[0].score_cp == 30  # the updated one


# ---------------------------------------------------------------------------
# Timeout handling
# ---------------------------------------------------------------------------


class TestXboardEngineTimeout:
    def test_analyze_respects_time_limit(self):
        """analyze() should return within time_limit even without target depth."""
        fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        # Only shallow output — never reaches depth 20
        stdout_lines = ["3 10 5 1000 e2e4"]
        engine, _ = _setup_engine(stdout_lines)

        start_time = time.monotonic()
        result = engine.analyze(fen, depth=20, time_limit=1.5)
        elapsed = time.monotonic() - start_time

        # Should return within a reasonable margin of the time limit
        assert elapsed < 4.0
        # Should still have the partial results
        assert len(result.lines) > 0
        assert result.lines[0].depth == 3

    def test_read_line_returns_none_on_timeout(self):
        """_read_line should return None when stdout has no data."""
        engine = XboardEngine("/fake/engine")
        engine._stdout = FakeStdout([])  # No lines available

        start = time.monotonic()
        engine._read_line(timeout=0.2)
        elapsed = time.monotonic() - start

        # Should return relatively quickly (within timeout + margin)
        assert elapsed < 1.0
