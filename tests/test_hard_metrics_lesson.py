"""Lesson concentration is measured from what we composed, and must not claim to see more.

Replaces a cue-word counter that read the response's last 14 words for one of five hardcoded
phrases. That version was directionally WRONG, not just noisy: it ranked v52 (22%) worse than
v33 (17%), when v33 is the documented monoculture peak — the ledger names the five plies where
one lesson closed five of eighteen turns. Measured from composition, v33 reads 33% falling to
14% by v43, which matches the record.

The important test here is the n/a one. A metric that reports a flattering number when it can
see nothing is the instrument error this project keeps rediscovering.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
_SCRIPT = REPO / "scripts" / "eval_hard_metrics.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("ehm_lesson_under_test", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ehm_lesson_under_test"] = mod  # @dataclass resolves via sys.modules
    spec.loader.exec_module(mod)
    return mod


_TEACH = (
    "CLOSE with one transferable takeaway on THIS lesson and no other: "
    "going after a piece that has too few defenders. Put it in your own words.\n"
)
_SUBST = (
    "CLOSE with one transferable takeaway, and use THIS one rather than the lesson you have "
    "already given earlier in this game: king activity in the endgame. Put it in your own words.\n"
)
_REFRAME = (
    "CLOSE by pointing out that this is the SAME idea as earlier in the game, not by teaching "
    "it again: the student has now met this lesson more than once \u2014 capture value. Say so once.\n"
)
_OPEN = "CLOSE with one transferable takeaway, not a generic maxim: name the principle.\n"


def test_the_four_ladder_states_are_told_apart() -> None:
    mod = _load()
    assert mod._composed_lesson(_TEACH) == ("teach", "going after a piece that has too few defenders")
    assert mod._composed_lesson(_SUBST) == ("subst", "king activity in the endgame")
    assert mod._composed_lesson(_REFRAME) == ("reframe", "capture value")
    # Asked, but we named nothing — the MODEL chooses. Carries no lesson to count.
    assert mod._composed_lesson(_OPEN) == ("open", "")
    # Ladder retired it: no CLOSE instruction at all.
    assert mod._composed_lesson("--- Top lines ---\n1.e4\n") == ("silent", "")


def test_open_is_not_silent() -> None:
    """The distinction is the metric's blind spot, so it has to be visible.

    An open ask means the model picked the topic, which composition-based concentration cannot
    see. Before v30 every turn was open — 44 of 44 at v20 — which is precisely what composing
    the subject was built to stop.
    """
    mod = _load()
    assert mod._composed_lesson(_OPEN)[0] == "open"
    assert mod._composed_lesson("no close here")[0] == "silent"


def test_concentration_is_None_not_zero_when_nothing_was_composed() -> None:
    mod = _load()
    m = mod.Metrics(name="t", spoken=44, lesson_composed=0, lesson_open=44)
    assert m.lesson_concentration is None, "0% would claim perfect variety where the question does not apply"


def test_concentration_divides_by_composed_not_spoken() -> None:
    """v33: one lesson on 5 of 15 composed turns, out of 18 spoken.

    Composed is the population the measurement can see. Dividing by spoken would silently
    credit the turns it cannot read.
    """
    mod = _load()
    m = mod.Metrics(name="t", spoken=18, lesson_composed=15, lesson_open=3)
    m.lessons.update(["too few defenders"] * 5 + ["capture value"] * 4 + [f"other {i}" for i in range(6)])
    assert m.lesson_concentration is not None
    assert round(m.lesson_concentration) == 33


def test_one_lesson_everywhere_reads_as_total_concentration() -> None:
    mod = _load()
    m = mod.Metrics(name="t", spoken=10, lesson_composed=10)
    m.lessons.update(["the only lesson"] * 10)
    assert m.lesson_concentration == 100.0
