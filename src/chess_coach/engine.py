"""Chess engine communication layer.

Manages a subprocess running a chess engine (Xboard or UCI protocol),
sends positions, and collects analysis output.
"""

from __future__ import annotations

import subprocess
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO


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
    def analyze(
        self, fen: str, depth: int = 18, time_limit: float | None = None
    ) -> AnalysisResult: ...

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

        deadline = time.monotonic() + (time_limit or depth * 2.0)
        target_depth = depth

        while time.monotonic() < deadline:
            line = self._read_line(timeout=1.0)
            if line is None:
                continue

            parsed = self._parse_thinking_line(line)
            if parsed:
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
        """Parse xboard thinking output: depth score time nodes pv..."""
        parts = line.strip().split()
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
            line = self._read_line(timeout=deadline - time.monotonic())
            if line is None:
                break
            lines.append(line)
            if marker in line:
                break
        return lines
