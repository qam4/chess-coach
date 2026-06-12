"""Tests for the coaching-eval benchmark model + loader (Task 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from chess_coach.eval import (
    BenchmarkError,
    BenchmarkPosition,
    GroundTruthPoint,
    load_benchmark,
)
from chess_coach.eval.benchmark import default_benchmark_path

# --------------------------------------------------------------- real data


def test_default_benchmark_loads() -> None:
    """The shipped positions.yaml parses and is non-empty."""
    positions = load_benchmark(default_benchmark_path())
    assert len(positions) >= 8
    assert all(isinstance(p, BenchmarkPosition) for p in positions)
    # Phases and levels are covered.
    phases = {p.phase for p in positions}
    levels = {p.level for p in positions}
    assert {"opening", "middlegame", "endgame"} <= phases
    assert {"beginner", "intermediate", "advanced"} <= levels


def test_default_benchmark_ids_unique() -> None:
    positions = load_benchmark(default_benchmark_path())
    ids = [p.id for p in positions]
    assert len(ids) == len(set(ids))


def test_required_points_filter() -> None:
    positions = load_benchmark(default_benchmark_path())
    by_id = {p.id: p for p in positions}
    hk = by_id["hanging_knight_e5"]
    # hanging_piece e5 is required; the "undefended" free hint is not.
    kinds = {(pt.kind, pt.value): pt.required for pt in hk.points}
    assert kinds[("hanging_piece", "e5")] is True
    assert ("hanging_piece", "e5") in {(p.kind, p.value) for p in hk.required_points()}


# Kinds the Layer 1 coverage check can actually verify against a
# response (mirrors objective._REFERENCEABLE_KINDS + eval_direction).
_REQUIRED_COVERABLE = {"hanging_piece", "tactic", "free", "eval_direction"}


def test_every_position_has_a_required_referenceable_point() -> None:
    """Guard against vacuous scoring: a position whose required points
    are all non-referenceable (e.g. only `phase`) or all optional gets
    coverage 0/0 -> factual 1.0 for any error-free response, which
    reads as a perfect score for generic coaching. Every position must
    pin at least one required, checkable fact."""
    positions = load_benchmark(default_benchmark_path())
    offenders = [p.id for p in positions if not any(pt.kind in _REQUIRED_COVERABLE for pt in p.required_points())]
    assert offenders == [], f"positions with no required referenceable point: {offenders}"


# --------------------------------------------------------------- happy path


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "positions.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_minimal_valid_file(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
version: 1
positions:
  - id: p1
    fen: "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    level: beginner
    phase: opening
    points:
      - kind: eval_direction
        value: equal
      - kind: free
        value: development
        required: false
""",
    )
    positions = load_benchmark(path)
    assert len(positions) == 1
    p = positions[0]
    assert p.id == "p1"
    assert p.points[0] == GroundTruthPoint("eval_direction", "equal", True)
    assert p.points[1].required is False


# --------------------------------------------------------------- failures


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(BenchmarkError, match="not found"):
        load_benchmark(tmp_path / "nope.yaml")


def test_empty_positions(tmp_path: Path) -> None:
    path = _write(tmp_path, "version: 1\npositions: []\n")
    with pytest.raises(BenchmarkError, match="non-empty"):
        load_benchmark(path)


def test_invalid_fen(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
positions:
  - id: bad
    fen: "not a fen"
    level: beginner
    phase: opening
""",
    )
    with pytest.raises(BenchmarkError, match="invalid FEN"):
        load_benchmark(path)


def test_bad_level(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
positions:
  - id: bad
    fen: "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    level: grandmaster
    phase: opening
""",
    )
    with pytest.raises(BenchmarkError, match="level must be one of"):
        load_benchmark(path)


def test_unknown_point_kind(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
positions:
  - id: bad
    fen: "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    level: beginner
    phase: opening
    points:
      - kind: telepathy
        value: x
""",
    )
    with pytest.raises(BenchmarkError, match="unknown point kind"):
        load_benchmark(path)


def test_bad_eval_direction_value(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
positions:
  - id: bad
    fen: "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    level: beginner
    phase: opening
    points:
      - kind: eval_direction
        value: white_winning
""",
    )
    with pytest.raises(BenchmarkError, match="eval_direction value must be"):
        load_benchmark(path)


def test_bad_hanging_square(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
positions:
  - id: bad
    fen: "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    level: beginner
    phase: opening
    points:
      - kind: hanging_piece
        value: z9
""",
    )
    with pytest.raises(BenchmarkError, match="must be a square"):
        load_benchmark(path)


def test_duplicate_ids(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
positions:
  - id: dup
    fen: "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    level: beginner
    phase: opening
  - id: dup
    fen: "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
    level: beginner
    phase: opening
""",
    )
    with pytest.raises(BenchmarkError, match="duplicate position id"):
        load_benchmark(path)


def test_missing_required_field(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
positions:
  - id: bad
    fen: "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    level: beginner
""",
    )
    with pytest.raises(BenchmarkError, match="missing required field 'phase'"):
        load_benchmark(path)
