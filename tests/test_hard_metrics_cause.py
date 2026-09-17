"""The cause metric must stay anchored to the board, not to our phrasing.

Ledger row 137. The version this replaces matched literal fragments lifted from our own
composed clauses, so it scored whether the model echoed our sentences: 50%/50% for qwen3:14b
against 17%/12% for gemma4:12b-it-qat, while every gemma turn it scored zero on did explain
why the move failed. One missed on a single word — "check that was skipped" versus "check was
skipped".

These tests exist so that class of metric cannot come back. The paraphrase test is the load
bearing one: it fails if anyone reintroduces phrase matching.
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


def test_a_square_inside_a_SAN_token_counts_on_the_coach_side() -> None:
    """Asymmetric on purpose, and measured.

    At ply 8 of seed 13 the cause was "their bishop on c3 was attacked and undefended, and
    bxc3 does not take it" and the coach answered "the stronger move was Bxc3, capturing their
    bishop". Strict matching scored that a miss, which it is not.
    """
    mod = _load()
    assert mod._voices_the_cause("The stronger move was Bxc3, capturing their bishop.", {"c3"})
    assert mod._voices_the_cause("the opponent plays Rxb2, taking it", {"b2"})


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


def test_a_paraphrase_scores_THE_SAME_as_an_echo() -> None:
    """The regression this whole change exists to prevent.

    Both turns convey the same cause. The retired metric scored the first and missed the
    second, purely on wording — which is how a second model appeared 35 points worse while
    teaching the same thing.
    """
    mod = _load()
    squares = mod._cause_squares(_PROMPT)
    assert squares is not None

    echo = "The check that was skipped: your pawn on b2 was defended before Bd2 and is not now."
    paraphrase = "You left b2 unprotected — it had a defender before, and after your move it has none."

    assert mod._voices_the_cause(echo, squares)
    assert mod._voices_the_cause(paraphrase, squares)

    # And the retired phrasing must not be what decides it: a turn quoting our sentence but
    # naming no square from the cause does NOT count.
    wrong_square = "The check that was skipped: your rook on h8 is loose."
    assert not mod._voices_the_cause(wrong_square, squares)


def test_a_turn_that_never_mentions_the_cause_square_is_a_miss() -> None:
    mod = _load()
    squares = mod._cause_squares(_PROMPT)
    assert squares is not None
    assert not mod._voices_the_cause("A stronger move was Nf3, developing a piece.", squares)


def test_given_and_voiced_are_reported_separately() -> None:
    """One number conflated composition with delivery and reported neither.

    Measured: ~70% given, 90-100% voiced. Collapsed into one figure that reads as ~65% and
    hides that the gap is ours, not the model's.
    """
    mod = _load()
    m = mod.Metrics(name="t", spoken=10, cause_given=7, cause_anchorable=6, cause_voiced=6)
    assert m.cause_given_rate == 70.0
    assert m.cause_voiced_rate == 100.0
    # Voiced is a share of ANCHORABLE, not of spoken: unscorable causes must not dilute it.
    assert mod.Metrics(name="t", spoken=10, cause_given=7, cause_anchorable=0).cause_voiced_rate == 0.0
