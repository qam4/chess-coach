"""The clause pipeline's behaviour is pinned to a checked-in snapshot.

Why this exists rather than a design document. What the coach says on a turn survives nine
sequential filters — path selection, the silence gates, tier selection, effect priority, the
lesson ladder, the clause ladder, the fact budget, guidance selection, the fidelity gate. Each
was added on its own to answer a specific review finding, and none was designed against the
others. We intend to replace that chain with generate-then-select.

The risk in that refactor is not that we do not know what to build. It is that those nine
filters encode measured lessons — do not claim king activity outside an endgame, do not say
"toward the centre" without a count, do not call an already-developed piece developed, do not
describe a king walk that fails to distinguish itself from the move actually played — and any
one of them could be dropped silently. A document does not protect against that. This does.

If this test fails, the pipeline says something different than it did. That is not
automatically wrong: much of the redesign is *meant* to change behaviour. But every change
must be looked at and approved one at a time, which is exactly what the failure output gives
you::

    python scripts/snapshot_clauses.py --check docs/clause-snapshot.tsv   # see the diff
    python scripts/snapshot_clauses.py --out docs/clause-snapshot.tsv     # approve it

Never regenerate to make a red test green without reading the diff first. That is the one way
this test can quietly become worthless.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SNAPSHOT = REPO / "docs" / "clause-snapshot.tsv"
SCRIPT = REPO / "scripts" / "snapshot_clauses.py"


@pytest.mark.skipif(not SNAPSHOT.exists(), reason="snapshot not generated yet")
def test_the_clause_pipeline_still_says_what_it_said() -> None:
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "--check", str(SNAPSHOT)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (
        "The clause pipeline's behaviour changed.\n\n"
        f"{result.stdout}\n{result.stderr}\n"
        "Read every line above. If each change is intended, approve them with:\n"
        "  python scripts/snapshot_clauses.py --out docs/clause-snapshot.tsv"
    )


@pytest.mark.skipif(not SNAPSHOT.exists(), reason="snapshot not generated yet")
def test_the_snapshot_covers_every_effect_category() -> None:
    """A snapshot that misses a branch cannot protect it.

    The first attempt recorded only the moves actually played in the stored games: 88 rows,
    and most branches never exercised. Every legal move in every stored position is what makes
    it a net rather than a gesture.
    """
    from chess_coach import prompts

    categories = {
        getattr(prompts, name) for name in dir(prompts) if name.startswith("EFFECT_") and name != "EFFECT_TAKEAWAYS"
    }
    seen = {line.split("\t")[5] for line in SNAPSHOT.read_text(encoding="utf-8").splitlines()[1:]}
    missing = {c for c in categories if isinstance(c, str)} - seen
    assert not missing, f"no snapshotted position produces these effects, so nothing protects them: {sorted(missing)}"
