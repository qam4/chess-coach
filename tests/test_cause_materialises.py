"""The cause detector is judged against what the opponent actually did, not against its own rule.

Why this test exists rather than another board check at the moment of the turn: the first measure of
this detector asked "can the opponent attack this square now or in one move", which is the same
predicate the detector applies, so it could not disagree with it. This one reads the continuation of
the game, which the detector never sees.

Runs over the committed v55 transcripts. They are committed - `.gitignore` un-ignores
`output/coach_review_v*/transcript.json` - so this guards the thing it claims to guard rather than
whatever happens to be on one machine.

Sample size is small and stated in the assertions: 12 causes across five games. The thresholds are
loose on purpose. This is a guard against the detector being loosened until its warnings are noise,
not a precise estimate of anything.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TRANSCRIPTS = sorted(REPO.glob("output/coach_review_v55_seed*/transcript.json"))


def _load():
    path = REPO / "scripts" / "eval_cause_materialises.py"
    spec = importlib.util.spec_from_file_location("eval_cause_materialises", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["eval_cause_materialises"] = mod
    spec.loader.exec_module(mod)
    return mod


ecm = _load()

pytestmark = pytest.mark.skipif(
    not TRANSCRIPTS,
    reason="v55 transcripts absent; nothing to judge the detector against",
)


def _all_outcomes():
    rows = []
    for p in TRANSCRIPTS:
        rows.extend(ecm.outcomes(p))
    return rows


def test_most_warnings_describe_a_threat_that_actually_arrives() -> None:
    """A FLOOR guard against future loosening. It does NOT demonstrate the gate that added it.

    Checked, because the temptation was to imply otherwise: the pre-gate build reads 11 of 16 (69%)
    and passes this floor as well. So this test would not have caught the defect it was written
    alongside. It catches the next person widening the detector until most of its warnings are about
    threats that never come.

    The floor stays at 60% rather than being tightened to sit between 69% and 83%, because with 12
    samples a threshold placed between two measurements is fitted to those measurements.
    """
    rows = _all_outcomes()
    assert rows, "no own-piece causes found at all — the cause frame has probably changed"
    hit = [r for r in rows if r.materialised]
    rate = len(hit) / len(rows)
    assert rate >= 0.60, (
        f"only {len(hit)}/{len(rows)} ({rate:.0%}) of 'you stopped defending X' warnings describe a "
        "square the opponent ever attacked. The detector is warning about threats that never arrive."
    )


def test_the_threat_arrives_soon_rather_than_eventually() -> None:
    """A warning is about THIS move. If the threat lands thirty plies later it is not a consequence.

    Measured median 8 plies with the gate, max 14; without it the max was 28.
    """
    delays = [r.delay for r in _all_outcomes() if r.delay is not None]
    assert delays
    median = sorted(delays)[len(delays) // 2]
    assert median <= 16, f"median delay {median} plies — the warnings are not about the move that caused them"


def test_curated_puzzle_positions_are_excluded() -> None:
    """A curated position has no continuation, so a cause on one can never materialise.

    Counting them would push the rate down for a reason that has nothing to do with the detector —
    the same shape as the metric that divided by all 44 turns including the silent ones.
    """
    assert all(r.ply < 1000 for r in _all_outcomes())
