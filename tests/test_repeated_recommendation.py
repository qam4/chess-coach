"""A recommendation the student has already ignored gets less room, not the same.

The achievement clause has flagged the recurrence since v37 and it changed nothing about length:
over 673 repeat turns the median repeat is 0.97x the first telling, and on the sharpest streak
(Nxc7+ recommended four turns running) it went 47 words to 75, 74, 81.

What must NOT happen is the facts being withheld. `_achievement_line`'s docstring records what that
costs: when the reason was retired the model invented three replacements. So these tests assert the
budget shrinks AND the clause and move name survive.
"""

from __future__ import annotations

import re

from chess_coach.models import ComparisonReport
from chess_coach.prompts import (
    ACHIEVEMENT_REFRAME_AFTER,
    build_rich_move_evaluation_prompt,
)

# A real blunder position: White has just played Rb1 instead of Nxc7+, which forks the king on e8
# and the undefended rook on a8. From v55 seed 23 ply 19.
FEN = "r1b1k1nr/1ppp1pp1/2n1p3/pN4Bp/2QPP3/8/PP3PPP/2RK1BNR w k - 2 12"


def _report() -> ComparisonReport:
    return ComparisonReport(
        fen=FEN,
        user_move="c1b1",
        user_eval_cp=0,
        best_move="b5c7",
        best_eval_cp=583,
        eval_drop_cp=583,
        classification="blunder",
        nag="??",
        best_move_idea="material gain — winning capture",
        refutation_line=None,
        missed_tactics=[],
        top_lines=[],
        critical_moment=False,
        critical_reason=None,
    )


def _word_limit(prompt: str) -> int:
    m = re.search(r"under (\d+) words", prompt)
    assert m, "the prompt must state a word limit"
    return int(m.group(1))


def test_a_repeated_recommendation_gets_a_smaller_budget() -> None:
    first = build_rich_move_evaluation_prompt(_report(), achievement_times_shown=0)
    repeat = build_rich_move_evaluation_prompt(_report(), achievement_times_shown=ACHIEVEMENT_REFRAME_AFTER)
    assert _word_limit(repeat) < _word_limit(first), (
        f"repeat budget {_word_limit(repeat)} is not below the first telling's {_word_limit(first)}"
    )


def test_the_repeat_instruction_appears_only_on_a_repeat() -> None:
    marker = "ALREADY RECOMMENDED THIS MOVE"
    assert marker not in build_rich_move_evaluation_prompt(_report(), achievement_times_shown=0)
    assert marker in build_rich_move_evaluation_prompt(_report(), achievement_times_shown=ACHIEVEMENT_REFRAME_AFTER)


def test_the_move_and_its_reason_survive_the_shortening() -> None:
    """The guardrail, in prompt form. Withholding the fact is what produced invention before."""
    repeat = build_rich_move_evaluation_prompt(_report(), achievement_times_shown=ACHIEVEMENT_REFRAME_AFTER)
    assert "Nxc7+" in repeat, "the move must still be named"
    assert "does the same thing here as it did earlier" in repeat, "the achievement clause must still be stated"
    assert "c7" in repeat, "the composed reason must still name its square"


def test_the_budget_never_falls_below_the_floor() -> None:
    """A tight tier must not be squeezed to nothing — the turn still needs move, reason and hook."""
    repeat = build_rich_move_evaluation_prompt(_report(), achievement_times_shown=ACHIEVEMENT_REFRAME_AFTER)
    assert _word_limit(repeat) >= 35
