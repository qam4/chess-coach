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


def test_voicing_the_cue_is_anchored_on_squares_not_wording() -> None:
    """Same contract as the cause: paraphrase counts, echoing our sentence is not required."""
    mod = _load()
    cue = mod._cue_squares(_CUE_PROMPT_NEW)
    assert mod._voices_the_cause("Your bishop on b4 was there for the taking.", cue)
    assert mod._voices_the_cause("Bxb4 was on.", cue), "loose matching must see the square in SAN"
    assert not mod._voices_the_cause("Think about your development and the centre.", cue)


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


def test_the_theme_is_voiced_by_file_as_well_as_by_square() -> None:
    """The model answers in the vocabulary the theme used, and that vocabulary is often a file.

    Handed "your a-file pawn is passed" the coach writes "the passed pawn on the a-file", with
    no square in the sentence. Square-only matching scored two such turns as unexplained and
    made the theme look like a 1-turn problem when it accounts for 4 of the 5 turns B-012 lost.
    """
    mod = _load()
    squares = mod._theme_squares(_THEME_PROMPT)
    files = mod._theme_files(_THEME_PROMPT)
    assert files == {"a"}
    assert "a5" in squares, "a file expands to its squares so it can be compared with a cue"

    by_file = "You missed the chance to push your passed pawn on the a-file."
    assert not mod._voices_the_cause(by_file, squares), "no square appears, so square matching misses it"
    assert mod._voices_the_theme(by_file, squares, files), "but the theme WAS voiced, by file"

    by_square = "Push the pawn to a5."
    assert mod._voices_the_theme(by_square, squares, files)

    assert not mod._voices_the_theme("Your king is doing nothing useful.", squares, files)


def test_theme_competition_is_keyed_on_the_cue_not_the_cause() -> None:
    """Keyed to the cause, this counter reported 1 displaced turn where the truth was 4.

    A turn can keep the CAUSE and still lose the CUE — the cue is the wider set, including the
    achievement clause, and it is what B-012's criterion is about. Anchoring the competition
    check to the narrower set silently excluded the turns that had no composed cause at all.
    """
    mod = _load()
    turns = [
        {
            "ply": 87,
            "fen_before": "8/6p1/8/8/5K2/8/P7/7k w - - 0 1",
            "student_move_san": "Kf4",
            "best_move_san": "a4",
            "classification": "mistake",
            "eval_drop_cp": 120,
            "coach_feedback": "You missed the chance to push your passed pawn on the a-file.",
            "prompt": _THEME_PROMPT,
            "latency_s": 1.0,
            "fidelity_kinds": {},
        }
    ]
    m = mod.measure_turns("probe", turns) if hasattr(mod, "measure_turns") else None
    if m is None:  # measure() reads a file; exercise the pieces directly instead
        cue = mod._cue_squares(_THEME_PROMPT)
        theme_sq = mod._theme_squares(_THEME_PROMPT)
        theme_f = mod._theme_files(_THEME_PROMPT)
        text = turns[0]["coach_feedback"]
        assert cue == {"g7"}
        assert theme_sq and not (theme_sq & cue), "the theme points away from the cue"
        assert not mod._voices_the_cause(text, cue), "the cue was not voiced"
        assert mod._voices_the_theme(text, theme_sq, theme_f), "the theme was"
