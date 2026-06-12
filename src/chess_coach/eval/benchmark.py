"""Benchmark position model + loader for the coaching eval harness.

A ``BenchmarkPosition`` is a position annotated with the coaching
points a correct response should cover. Unlike the old keyword tests,
the points are *structured, checkable assertions* wherever possible —
``hanging_piece: e4``, ``eval_direction: white_better`` — so Layer 1
can verify them against the engine's report instead of grepping for
vocabulary.

The set lives as data (``data/eval/positions.yaml``) so it grows
without code changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chess
import yaml

# Ground-truth point kinds. Each maps to a Layer 1 check (Task 2):
#
# - hanging_piece   value = square ("e4"); checked against report.hanging_pieces
# - eval_direction  value in {white_better, black_better, equal}; sign of eval_cp
# - tactic          value = motif type ("fork"); checked against report.tactics
# - phase           value in {opening, middlegame, endgame}; phase-appropriateness
# - free            value = text; soft coverage hint, no structured check
KNOWN_KINDS = frozenset({"hanging_piece", "eval_direction", "tactic", "phase", "free"})

_EVAL_DIRECTIONS = frozenset({"white_better", "black_better", "equal"})
_PHASES = frozenset({"opening", "middlegame", "endgame"})
_LEVELS = frozenset({"beginner", "intermediate", "advanced"})


class BenchmarkError(Exception):
    """Raised when the benchmark file is malformed. Fail-fast: the
    message names the offending position/field so the author can fix
    it immediately."""


@dataclass(frozen=True)
class GroundTruthPoint:
    """One checkable coaching point for a position."""

    kind: str
    value: str
    required: bool = True


@dataclass(frozen=True)
class BenchmarkPosition:
    """A position annotated with ground-truth coaching points."""

    id: str
    fen: str
    level: str
    phase: str
    points: tuple[GroundTruthPoint, ...]
    notes: str = ""

    def required_points(self) -> tuple[GroundTruthPoint, ...]:
        return tuple(p for p in self.points if p.required)


def _err(ctx: str, msg: str) -> BenchmarkError:
    return BenchmarkError(f"{ctx}: {msg}")


def _validate_fen(fen: str, ctx: str) -> None:
    try:
        chess.Board(fen)
    except (ValueError, AssertionError) as e:
        raise _err(ctx, f"invalid FEN {fen!r}: {e}") from e


def _parse_point(raw: Any, ctx: str) -> GroundTruthPoint:
    if not isinstance(raw, dict):
        raise _err(ctx, f"point must be a mapping, got {type(raw).__name__}")
    if "kind" not in raw:
        raise _err(ctx, "point missing 'kind'")
    if "value" not in raw:
        raise _err(ctx, "point missing 'value'")
    kind = str(raw["kind"])
    value = str(raw["value"])
    required = bool(raw.get("required", True))

    if kind not in KNOWN_KINDS:
        raise _err(ctx, f"unknown point kind {kind!r} (known: {sorted(KNOWN_KINDS)})")

    # Per-kind value validation — catches typos early.
    if kind == "eval_direction" and value not in _EVAL_DIRECTIONS:
        raise _err(ctx, f"eval_direction value must be one of {sorted(_EVAL_DIRECTIONS)}, got {value!r}")
    if kind == "phase" and value not in _PHASES:
        raise _err(ctx, f"phase value must be one of {sorted(_PHASES)}, got {value!r}")
    if kind == "hanging_piece":
        try:
            chess.parse_square(value)
        except ValueError as e:
            raise _err(ctx, f"hanging_piece value must be a square like 'e4', got {value!r}") from e

    return GroundTruthPoint(kind=kind, value=value, required=required)


def _parse_position(raw: Any, index: int) -> BenchmarkPosition:
    ctx = f"positions[{index}]"
    if not isinstance(raw, dict):
        raise _err(ctx, f"position must be a mapping, got {type(raw).__name__}")

    for field in ("id", "fen", "level", "phase"):
        if field not in raw:
            raise _err(ctx, f"missing required field '{field}'")

    pos_id = str(raw["id"])
    ctx = f"positions[{index}] ({pos_id})"
    fen = str(raw["fen"])
    level = str(raw["level"])
    phase = str(raw["phase"])
    notes = str(raw.get("notes", ""))

    _validate_fen(fen, ctx)
    if level not in _LEVELS:
        raise _err(ctx, f"level must be one of {sorted(_LEVELS)}, got {level!r}")
    if phase not in _PHASES:
        raise _err(ctx, f"phase must be one of {sorted(_PHASES)}, got {phase!r}")

    raw_points = raw.get("points", [])
    if not isinstance(raw_points, list):
        raise _err(ctx, f"'points' must be a list, got {type(raw_points).__name__}")
    points = tuple(_parse_point(p, f"{ctx}.points[{i}]") for i, p in enumerate(raw_points))

    return BenchmarkPosition(
        id=pos_id,
        fen=fen,
        level=level,
        phase=phase,
        points=points,
        notes=notes,
    )


def load_benchmark(path: str | Path) -> list[BenchmarkPosition]:
    """Load and validate the benchmark position set.

    Raises :class:`BenchmarkError` (fail-fast) on the first malformed
    entry, naming the offending position and field.
    """
    path = Path(path)
    if not path.exists():
        raise BenchmarkError(f"benchmark file not found: {path}")

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise BenchmarkError(f"{path}: invalid YAML: {e}") from e

    if not isinstance(data, dict):
        raise BenchmarkError(f"{path}: top level must be a mapping with a 'positions' list")
    raw_positions = data.get("positions")
    if not isinstance(raw_positions, list) or not raw_positions:
        raise BenchmarkError(f"{path}: 'positions' must be a non-empty list")

    positions = [_parse_position(p, i) for i, p in enumerate(raw_positions)]

    # Duplicate-id guard — ids key the results, so collisions silently
    # overwrite. Catch them at load time.
    seen: set[str] = set()
    for p in positions:
        if p.id in seen:
            raise BenchmarkError(f"{path}: duplicate position id {p.id!r}")
        seen.add(p.id)

    return positions


def default_benchmark_path() -> Path:
    """Repo-relative default location of the benchmark set."""
    # src/chess_coach/eval/benchmark.py -> repo root is three parents up.
    return Path(__file__).resolve().parents[3] / "data" / "eval" / "positions.yaml"
