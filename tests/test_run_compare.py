"""A difference is only noise if the input was held fixed.

Guards the routine written after the 2026-09-21 retraction, where a comparison spanning a prompt
change was read as model non-determinism. The load-bearing test is
`test_a_prompt_change_is_not_reported_as_model_noise`: it reproduces the exact shape of that
mistake — most prompts changed, most texts changed — and asserts the routine refuses to call it a
repeat.
"""

from __future__ import annotations

import json
from pathlib import Path

from chess_coach.eval.run_compare import compare, load_turns, partition_repeats


def _write(tmp_path: Path, name: str, turns: list[tuple[int, str, str]]) -> Path:
    """A minimal transcript: (ply, prompt, coach_feedback)."""
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    payload = {"turns": [{"ply": p, "prompt": pr, "coach_feedback": fb} for p, pr, fb in turns]}
    path = d / "transcript.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_identical_runs_are_a_repeat_with_no_noise(tmp_path: Path) -> None:
    turns = [(0, "P0", "said nought"), (2, "P2", "said two")]
    a = _write(tmp_path, "a", turns)
    b = _write(tmp_path, "b", turns)
    c = compare(a, b)
    assert c.is_repeat
    assert c.noise_turns == 0
    assert c.comparable == 2
    assert "byte-identical" in c.verdict()


def test_same_prompt_different_text_is_model_noise(tmp_path: Path) -> None:
    a = _write(tmp_path, "a", [(0, "P0", "one way"), (2, "P2", "same")])
    b = _write(tmp_path, "b", [(0, "P0", "another way"), (2, "P2", "same")])
    c = compare(a, b)
    assert c.is_repeat  # the input never changed, so it IS a repeat
    assert c.model == [0]
    assert c.same == [2]
    assert "non-determinism" in c.verdict()


def test_a_prompt_change_is_not_reported_as_model_noise(tmp_path: Path) -> None:
    """The retracted finding, in miniature.

    Four turns, three of which changed their prompt and their text, one of which held the prompt
    fixed and came back identical. Counting texts gives "3 of 4 differ, the coach is random".
    The truth is one comparable turn and zero noise.
    """
    a = _write(
        tmp_path,
        "v53",
        [
            (0, "P0 em\u00e2\u20ac\u201ddash", "text A"),
            (2, "P2 em\u00e2\u20ac\u201ddash", "text B"),
            (4, "P4 em\u00e2\u20ac\u201ddash", "text C"),
            (6, "P6", "text D"),
        ],
    )
    b = _write(
        tmp_path,
        "v54",
        [
            (0, "P0 em\u2014dash", "text A2"),
            (2, "P2 em\u2014dash", "text B2"),
            (4, "P4 em\u2014dash", "text C2"),
            (6, "P6", "text D"),
        ],
    )
    c = compare(a, b)
    assert not c.is_repeat
    assert c.input_changed == [0, 2, 4]
    assert c.comparable == 1
    assert c.noise_turns == 0
    v = c.verdict()
    assert "NOT a repeat" in v
    assert "attributable to the code" in v


def test_turns_silent_on_both_sides_do_not_pad_the_identical_count(tmp_path: Path) -> None:
    """A silent turn was never a measurement. Counting it makes a moved run look stable."""
    a = _write(tmp_path, "a", [(0, "", ""), (2, "", ""), (4, "P4", "spoke A")])
    b = _write(tmp_path, "b", [(0, "", ""), (2, "", ""), (4, "P4", "spoke B")])
    c = compare(a, b)
    assert c.comparable == 1, "the two silent turns must not be counted"
    assert c.model == [4]


def test_partition_rejects_a_run_whose_prompt_differs(tmp_path: Path) -> None:
    good1 = _write(tmp_path, "r1", [(0, "P0", "x")])
    good2 = _write(tmp_path, "r2", [(0, "P0", "y")])
    other = _write(tmp_path, "r3", [(0, "P0 CHANGED", "z")])
    keep, rejected = partition_repeats([good1, good2, other])
    assert keep == [good1, good2]
    assert [p for p, _ in rejected] == [other]
    assert rejected[0][1].input_changed == [0]


def test_a_turn_present_on_only_one_side_blocks_the_repeat_claim(tmp_path: Path) -> None:
    a = _write(tmp_path, "a", [(0, "P0", "x"), (2, "P2", "y")])
    b = _write(tmp_path, "b", [(0, "P0", "x")])
    c = compare(a, b)
    assert not c.is_repeat
    assert c.only_left == [2]


def test_load_turns_ignores_entries_without_an_integer_ply(tmp_path: Path) -> None:
    d = tmp_path / "odd"
    d.mkdir()
    path = d / "transcript.json"
    path.write_text(json.dumps({"turns": [{"ply": None, "prompt": "p"}, {"ply": 3, "prompt": "q"}]}), encoding="utf-8")
    assert sorted(load_turns(path)) == [3]
