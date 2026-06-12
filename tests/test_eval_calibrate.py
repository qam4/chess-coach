"""Tests for Layer 3 calibration: agreement computation + ratings I/O."""

from __future__ import annotations

from pathlib import Path

import pytest

from chess_coach.eval.calibrate import (
    build_ratings_template,
    compute_agreement,
    load_seed_ratings,
    response_key,
)
from chess_coach.eval.judge import default_rubric_path, load_rubric


def _rubric():
    return load_rubric(default_rubric_path())


def _all(value: bool) -> dict[str, bool]:
    return {k: value for k in _rubric().keys()}


# --------------------------------------------------------------- key


def test_response_key() -> None:
    assert response_key("startpos", "qwen3:8b") == "startpos::qwen3:8b"


# --------------------------------------------------------------- agreement


def test_perfect_agreement() -> None:
    r = _rubric()
    human = {"a::m": _all(True), "b::m": _all(False)}
    judge = {"a::m": _all(True), "b::m": _all(False)}
    rep = compute_agreement(human, judge, r)
    assert rep.n == 2
    assert rep.overall == 1.0
    assert all(v == 1.0 for v in rep.per_criterion.values())
    assert rep.below_threshold == []
    assert rep.ok


def test_total_disagreement() -> None:
    r = _rubric()
    human = {"a::m": _all(True)}
    judge = {"a::m": _all(False)}
    rep = compute_agreement(human, judge, r)
    assert rep.overall == 0.0
    assert set(rep.below_threshold) == set(r.keys())
    assert not rep.ok


def test_known_divergence_one_criterion() -> None:
    r = _rubric()
    # 4 responses; they agree on everything except 'key_idea', which
    # disagrees on 1 of 4 -> 75% for that criterion (below 0.8).
    keys = ["p1::m", "p2::m", "p3::m", "p4::m"]
    human = {k: _all(True) for k in keys}
    judge = {k: _all(True) for k in keys}
    judge["p1::m"]["key_idea"] = False  # one disagreement
    rep = compute_agreement(human, judge, r)
    assert rep.per_criterion["key_idea"] == 0.75
    assert "key_idea" in rep.below_threshold
    # Other criteria still perfect.
    assert rep.per_criterion["actionable"] == 1.0
    assert not rep.ok  # one criterion below threshold


def test_threshold_is_configurable() -> None:
    r = _rubric()
    keys = ["p1::m", "p2::m", "p3::m", "p4::m"]
    human = {k: _all(True) for k in keys}
    judge = {k: _all(True) for k in keys}
    judge["p1::m"]["key_idea"] = False  # 75% on key_idea
    # At threshold 0.7, 75% passes.
    rep = compute_agreement(human, judge, r, threshold=0.7)
    assert rep.below_threshold == []
    assert rep.ok


def test_only_shared_keys_compared() -> None:
    r = _rubric()
    human = {"a::m": _all(True), "b::m": _all(True)}
    judge = {"a::m": _all(True)}  # judge only saw 'a'
    rep = compute_agreement(human, judge, r)
    assert rep.n == 1  # only the shared key
    assert "b::m" in rep.missing
    assert rep.overall == 1.0


def test_no_overlap() -> None:
    r = _rubric()
    rep = compute_agreement({"a::m": _all(True)}, {"b::m": _all(True)}, r)
    assert rep.n == 0
    assert rep.overall == 0.0
    assert not rep.ok


# --------------------------------------------------------------- ratings I/O


def test_load_seed_ratings(tmp_path: Path) -> None:
    p = tmp_path / "ratings.yaml"
    p.write_text(
        'ratings:\n  "startpos::qwen3:8b":\n    key_idea: true\n    grounded: false\n  "p2::m":\n    key_idea: false\n',
        encoding="utf-8",
    )
    out = load_seed_ratings(p)
    assert out["startpos::qwen3:8b"]["key_idea"] is True
    assert out["startpos::qwen3:8b"]["grounded"] is False
    assert out["p2::m"]["key_idea"] is False


def test_load_seed_ratings_skips_nulls(tmp_path: Path) -> None:
    # Unfilled template entries (null) are dropped, not coerced to False.
    p = tmp_path / "ratings.yaml"
    p.write_text(
        'ratings:\n  "a::m":\n    key_idea: true\n    grounded: null\n',
        encoding="utf-8",
    )
    out = load_seed_ratings(p)
    assert out["a::m"] == {"key_idea": True}


def test_load_seed_ratings_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_seed_ratings(tmp_path / "nope.yaml")


def test_build_ratings_template_round_trips(tmp_path: Path) -> None:
    r = _rubric()
    text = build_ratings_template(["a::m", "b::m"], r)
    assert "a::m" in text
    assert "key_idea" in text
    # Template loads as valid YAML with all-null criteria -> empty dicts.
    p = tmp_path / "t.yaml"
    p.write_text(text, encoding="utf-8")
    loaded = load_seed_ratings(p)
    assert set(loaded) == {"a::m", "b::m"}
    assert loaded["a::m"] == {}  # all null until the human fills them
