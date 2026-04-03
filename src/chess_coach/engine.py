"""Chess engine communication layer.

Manages a subprocess running a chess engine (Xboard or UCI protocol),
sends positions, and collects analysis output.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, TYPE_CHECKING

if TYPE_CHECKING:
    from chess_coach.models import ComparisonReport, PositionReport

logger = logging.getLogger(__name__)


@dataclass
class AnalysisLine:
    """A single line of engine analysis (one PV)."""

    depth: int
    score_cp: int  # centipawns, from side-to-move perspective
    nodes: int
    time_ms: int
    pv: list[str]  # moves in coordinate notation (e.g. "e2e4")

    @property
    def score_str(self) -> str:
        if abs(self.score_cp) >= 20000:
            mate_in = (20001 - abs(self.score_cp) + 1) // 2
            sign = "+" if self.score_cp > 0 else "-"
            return f"#{sign}{mate_in}"
        return f"{self.score_cp / 100:+.2f}"


@dataclass
class AnalysisResult:
    """Complete analysis of a position."""

    fen: str
    lines: list[AnalysisLine] = field(default_factory=list)
    best_move: str = ""

    @property
    def top_line(self) -> AnalysisLine | None:
        return self.lines[0] if self.lines else None


class EngineProtocol(ABC):
    """Abstract interface for chess engine communication."""

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def analyze(self, fen: str, depth: int = 18, time_limit: float | None = None) -> AnalysisResult: ...

    @abstractmethod
    def is_ready(self) -> bool: ...

    @abstractmethod
    def play(self, fen: str, depth: int = 18, time_limit: float | None = None) -> str:
        """Return the engine's chosen move in coordinate notation."""
        ...


