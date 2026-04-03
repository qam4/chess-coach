"""Tests for chess_coach.engine — UciEngine with mock subprocess."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

from chess_coach.engine import UciEngine

# ---------------------------------------------------------------------------
# Helpers: fake subprocess (same pattern as test_engine.py)
# ---------------------------------------------------------------------------


class FakeStdin:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def write(self, data: str) -> None:
        self.commands.append(data.rstrip("\n"))

    def flush(self) -> None:
        pass


class FakeStdout:
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
        time.sleep(0.05)
        return ""


def _make_fake_proc(
    stdout_lines: list[str],
    poll_return: int | None = None,
) -> tuple[MagicMock, FakeStdin, FakeStdout]:
    fake_stdin = FakeStdin()
    fake_stdout = FakeStdout(stdout_lines)
    proc = MagicMock()
    proc.stdin = fake_stdin
    proc.stdout = fake_stdout
    proc.poll.return_value = poll_return
    proc.wait.return_value = 0
    return proc, fake_stdin, fake_stdout


def _setup_uci(stdout_lines: list[str], poll_return: int | None = None) -> tuple[UciEngine, FakeStdin]:
    """Create a UciEngine and inject a fake process (bypasses real start)."""
    proc, fake_stdin, fake_stdout = _make_fake_proc(stdout_lines, poll_return)
    engine = UciEngine("/fake/engine")
    engine._proc = proc
    engine._stdin = fake_stdin
    engine._stdout = fake_stdout
    return engine, fake_stdin


# ---------------------------------------------------------------------------
# UCI info line parser
# ---------------------------------------------------------------------------


class TestParseInfoLine:
    def test_basic_info_line(self):
        line = "info depth 8 score cp 77 nodes 238953 nps 1993933 time 110 pv e2e3 b8c6 b1c3"
        result = UciEngine._parse_info_line(line)
        assert result is not None
        assert result.depth == 8
        assert result.score_cp == 77
        assert result.nodes == 238953
        assert result.time_ms == 110
        assert result.pv == ["e2e3", "b8c6", "b1c3"]

    def test_negative_score(self):
        line = "info depth 5 score cp -42 nodes 1000 time 10 pv e7e5 d2d4"
        result = UciEngine._parse_info_line(line)
        assert result is not None
        assert result.score_cp == -42

    def test_mate_score_positive(self):
        line = "info depth 12 score mate 3 nodes 5000 time 50 pv h5f7 e8d8 f7g8"
        result = UciEngine._parse_info_line(line)
        assert result is not None
        # mate 3 → encoded as (20001 - 3*2) * 1 = 19995
        assert result.score_cp == 19995

    def test_mate_score_negative(self):
        line = "info depth 10 score mate -2 nodes 3000 time 30 pv a1a2 h8h1"
        result = UciEngine._parse_info_line(line)
        assert result is not None
        # mate -2 → encoded as -1 * (20001 - 2*2) = -19997
        assert result.score_cp == -19997

    def test_no_pv_returns_none(self):
        line = "info depth 5 score cp 10 nodes 100 time 5"
        result = UciEngine._parse_info_line(line)
        assert result is None

    def test_no_depth_returns_none(self):
        line = "info score cp 10 pv e2e4"
        result = UciEngine._parse_info_line(line)
        assert result is None

    def test_single_move_pv(self):
        line = "info depth 1 score cp 50 nodes 20 time 0 pv e2e4"
        result = UciEngine._parse_info_line(line)
        assert result is not None
        assert result.pv == ["e2e4"]

    def test_missing_optional_fields(self):
        """nodes and time are optional — should default to 0."""
        line = "info depth 3 score cp 15 pv d2d4 d7d5"
        result = UciEngine._parse_info_line(line)
        assert result is not None
        assert result.nodes == 0
        assert result.time_ms == 0


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestUciEngineLifecycle:
    @patch("chess_coach.engine.subprocess.Popen")
    def test_start_sends_uci_protocol(self, mock_popen_cls):
        fake_stdin = FakeStdin()
        fake_stdout = FakeStdout(
            [
                "id name blunder",
                "uciok",
                "readyok",
            ]
        )
        proc = MagicMock()
        proc.stdin = fake_stdin
        proc.stdout = fake_stdout
        proc.poll.return_value = None
        mock_popen_cls.return_value = proc

        engine = UciEngine("/fake/engine", args=["--uci"])
        engine.start()

        assert "uci" in fake_stdin.commands
        assert "isready" in fake_stdin.commands

    @patch("chess_coach.engine.subprocess.Popen")
    def test_stop_sends_quit(self, mock_popen_cls):
        fake_stdin = FakeStdin()
        fake_stdout = FakeStdout(["uciok", "readyok"])
        proc = MagicMock()
        proc.stdin = fake_stdin
        proc.stdout = fake_stdout
        proc.poll.return_value = None
        mock_popen_cls.return_value = proc

        engine = UciEngine("/fake/engine")
        engine.start()
        engine.stop()

        assert "quit" in fake_stdin.commands
        proc.wait.assert_called_once()

    def test_is_ready_true(self):
        engine, _ = _setup_uci([], poll_return=None)
        assert engine.is_ready() is True

    def test_is_ready_false_before_start(self):
        engine = UciEngine("/fake/engine")
        assert engine.is_ready() is False

    def test_is_ready_false_after_exit(self):
        engine, _ = _setup_uci([], poll_return=0)
        assert engine.is_ready() is False


# ---------------------------------------------------------------------------
# Analyze
# ---------------------------------------------------------------------------


class TestUciEngineAnalyze:
    def test_analyze_collects_lines(self):
        fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        stdout_lines = [
            "readyok",
            "info depth 5 score cp 30 nodes 5000 time 10 pv e2e4 e7e5",
            "info depth 8 score cp 77 nodes 238953 time 110 pv e2e3 b8c6",
            "bestmove e2e3 ponder b8c6",
        ]
        engine, fake_stdin = _setup_uci(stdout_lines)
        result = engine.analyze(fen, depth=8, time_limit=5.0)

        assert result.fen == fen
        assert result.best_move == "e2e3"
        assert len(result.lines) > 0
        assert f"position fen {fen}" in fake_stdin.commands

    def test_analyze_bestmove_from_response(self):
        fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
        stdout_lines = [
            "readyok",
            "info depth 6 score cp -3 nodes 10000 time 20 pv b8c6 b1c3",
            "bestmove b8c6 ponder b1c3",
        ]
        engine, _ = _setup_uci(stdout_lines)
        result = engine.analyze(fen, depth=6, time_limit=5.0)

        assert result.best_move == "b8c6"

    def test_analyze_empty_output(self):
        fen = "8/8/8/8/8/8/8/4K3 w - - 0 1"
        engine, _ = _setup_uci(["readyok"])
        result = engine.analyze(fen, depth=10, time_limit=1.0)

        assert result.lines == []
        assert result.best_move == ""

    def test_analyze_deduplicates_by_depth(self):
        fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        stdout_lines = [
            "readyok",
            "info depth 5 score cp 20 nodes 1000 time 5 pv e2e4",
            "info depth 5 score cp 30 nodes 2000 time 8 pv d2d4",
            "info depth 8 score cp 77 nodes 50000 time 100 pv e2e3 b8c6",
            "bestmove e2e3",
        ]
        engine, _ = _setup_uci(stdout_lines)
        result = engine.analyze(fen, depth=8, time_limit=5.0)

        depth_5 = [ln for ln in result.lines if ln.depth == 5]
        assert len(depth_5) == 1
        assert depth_5[0].score_cp == 30


# ---------------------------------------------------------------------------
# Play
# ---------------------------------------------------------------------------


class TestUciEnginePlay:
    def test_play_returns_bestmove(self):
        fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
        stdout_lines = [
            "readyok",
            "info depth 5 score cp -3 nodes 5000 time 10 pv b8c6",
            "bestmove b8c6 ponder b1c3",
        ]
        engine, fake_stdin = _setup_uci(stdout_lines)
        move = engine.play(fen, depth=5)

        assert move == "b8c6"
        assert f"position fen {fen}" in fake_stdin.commands
        assert "go depth 5" in fake_stdin.commands

    def test_play_with_time_limit(self):
        fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        stdout_lines = ["readyok", "bestmove e2e4"]
        engine, fake_stdin = _setup_uci(stdout_lines)
        move = engine.play(fen, time_limit=2.0)

        assert move == "e2e4"
        assert "go movetime 2000" in fake_stdin.commands

    def test_play_timeout_raises(self):
        fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        engine, _ = _setup_uci(["readyok"])  # readyok but no bestmove
        try:
            engine.play(fen, depth=5, time_limit=0.5)
            assert False, "Should have raised TimeoutError"
        except TimeoutError:
            pass
