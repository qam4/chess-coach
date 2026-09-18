"""The metrics history generator, which produces committed artefacts.

The guard test is the important one. `render_svg` plots run names on a version axis, and a
matrix run is named like `gemma12_seed11` — from which the version parser cheerfully returns 12.
Passing a mixed list produced a chart with 20 spurious points scattered mid-axis under a heading
reading "v2 to v52 (68 runs)". Nothing raised; the picture was simply wrong, and it took someone
looking at it to notice. A wrong chart is worse than no chart, so mixed input now fails loudly.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parent.parent
_SCRIPT = REPO / "scripts" / "metrics_history.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("metrics_history_under_test", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["metrics_history_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _row(run: str, group: str, **over: Any) -> dict[str, Any]:
    """A row with the ratio columns DERIVED from the counts, so the fixture is self-consistent.

    Deriving rather than hardcoding matters: a fixture whose count and share disagree would let
    a test pass against data the generator could never produce.
    """
    base: dict[str, Any] = {
        "run": run,
        "group": group,
        "detector": 1,
        "model": "qwen3:14b",
        "seed": 7,
        "opening": "standard start",
        "engine_sha": "abc123",
        "plies": 44,
        "spoke": 18,
        "clean_pct": "100",
        "bad_turns": 0,
        "gating": 0,
        "cause_given_pct": "72",
        "cause_voiced_pct": "100",
        "mind_reading": 0,
        "magnitude": 0,
        "words_per_turn": "62",
        "lesson_conc_pct": "25",
        "lesson_open": 2,
    }
    base.update(over)
    plies, spoke = int(base["plies"]), int(base["spoke"])
    base["spoke_pct_of_plies"] = f"{100.0 * spoke / plies:.0f}" if plies else ""
    for count_key, pct_key in (
        ("mind_reading", "mind_reading_pct_of_spoken"),
        ("magnitude", "magnitude_pct_of_spoken"),
        ("lesson_open", "lesson_open_pct_of_spoken"),
    ):
        base[pct_key] = f"{100.0 * int(base[count_key]) / spoke:.0f}" if spoke else ""
    base.update({k: v for k, v in over.items() if k.endswith("_pct_of_spoken") or k.endswith("_pct_of_plies")})
    return base


def test_render_svg_refuses_matrix_rows() -> None:
    mod = _load()
    rows = [_row("v2", "history"), _row("gemma12_seed11", "matrix")]
    with pytest.raises(ValueError, match="history rows only"):
        mod.render_svg(rows)


def test_render_svg_accepts_history_alone() -> None:
    mod = _load()
    svg = mod.render_svg([_row("v2", "history"), _row("v52", "history")])
    assert svg.startswith("<svg")
    assert "v2 to v52" in svg


def test_a_metric_that_does_not_apply_is_a_gap_not_a_zero() -> None:
    """An empty cell must break the line, never be drawn at the axis floor.

    `lesson_conc_pct` is blank before a lesson was ever composed. Plotting that as 0% would
    read as perfect variety — the flattering direction, which is the one to guard.
    """
    mod = _load()
    rows = [
        _row("v2", "history", lesson_conc_pct=""),
        _row("v3", "history", lesson_conc_pct=""),
        _row("v4", "history", lesson_conc_pct="25"),
        _row("v5", "history", lesson_conc_pct="25"),
    ]
    assert mod._series(rows, "lesson_conc_pct") == [(4, 25.0), (5, 25.0)]


def test_guard_refuses_to_compare_different_games() -> None:
    """Pairing is on (seed, model). Without it, game variation reads as a regression.

    Measured across five openings on one identical build: `cause_given_pct` spans 27 points. So
    comparing a Sicilian run against a French one and calling the difference a regression would
    fire constantly and mean nothing.
    """
    mod = _load()
    rows = [
        _row("v52_seed7", "history", seed=7, clean_pct="100"),
        _row("v53_seed17", "history", seed=17, clean_pct="80"),
    ]
    code, lines = mod.guard(rows)
    assert code == 1
    assert any("REFUSING to compare" in ln for ln in lines)


def test_guard_passes_when_a_paired_cell_is_unchanged() -> None:
    mod = _load()
    rows = [_row("v52_seed7", "history", seed=7), _row("v53_seed7", "history", seed=7)]
    code, lines = mod.guard(rows)
    assert code == 0, "\n".join(lines)
    assert any("nothing got worse" in ln for ln in lines)


def test_guard_fails_on_a_real_regression_in_a_paired_cell() -> None:
    """Same seed, same model, temperature 0 — so a difference is the build, not sampling."""
    mod = _load()
    rows = [
        _row("v52_seed7", "history", seed=7, clean_pct="100"),
        _row("v53_seed7", "history", seed=7, clean_pct="88"),
    ]
    code, lines = mod.guard(rows)
    assert code == 1
    assert any("FAIL" in ln and "clean_pct" in ln for ln in lines)


def test_guard_ignores_an_improvement() -> None:
    mod = _load()
    rows = [
        _row("v52_seed7", "history", seed=7, lesson_conc_pct="33"),
        _row("v53_seed7", "history", seed=7, lesson_conc_pct="14"),
    ]
    code, _lines = mod.guard(rows)
    assert code == 0, "a lower lesson_conc_pct is better and must not trip the guard"


def test_several_runs_of_one_version_collapse_to_one_point() -> None:
    """From now on a version is measured on several games and models, not one.

    Before aggregation, ten runs of v53 produced ten points at the same x — the line doubled
    back on itself vertically rather than averaging, and the headline card reported whichever
    row happened to sort last as "now".
    """
    mod = _load()
    rows = [_row("v52", "history", clean_pct="100")]
    rows += [_row("v53", "history", seed=s, clean_pct=c) for s, c in ((7, "100"), (11, "90"), (13, "95"))]

    agg = mod._agg(rows, "clean_pct")
    assert [a[0] for a in agg] == [52, 53], "one point per version"
    v53 = next(a for a in agg if a[0] == 53)
    assert v53[1] == 95.0  # mean of 100, 90, 95
    assert (v53[2], v53[3]) == (90.0, 100.0)  # the band


def test_a_decline_is_not_reported_as_flat() -> None:
    """The failure this state machine replaced.

    Comparing the latest value against the WORST ever reads "flat throughout" when the latest
    value IS the worst. `clean_pct` falling 100 -> 97 came out as unchanged, which is the
    flattering reading, and flattering-while-blind is the recurring defect in this project.
    """
    mod = _load()
    rows = [_row("v52", "history", clean_pct="100"), _row("v53", "history", clean_pct="97")]
    card = next(c for c in mod.headline(rows) if c["key"] == "clean_pct")
    assert card["state"] == "worst"
    assert card["better"] is False
    assert card["best"] == 100.0 and card["from_run"] == "v52"


def test_the_best_reading_so_far_says_so() -> None:
    mod = _load()
    rows = [_row("v52", "history", clean_pct="90"), _row("v53", "history", clean_pct="100")]
    card = next(c for c in mod.headline(rows) if c["key"] == "clean_pct")
    assert card["state"] == "best"
    assert card["better"] is True


def test_headline_compares_against_the_worst_value_not_the_first() -> None:
    """First-to-last mislabels a metric whose mechanism did not exist at the start.

    `lesson_open` read 0 before any closing instruction existed, then 44 once we asked openly,
    then 2 today. First-to-last says "0 to 2, worse". Worst-to-last says "down from 44".
    """
    mod = _load()
    rows = [
        _row("v2", "history", spoke=44, lesson_open=0),
        _row("v13", "history", spoke=44, lesson_open=44),
        _row("v52", "history", spoke=18, lesson_open=2),
    ]
    card = next(c for c in mod.headline(rows) if c["key"] == "lesson_open_pct_of_spoken")
    assert card["base"] == 100.0  # v13: 44 of 44 spoken turns
    assert card["from_run"] == "v13"
    assert card["better"] is True


def test_an_unchanged_metric_is_not_a_regression() -> None:
    mod = _load()
    rows = [_row("v2", "history", magnitude=0), _row("v52", "history", magnitude=0)]
    card = next(c for c in mod.headline(rows) if c["key"] == "magnitude_pct_of_spoken")
    assert card["delta"] == 0
    assert card["better"] is None


def test_every_charted_panel_is_a_ratio() -> None:
    """Raw counts are not comparable between games, and the games differ in length.

    The five openings run 23 to 51 plies, so `spoke=18` and `spoke=8` are 41% and 35% of their
    games — close — while the counts look wildly apart. An earlier chart plotted counts against
    a hardcoded "of 44 turns" axis, which is true only of the standard-start game.

    Counts stay in the TSV because they are the auditable ground truth; the chart shows shares.
    """
    mod = _load()
    for key, _label, unit, _ymax, _direction in mod._PANELS:
        assert key.endswith("_pct") or "_pct_of_" in key or key == "words_per_turn", key
        assert "%" in unit or key == "words_per_turn", f"{key} unit is not a share: {unit!r}"
    assert not any("of 44" in p[2] for p in mod._PANELS)


def test_a_short_game_and_a_long_one_are_comparable_as_ratios() -> None:
    """The point of the change. As counts these look far apart; as shares they are close.

    Real numbers from the matrix: the Italian game spoke on 8 of 23 plies, the standard start on
    18 of 44. 8 against 18 reads as a collapse; 35% against 41% reads as roughly the same coach.
    """
    italian = _row("italian", "matrix", plies=23, spoke=8)
    standard = _row("standard", "matrix", plies=44, spoke=18)
    assert italian["spoke_pct_of_plies"] == "35"
    assert standard["spoke_pct_of_plies"] == "41"
