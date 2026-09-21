"""The backlog's own checks: every actionable item says what it gives, and the table is current.

Runs against the REAL committed `BACKLOG.md`, not a fixture. That is deliberate: the failure this
repo keeps repeating is a check whose inputs come from somewhere the check does not actually
guard — `tests/test_clause_snapshot.py` globbed gitignored `output/` and passed on the dev machine
while failing on every clean checkout. `BACKLOG.md` is committed, so this test guards the thing it
claims to guard.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BACKLOG = REPO / "BACKLOG.md"


def _load():
    """Import the script by path — `scripts/` is not a package."""
    path = REPO / "scripts" / "backlog_index.py"
    spec = importlib.util.spec_from_file_location("backlog_index", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["backlog_index"] = mod
    spec.loader.exec_module(mod)
    return mod


bi = _load()


def test_every_actionable_item_declares_category_gives_and_priority() -> None:
    items, problems = bi.parse(BACKLOG.read_text(encoding="utf-8"))
    assert not problems, "BACKLOG.md items missing metadata:\n  " + "\n  ".join(problems)
    assert items, "no actionable items parsed — the heading pattern has probably drifted"


def test_the_generated_index_is_current() -> None:
    text = BACKLOG.read_text(encoding="utf-8")
    items, problems = bi.parse(text)
    assert not problems
    assert bi.replace_block(text, bi.render(items)) == text, (
        "BACKLOG.md index is stale. Run: python scripts/backlog_index.py"
    )


def test_priority_is_impact_so_every_p1_states_a_reach() -> None:
    """A P1 must say how much it reaches. "Refactor X" is not a priority-1 justification.

    Weak by design — it checks for a digit, not for a good argument. It exists because the thing
    that actually went wrong was a P3 proposed ahead of two P1s, and the tell was that its
    "gives" had no number in it at all.
    """
    items, _ = bi.parse(BACKLOG.read_text(encoding="utf-8"))
    p1 = [it for it in items if it.priority == "P1"]
    assert p1, "no P1 items — if that is genuinely true, delete this test rather than weakening it"
    for it in p1:
        assert any(ch.isdigit() for ch in it.gives), f"P1 {it.title!r} gives no number: {it.gives!r}"


@pytest.mark.parametrize(
    "bad",
    [
        # Missing Priority entirely.
        "## TOP — Do a thing\n\n- **Category:** coaching\n- **Gives:** 3 of 81 turns\n\nprose\n",
        # A category outside the closed list.
        "## TOP — Do a thing\n\n- **Category:** cleanup\n- **Gives:** 3 turns\n- **Priority:** P1\n",
        # Fields below the first prose paragraph, where a reader would not find them.
        "## OPEN — Do a thing\n\nprose first\n\n- **Category:** coaching\n- **Gives:** x\n- **Priority:** P2\n",
    ],
)
def test_malformed_items_are_reported_not_ignored(bad: str) -> None:
    _items, problems = bi.parse(bad)
    assert problems, f"should have been rejected:\n{bad}"


def test_a_record_heading_needs_no_metadata() -> None:
    """DONE items and narrative sections are records, not actions. They must not be flagged."""
    text = (
        "## DONE — Something we finished\n\nprose\n\n"
        "### Closed by measurement, do not reopen\n\nprose\n\n"
        "## TOP — A real action\n\n"
        "- **Category:** instrumentation\n- **Gives:** 5 of 81 turns\n- **Priority:** P2\n"
    )
    items, problems = bi.parse(text)
    assert not problems, problems
    assert [it.title for it in items] == ["A real action"]