class XboardEngine(EngineProtocol):
    """Xboard/WinBoard protocol engine driver."""

    def __init__(self, path: str | Path, args: list[str] | None = None):
        self._path = str(path)
        self._args = args or []
        self._proc: subprocess.Popen[str] | None = None
        self._stdin: IO[str] | None = None
        self._stdout: IO[str] | None = None

    def start(self) -> None:
        cmd = [self._path] + self._args
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._stdin = self._proc.stdin
        self._stdout = self._proc.stdout
        self._send("xboard")
        self._send("protover 2")
        # Read feature lines until done
        self._read_until("done=1", timeout=5.0)
        self._send("post")  # Enable thinking output

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._send("quit")
            self._proc.wait(timeout=5)

    def is_ready(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def analyze(self, fen: str, depth: int = 18, time_limit: float | None = None) -> AnalysisResult:
        result = AnalysisResult(fen=fen)

        self._send("force")
        self._send(f"setboard {fen}")
        self._send("analyze")

        deadline = time.monotonic() + (time_limit or max(60.0, depth * 5.0))
        target_depth = depth

        while time.monotonic() < deadline:
            line = self._read_line(timeout=1.0)
            if line is None:
                continue
            # Skip engine debug lines (e.g. Blunder's "# ..." output)
            if line.startswith("#"):
                continue

            logger.debug("Engine raw: %s", line)
            parsed = self._parse_thinking_line(line)
            if parsed:
                logger.debug("Parsed depth=%d score=%d pv=%s", parsed.depth, parsed.score_cp, parsed.pv[:3])
                # Keep only the deepest line per search
                result.lines = [ln for ln in result.lines if ln.depth != parsed.depth]
                result.lines.append(parsed)
                result.lines.sort(key=lambda ln: ln.depth, reverse=True)

                if parsed.depth >= target_depth:
                    break

        self._send("exit")  # Exit analyze mode
        # Small delay to let engine process the exit
        time.sleep(0.1)

        if result.lines:
            result.best_move = result.lines[0].pv[0] if result.lines[0].pv else ""
            logger.info(
                "Analysis complete: depth=%d best_move=%s lines=%d",
                result.lines[0].depth,
                result.best_move,
                len(result.lines),
            )
        else:
            logger.warning("Analysis returned no lines for FEN: %s", fen)

        return result

    def play(self, fen: str, depth: int = 18, time_limit: float | None = None) -> str:
        """Return the engine's chosen move in coordinate notation."""
        self._send("force")
        self._send(f"setboard {fen}")
        if time_limit:
            self._send(f"st {int(time_limit)}")
        else:
            self._send(f"sd {depth}")
        self._send("go")
        # Read until we get "move <move>"
        deadline = time.monotonic() + (time_limit or depth * 2.0)
        while time.monotonic() < deadline:
            line = self._read_line(timeout=1.0)
            if line and line.startswith("move "):
                return line.split()[1]
        raise TimeoutError("Engine did not return a move")

    def _parse_thinking_line(self, line: str) -> AnalysisLine | None:
        """Parse xboard thinking output.

        Supports two formats:
        1. Standard xboard: depth score time_cs nodes pv...
        2. Blunder verbose: depth=N, search ply=N, searched moves=N, time=Ns, score=N, pv=...
        """
        stripped = line.strip()

        # Try Blunder verbose format first
        if stripped.startswith("depth="):
            return self._parse_blunder_line(stripped)

        # Standard xboard format: depth score time nodes pv...
        parts = stripped.split()
        if len(parts) < 5:
            return None
        try:
            depth = int(parts[0])
            score_cp = int(parts[1])
            time_cs = int(parts[2])  # centiseconds
            nodes = int(parts[3])
            pv = parts[4:]
            return AnalysisLine(
                depth=depth,
                score_cp=score_cp,
                nodes=nodes,
                time_ms=time_cs * 10,
                pv=pv,
            )
        except (ValueError, IndexError):
            return None

    def _parse_blunder_line(self, line: str) -> AnalysisLine | None:
        """Parse Blunder's verbose thinking format.

        Example:
          depth=6, searched moves=122462, time=0.89s, score=3288,
          pv=1. ... Nc6 2. Bc4 e5
        """
        import re

        depth_m = re.search(r"depth=(\d+)", line)
        score_m = re.search(r"score=(-?\d+)", line)
        nodes_m = re.search(r"searched moves=(\d+)", line)
        time_m = re.search(r"time=([0-9.]+)s", line)
        pv_m = re.search(r"pv=(.+)$", line)

        if not (depth_m and score_m):
            return None

        depth = int(depth_m.group(1))
        score_cp = int(score_m.group(1))
        nodes = int(nodes_m.group(1)) if nodes_m else 0
        time_s = float(time_m.group(1)) if time_m else 0.0

        # Parse PV: strip move numbers ("1.", "2.", "1. ...") to get bare SAN moves
        pv_san: list[str] = []
        if pv_m:
            pv_raw = pv_m.group(1).strip()
            for token in pv_raw.split():
                # Skip move numbers like "1.", "2." and ellipsis "..."
                if re.match(r"^\d+\.$", token) or token == "...":
                    continue
                pv_san.append(token)

        return AnalysisLine(
            depth=depth,
            score_cp=score_cp,
            nodes=nodes,
            time_ms=int(time_s * 1000),
            pv=pv_san,
        )

    def _send(self, cmd: str) -> None:
        if self._stdin:
            self._stdin.write(cmd + "\n")
            self._stdin.flush()

    def _read_line(self, timeout: float = 1.0) -> str | None:
        """Read a single line with timeout."""
        if not self._stdout:
            return None

        result: list[str] = []
        done = threading.Event()

        def _reader() -> None:
            assert self._stdout is not None
            line = self._stdout.readline()
            result.append(line)
            done.set()

        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        done.wait(timeout=timeout)

        if result:
            return result[0].strip()
        return None

    def _read_until(self, marker: str, timeout: float = 5.0) -> list[str]:
        """Read lines until one contains the marker."""
        lines: list[str] = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            line = self._read_line(timeout=remaining)
            if line is None or line == "":
                continue
            # Skip engine debug lines (e.g. Blunder's "# ..." output)
            if line.startswith("#"):
                continue
            lines.append(line)
            if marker in line:
                break
        return lines


class UciEngine(EngineProtocol):
    """UCI protocol engine driver.

    Implements the Universal Chess Interface protocol for engines that
    support ``--uci`` (e.g. Blunder, Stockfish).

    UCI info line format::

        info depth 8 score cp 77 nodes 238953 nps 1993933 time 110 pv e2e3 b8c6 ...

    The ``bestmove`` line terminates a ``go`` command::

        bestmove e2e3 ponder b8c6
    """

    def __init__(self, path: str | Path, args: list[str] | None = None):
        self._path = str(path)
        self._args = args or []
        self._proc: subprocess.Popen[str] | None = None
        self._stdin: IO[str] | None = None
        self._stdout: IO[str] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        cmd = [self._path] + self._args
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._stdin = self._proc.stdin
        self._stdout = self._proc.stdout

        self._send("uci")
        self._read_until("uciok", timeout=5.0)
        self._send("isready")
        self._read_until("readyok", timeout=5.0)

    def set_option(self, name: str, value: str | int | bool) -> None:
        """Send a UCI setoption command."""
        if isinstance(value, bool):
            value = "true" if value else "false"
        self._send(f"setoption name {name} value {value}")
        self._send("isready")
        self._read_until("readyok", timeout=2.0)

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._send("quit")
            self._proc.wait(timeout=5)

    def is_ready(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # ------------------------------------------------------------------
    # Analysis (infinite / depth-limited)
    # ------------------------------------------------------------------

    def analyze(
        self,
        fen: str,
        depth: int = 18,
        time_limit: float | None = None,
    ) -> AnalysisResult:
        result = AnalysisResult(fen=fen)

        self._send(f"position fen {fen}")
        self._send("isready")
        self._read_until("readyok", timeout=5.0)

        if time_limit:
            movetime_ms = int(time_limit * 1000)
            self._send(f"go movetime {movetime_ms}")
        else:
            self._send(f"go depth {depth}")

        # Read info lines until bestmove
        deadline = time.monotonic() + (time_limit or max(60.0, depth * 5.0))
        while time.monotonic() < deadline:
            line = self._read_line(timeout=1.0)
            if line is None:
                continue

            logger.debug("UCI raw: %s", line)

            if line.startswith("bestmove"):
                # Extract bestmove token
                parts = line.split()
                if len(parts) >= 2 and not result.best_move:
                    result.best_move = parts[1]
                break

            if line.startswith("info"):
                parsed = self._parse_info_line(line)
                if parsed:
                    # Keep the deepest line per depth
                    result.lines = [ln for ln in result.lines if ln.depth != parsed.depth]
                    result.lines.append(parsed)
                    result.lines.sort(key=lambda ln: ln.depth, reverse=True)

        # Derive best_move from deepest PV if bestmove wasn't explicit
        if not result.best_move and result.lines and result.lines[0].pv:
            result.best_move = result.lines[0].pv[0]

        if result.lines:
            logger.info(
                "UCI analysis complete: depth=%d best_move=%s lines=%d",
                result.lines[0].depth,
                result.best_move,
                len(result.lines),
            )
        else:
            logger.warning("UCI analysis returned no lines for FEN: %s", fen)

        return result

    # ------------------------------------------------------------------
    # Play (engine picks a move)
    # ------------------------------------------------------------------

    def play(
        self,
        fen: str,
        depth: int = 18,
        time_limit: float | None = None,
    ) -> str:
        """Return the engine's chosen move in coordinate notation."""
        self._send(f"position fen {fen}")
        self._send("isready")
        self._read_until("readyok", timeout=5.0)

        if time_limit:
            movetime_ms = int(time_limit * 1000)
            self._send(f"go movetime {movetime_ms}")
        else:
            self._send(f"go depth {depth}")

        deadline = time.monotonic() + (time_limit or max(30.0, depth * 2.0))
        while time.monotonic() < deadline:
            line = self._read_line(timeout=1.0)
            if line and line.startswith("bestmove"):
                parts = line.split()
                if len(parts) >= 2:
                    return parts[1]
        raise TimeoutError("UCI engine did not return bestmove")

    # ------------------------------------------------------------------
    # UCI info line parser
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_info_line(line: str) -> AnalysisLine | None:
        """Parse a UCI ``info`` line into an AnalysisLine.

        Example::

            info depth 8 score cp 77 nodes 238953 nps 1993933 time 110 pv e2e3 b8c6 ...
            info depth 5 score mate 3 nodes 1234 time 10 pv e1g1 ...
        """
        tokens = line.split()
        if tokens[0] != "info":
            return None

        depth = 0
        score_cp = 0
        nodes = 0
        time_ms = 0
        pv: list[str] = []

        i = 1
        while i < len(tokens):
            tok = tokens[i]
            if tok == "depth" and i + 1 < len(tokens):
                try:
                    depth = int(tokens[i + 1])
                except ValueError:
                    pass
                i += 2
            elif tok == "score" and i + 1 < len(tokens):
                kind = tokens[i + 1]
                if kind == "cp" and i + 2 < len(tokens):
                    try:
                        score_cp = int(tokens[i + 2])
                    except ValueError:
                        pass
                    i += 3
                elif kind == "mate" and i + 2 < len(tokens):
                    try:
                        mate_in = int(tokens[i + 2])
                        # Encode mate scores the same way as AnalysisLine.score_str expects
                        sign = 1 if mate_in > 0 else -1
                        score_cp = sign * (20001 - abs(mate_in) * 2)
                    except ValueError:
                        pass
                    i += 3
                else:
                    i += 2
            elif tok == "nodes" and i + 1 < len(tokens):
                try:
                    nodes = int(tokens[i + 1])
                except ValueError:
                    pass
                i += 2
            elif tok == "time" and i + 1 < len(tokens):
                try:
                    time_ms = int(tokens[i + 1])
                except ValueError:
                    pass
                i += 2
            elif tok == "pv":
                pv = tokens[i + 1 :]
                break
            else:
                i += 1

        # Skip lines without depth or PV (e.g. "info string ..." or partial)
        if depth == 0 or not pv:
            return None

        return AnalysisLine(
            depth=depth,
            score_cp=score_cp,
            nodes=nodes,
            time_ms=time_ms,
            pv=pv,
        )

    # ------------------------------------------------------------------
    # I/O helpers (same pattern as XboardEngine)
    # ------------------------------------------------------------------

    def _send(self, cmd: str) -> None:
        if self._stdin:
            self._stdin.write(cmd + "\n")
            self._stdin.flush()

    def _read_line(self, timeout: float = 1.0) -> str | None:
        """Read a single line with timeout.

        Uses a shared queue fed by a persistent reader thread to avoid
        orphaned threads stealing lines from subsequent reads.
        """
        if not self._stdout:
            return None

        if not hasattr(self, "_line_queue"):
            import queue as _queue

            self._line_queue: _queue.Queue[str] = _queue.Queue()

            def _reader_loop() -> None:
                assert self._stdout is not None
                try:
                    while True:
                        line = self._stdout.readline()
                        if not line:
                            break
                        self._line_queue.put(line)
                except (ValueError, OSError):
                    pass

            t = threading.Thread(target=_reader_loop, daemon=True)
            t.start()

        try:
            line = self._line_queue.get(timeout=timeout)
            return line.strip()
        except Exception:
            return None

    def _read_until(self, marker: str, timeout: float = 5.0) -> list[str]:
        """Read lines until one contains the marker."""
        lines: list[str] = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            line = self._read_line(timeout=remaining)
            if line is None or line == "":
                continue
            lines.append(line)
            if marker in line:
                break
        return lines


# ---------------------------------------------------------------------------
# CoachingEngine — UCI + coaching protocol adapter
# ---------------------------------------------------------------------------

EXPECTED_VERSION = "1.0.0"


class CoachingEngine(EngineProtocol):
    """Engine adapter that wraps :class:`UciEngine` and adds coaching protocol support.

    The coaching protocol runs alongside UCI over the same stdin/stdout pipe.
    Commands prefixed with ``coach`` return JSON responses delimited by
    ``BEGIN_COACH_RESPONSE`` / ``END_COACH_RESPONSE`` markers.

    On :meth:`start`, the engine is probed with ``coach ping``.  If the engine
    responds, :attr:`coaching_available` is ``True`` and the rich
    :meth:`get_position_report` / :meth:`get_comparison_report` methods are
    usable.  Otherwise the adapter falls back to pure UCI via the inner engine.
    """

    def __init__(
        self,
        path: str | Path,
        args: list[str] | None = None,
        coaching_timeout: float = 30.0,
        ping_timeout: float = 2.0,
    ) -> None:
        self._inner = UciEngine(path, args)
        self._coaching_timeout = coaching_timeout
        self._ping_timeout = ping_timeout
        self._coaching_available = False

    # ------------------------------------------------------------------
    # EngineProtocol interface — delegated to inner UciEngine
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._inner.start()
        self._probe_coaching_protocol()

    def stop(self) -> None:
        self._inner.stop()

    def set_option(self, name: str, value: str | int | bool) -> None:
        """Send a UCI setoption command via the inner engine."""
        self._inner.set_option(name, value)

    def analyze(self, fen: str, depth: int = 18, time_limit: float | None = None) -> AnalysisResult:
        return self._inner.analyze(fen, depth, time_limit)

    def is_ready(self) -> bool:
        return self._inner.is_ready()

    def play(self, fen: str, depth: int = 18, time_limit: float | None = None) -> str:
        return self._inner.play(fen, depth, time_limit)

    # ------------------------------------------------------------------
    # Coaching protocol
    # ------------------------------------------------------------------

    @property
    def coaching_available(self) -> bool:
        """Whether the connected engine supports the coaching protocol."""
        return self._coaching_available

    def get_position_report(
        self,
        fen: str,
        multipv: int = 3,
        depth: int | None = None,
        movetime: int | None = None,
    ) -> "PositionReport":
        """Request a rich position evaluation from the engine.

        Sends ``coach eval fen <FEN> multipv <N>`` and parses the JSON
        response into a :class:`PositionReport`.

        Args:
            fen: FEN string of the position to evaluate.
            multipv: Number of principal variation lines to return.
            depth: Search depth limit in plies. Mutually exclusive with movetime.
            movetime: Search time limit in milliseconds. Mutually exclusive with depth.

        Raises:
            CoachingTimeoutError: If the engine does not respond in time.
            EngineTerminatedError: If the engine process has died.
            CoachingParseError: If the response JSON is malformed.
            CoachingValidationError: If the response doesn't match the schema.
        """
        from chess_coach.models import (
            format_coaching_command,
            validate_position_report,
        )

        cmd = format_coaching_command("eval", fen=fen, multipv=multipv, depth=depth, movetime=movetime)
        data = self._send_coaching_command(cmd)
        return validate_position_report(data)

    def get_comparison_report(
        self,
        fen: str,
        user_move: str,
        depth: int | None = None,
        movetime: int | None = None,
    ) -> "ComparisonReport":
        """Request a move comparison report from the engine.

        Sends ``coach compare fen <FEN> move <MOVE>`` and parses the JSON
        response into a :class:`ComparisonReport`.

        Args:
            fen: FEN string of the position before the move.
            user_move: The user's move in UCI notation.
            depth: Search depth limit in plies. Mutually exclusive with movetime.
            movetime: Search time limit in milliseconds. Mutually exclusive with depth.

        Raises:
            CoachingTimeoutError: If the engine does not respond in time.
            EngineTerminatedError: If the engine process has died.
            CoachingParseError: If the response JSON is malformed.
            CoachingValidationError: If the response doesn't match the schema.
        """
        from chess_coach.models import (
            format_coaching_command,
            validate_comparison_report,
        )

        cmd = format_coaching_command("compare", fen=fen, move=user_move, depth=depth, movetime=movetime)
        data = self._send_coaching_command(cmd)
        return validate_comparison_report(data)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _probe_coaching_protocol(self) -> bool:
        """Send ``coach ping`` to detect coaching protocol support.

        Sets :attr:`_coaching_available` based on the result.  Returns
        ``True`` when the protocol is available.
        """
        from chess_coach.models import (
            check_version_compatibility,
            format_coaching_command,
            parse_coaching_envelope,
        )

        try:
            cmd = format_coaching_command("ping")
            self._inner._send(cmd)

            # Read lines until END_COACH_RESPONSE or timeout
            lines: list[str] = []
            deadline = time.monotonic() + self._ping_timeout
            while time.monotonic() < deadline:
                remaining = max(0.1, deadline - time.monotonic())
                line = self._inner._read_line(timeout=remaining)
                if line is None or line == "":
                    continue
                lines.append(line)
                if "END_COACH_RESPONSE" in line:
                    break

            if not any("END_COACH_RESPONSE" in ln for ln in lines):
                # Engine didn't respond — coaching not available
                logger.info("Engine does not support coaching protocol (ping timeout)")
                self._coaching_available = False
                return False

            envelope = parse_coaching_envelope(lines)
            engine_version = envelope.get("version", "0.0.0")
            compat = check_version_compatibility(engine_version, EXPECTED_VERSION)

            if compat == "incompatible":
                logger.warning(
                    "Coaching protocol version mismatch: engine=%s expected=%s — disabling coaching",
                    engine_version,
                    EXPECTED_VERSION,
                )
                self._coaching_available = False
                return False

            if compat == "compatible_warning":
                logger.info(
                    "Coaching protocol minor version difference: engine=%s expected=%s",
                    engine_version,
                    EXPECTED_VERSION,
                )

            logger.info("Coaching protocol available (engine version %s)", engine_version)
            self._coaching_available = True
            return True

        except Exception:
            logger.debug("Coaching protocol probe failed", exc_info=True)
            self._coaching_available = False
            return False

    def _send_coaching_command(self, cmd: str) -> dict[str, object]:
        """Send a coaching command and return the parsed response data dict.

        Writes *cmd* to the engine's stdin, reads lines until
        ``END_COACH_RESPONSE`` or timeout, then parses via
        :func:`parse_coaching_response`.

        Raises:
            EngineTerminatedError: If the engine process is not running.
            CoachingTimeoutError: If no ``END_COACH_RESPONSE`` within
                :attr:`_coaching_timeout`.
            CoachingParseError: If the response is malformed JSON.
        """
        from chess_coach.models import (
            CoachingTimeoutError,
            EngineTerminatedError,
            parse_coaching_response,
        )

        # Check process is alive before sending
        proc = self._inner._proc
        if proc is None or proc.poll() is not None:
            raise EngineTerminatedError("engine process is not running")

        # Flush the pipe: send isready and drain until readyok.
        # This ensures no leftover output from previous commands
        # (e.g. setoption) interferes with the coaching response.
        self._inner._send("isready")
        self._inner._read_until("readyok", timeout=5.0)

        self._inner._send(cmd)

        lines: list[str] = []
        deadline = time.monotonic() + self._coaching_timeout
        while time.monotonic() < deadline:
            # Check for process death during read
            if proc.poll() is not None:
                raise EngineTerminatedError("engine process terminated during coaching command")

            remaining = max(0.1, deadline - time.monotonic())
            line = self._inner._read_line(timeout=min(remaining, 1.0))
            if line is None or line == "":
                continue
            lines.append(line)
            if "END_COACH_RESPONSE" in line:
                break

        if not any("END_COACH_RESPONSE" in ln for ln in lines):
            raise CoachingTimeoutError(f"coaching command timed out after {self._coaching_timeout}s: {cmd}")

        return parse_coaching_response(lines)
