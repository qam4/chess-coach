"""What `eval_hard_metrics` reads off OUR prompt: the composed cause, the cue, the guidance theme.

Ledger row 137 retired a cause metric that matched fragments of our own clauses in the model's
reply. B-021 (2026-10-16) retired its successor too, which pulled squares out of the reply with a
regex: whether the reply told the student the cause is now the judge's reading
(`chess_coach.eval.claims`). What is left here reads only text we composed, so these tests pin
which squares and facts our prompt hands the coach — the half of "did it reach the student" that
is ours.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
_SCRIPT = REPO / "scripts" / "eval_hard_metrics.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("eval_hard_metrics_under_test", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["eval_hard_metrics_under_test"] = mod  # @dataclass resolves via sys.modules
    spec.loader.exec_module(mod)
    return mod


_PROMPT = (
    "--- Something else ---\n"
    "noise\n\n"
    "--- How this came about ---\n"
    "Before Bd2 your pawn on b2 was defended; after it, it is not. "
    "The check that was skipped: after my move, is everything I was defending still defended?\n\n"
    "--- Next section ---\n"
    "more noise\n"
)


def test_cause_squares_ignores_the_moves_destination() -> None:
    """The cause is about b2. d2 is only where the bishop went.

    Anchoring on a move's destination would point the metric at the wrong square, so the
    cause side uses strict extraction: a bare square, not one inside "Bd2".
    """
    mod = _load()
    assert mod._cause_squares(_PROMPT) == {"b2"}


def test_no_composed_cause_is_None_not_empty() -> None:
    """None means "we composed nothing"; empty set means "composed, no square to anchor on".

    They must stay distinguishable: the first is a composition gap we can fix, the second is
    the repeat-clause-only case ("This same piece already came up on move 6"), which is given
    but unscorable and must not count as a miss.
    """
    mod = _load()
    assert mod._cause_squares("--- Top lines ---\n1.e4 e5\n") is None
    repeat_only = "--- How this came about ---\nThis same piece already came up on move 6.\n"
    assert mod._cause_squares(repeat_only) == set()


def test_cause_given_is_a_share_of_spoken_turns() -> None:
    """Given is ours to fix: ~70% of spoken turns are handed a composed cause.

    Its other half, "did the cause reach the student", is the judge's reading since B-021.
    """
    mod = _load()
    assert mod.Metrics(name="t", spoken=10, cause_given=7).cause_given_rate == 70.0


# ---------------------------------------------------------------------------
# The CUE metric (B-012's fifth criterion). Wider than the cause: any concrete fact we
# supplied, including the achievement clause.
# ---------------------------------------------------------------------------

_CUE_PROMPT_NEW = (
    "--- How this came about ---\n"
    "Before Kd1 your pawn on f2 was defended; after it, it is not.\n\n"
    "--- Background (NOT the cause) ---\n"
    "Your knight on g5 is undefended.\n\n"
    "What was available here does this: attacking their undefended bishop on b4.\n"
)

#: The SAME turn as it was composed before B-012. Only the achievement subject differs.
_CUE_PROMPT_OLD = _CUE_PROMPT_NEW.replace("What was available here", "The best move (Bc3)")


def test_the_cue_includes_the_achievement_clause_and_excludes_the_background() -> None:
    """The cue is any concrete fact we supplied — but not the one we labelled "not the cause".

    The background header exists to demote a loose piece when the cause names a different
    square, and the prompt tells the model it is not the subject. Counting it would score a
    turn as voicing the cue for naming the thing we told it to ignore.
    """
    mod = _load()
    cue = mod._cue_squares(_CUE_PROMPT_NEW)
    assert cue == {"f2", "b4"}
    assert "g5" not in cue, "the demoted background piece must not count as the cue"
    # The narrower cause series is unchanged and still answers its own question.
    assert mod._cause_squares(_CUE_PROMPT_NEW) == {"f2"}
    # No facts at all is None, not an empty set: nothing to score either way.
    assert mod._cue_squares("--- Board (piece placement) ---\nrnbq...\n") is None


def test_the_cue_measures_both_sides_of_the_b012_change_identically() -> None:
    """The load-bearing one. A measure used to judge a change must not be blind to one side.

    The first version of `_ACHIEVEMENT_CLAUSE` matched only the post-B-012 subject ("What was
    available here"), so the pre-change runs lost their achievement squares entirely: 66
    anchorable turns on v57 against 74 on v58. That reported the change as a small regression
    when a like-for-like measure showed a larger one — the instrument itself was the wrong
    comparison group.
    """
    mod = _load()
    assert mod._cue_squares(_CUE_PROMPT_OLD) == mod._cue_squares(_CUE_PROMPT_NEW)


# ---------------------------------------------------------------------------
# The THEME counters (B-013): does an injected guidance fact displace the cue?
# ---------------------------------------------------------------------------

_THEME_PROMPT = (
    "--- How this came about ---\n"
    "Before Kf4 your pawn on g7 was defended; after it, it is not.\n\n"
    "--- What to focus on ---\n"
    "- passed pawn — a pawn with no enemy pawn ahead of it on its file or either neighbour.\n"
    " How to apply: push it with support.\n"
    " HERE: your a-file pawn is passed.\n"
)


def test_a_theme_file_expands_to_its_squares() -> None:
    """The theme often names a FILE ("your a-file pawn is passed") where the cue names a square,
    so comparing the two needs one vocabulary: a file expands to its eight squares."""
    mod = _load()
    squares = mod._theme_squares(_THEME_PROMPT)
    assert {f"a{rank}" for rank in range(1, 9)} <= squares


def test_theme_competition_is_keyed_on_the_cue_not_the_cause() -> None:
    """Keyed to the cause, this counter reported 1 competing turn where the truth was 4.

    A turn can keep the CAUSE and still lose the CUE — the cue is the wider set, including the
    achievement clause, and it is what B-012's criterion is about. Both sides are our prompt.
    """
    mod = _load()
    cue = mod._cue_squares(_THEME_PROMPT)
    theme_sq = mod._theme_squares(_THEME_PROMPT)
    assert cue == {"g7"}
    assert theme_sq and not (theme_sq & cue), "the theme points away from the cue"


def test_supplied_facts_label_the_guidance_apart_from_the_cue() -> None:
    """What the judge's reader is handed (B-021): every composed fact, with the guidance labelled."""
    mod = _load()
    facts = mod.supplied_facts(_THEME_PROMPT)
    assert facts[0] == ("How this came about", "Before Kf4 your pawn on g7 was defended; after it, it is not.")
    assert (mod.GUIDANCE, "your a-file pawn is passed.") in facts
