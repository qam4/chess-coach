"""The backlog's own checks: every open item has a stable id and says what it gives.

Runs against the REAL committed `BACKLOG.md` and `BUGS.md`, not fixtures. That is deliberate: the
failure this repo keeps repeating is a check whose inputs come from somewhere it does not actually
guard — `tests/test_clause_snapshot.py` globbed gitignored `output/` and passed on the dev machine
while failing on every clean checkout. Both files are committed, so this guards what it claims to.
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


def test_every_open_item_declares_id_category_gives_and_priority() -> None:
    items, problems = bi.parse_all()
    assert not problems, "open items missing metadata:\n  " + "\n  ".join(problems)
    assert items, "no actionable items parsed — the heading patterns have probably drifted"


def test_the_generated_index_is_current() -> None:
    text = BACKLOG.read_text(encoding="utf-8")
    items, problems = bi.parse_all()
    assert not problems
    assert bi.replace_block(text, bi.render(items)) == text, "the index is stale. Run: python scripts/backlog_index.py"


def test_ids_are_unique_across_both_files() -> None:
    items, _ = bi.parse_all()
    idents = [it.ident for it in items]
    assert len(idents) == len(set(idents)), "duplicate ids: an id is a permanent handle"


def test_open_bugs_appear_in_the_index() -> None:
    """The point of spanning two files. If this reads zero, BUGS.md has fallen out of the index."""
    items, _ = bi.parse_all()
    assert any(it.source == "bugs" for it in items), "no open bugs indexed — is BUGS.md still parsed?"


def test_priority_is_impact_so_every_p1_states_a_reach() -> None:
    """A P1 must say how much it reaches. "Refactor X" is not a priority-1 justification.

    Weak by design — it checks for a digit, not for a good argument. It exists because the thing
    that actually went wrong was a P3 proposed ahead of two P1s, and the tell was that its "gives"
    had no number in it at all.
    """
    items, _ = bi.parse_all()
    p1 = [it for it in items if it.priority == "P1"]
    assert p1, "no P1 items — if that is genuinely true, delete this test rather than weakening it"
    for it in p1:
        assert any(ch.isdigit() for ch in it.gives), f"P1 {it.ident} gives no number: {it.gives!r}"


@pytest.mark.parametrize(
    "bad",
    [
        # Priority missing entirely.
        "## TOP — Do a thing\n\n- **Id:** B-900\n- **Category:** coaching\n- **Gives:** 3 turns\n",
        # Category outside the closed list.
        "## TOP — Do a thing\n\n- **Id:** B-900\n- **Category:** cleanup\n- **Gives:** x\n- **Priority:** P1\n",
        # Id not in the B-nnn / BUG-nn form.
        "## TOP — Do a thing\n\n- **Id:** nine\n- **Category:** coaching\n- **Gives:** x\n- **Priority:** P1\n",
        # Fields below the first prose paragraph, where a reader would not find them.
        "## OPEN — Do a thing\n\nprose first\n\n- **Id:** B-900\n- **Category:** coaching\n"
        "- **Gives:** x\n- **Priority:** P2\n",
    ],
)
def test_malformed_backlog_items_are_reported_not_ignored(bad: str) -> None:
    _items, problems = bi.parse_backlog(bad)
    assert problems, f"should have been rejected:\n{bad}"


def test_a_record_heading_needs_no_metadata() -> None:
    """DONE items and narrative sections are records, not actions. They must not be flagged."""
    text = (
        "## DONE — Something we finished\n\nprose\n\n"
        "### Closed by measurement, do not reopen\n\nprose\n\n"
        "## TOP — A real action\n\n"
        "- **Id:** B-900\n- **Category:** instrumentation\n- **Gives:** 5 of 81 turns\n- **Priority:** P2\n"
    )
    items, problems = bi.parse_backlog(text)
    assert not problems, problems
    assert [it.title for it in items] == ["A real action"]


def test_a_fixed_bug_is_a_record_but_an_unannotated_open_one_is_an_error() -> None:
    fixed = "### BUG-900: Something\n- **Status**: FIXED — done in Phase 3.\n- **Observed**: x\n"
    items, problems = bi.parse_bugs(fixed)
    assert not problems and not items

    open_bug = "### BUG-901: Something\n- **Observed**: x\n- **Not fixed**: needs a decision\n"
    items, problems = bi.parse_bugs(open_bug)
    assert problems and "carries no metadata" in problems[0]


def test_partially_fixed_is_not_treated_as_fixed() -> None:
    """BUG-006 is 'PARTIALLY FIXED' and still open.

    A rule keying on the word FIXED anywhere in the status would have filed it as done and hidden
    it from the index, which is exactly the class of silent omission this index exists to prevent.
    """
    partial = (
        "### BUG-902: Slow\n"
        "- **Id:** BUG-902\n- **Category:** infra\n- **Gives:** 1 thing\n- **Priority:** P2\n"
        "- **Status**: PARTIALLY FIXED — half of it.\n"
    )
    items, problems = bi.parse_bugs(partial)
    assert not problems, problems
    assert [it.ident for it in items] == ["BUG-902"]


def test_a_bug_whose_declared_id_disagrees_with_its_heading_is_refused() -> None:
    text = (
        "### BUG-903: Something\n"
        "- **Id:** BUG-999\n- **Category:** infra\n- **Gives:** x\n- **Priority:** P3\n"
        "- **Not fixed**: no\n"
    )
    _items, problems = bi.parse_bugs(text)
    assert problems and "they must match" in problems[0]


def test_a_closed_items_id_is_not_offered_for_reuse() -> None:
    """An id is a permanent handle. A closed item still owns its number.

    The first version of `next_free_id` derived the answer from the OPEN items, so the moment B-007
    was closed it offered B-007 again — and every citation of the closed item would then have
    resolved to a different one.
    """
    suggested = bi.next_free_id()
    text = (bi.BACKLOG.read_text(encoding="utf-8")) + (bi.BUGS.read_text(encoding="utf-8") if bi.BUGS.exists() else "")
    assert f"**Id:** {suggested}" not in text, f"{suggested} is already used somewhere in the files"
