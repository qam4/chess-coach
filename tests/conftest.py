"""Shared fixtures for chess-coach tests."""

from collections.abc import Callable
from typing import Any

import pytest

#: The v33 shape: a best move that attacks an under-defended piece. This is what makes
#: `_best_move_achievement` compose a clause instead of returning nothing, so it is the
#: only comparison fixture we have that reaches the achievement line.
#:
#: `test_coach` keeps its own copy of this report because the tests directory is not on
#: `sys.path` — a sibling module in `tests/` is not importable, and conftest is only
#: reachable through the fixture mechanism below. Collapsing the two copies needs
#: `pythonpath` to include `tests`, which is a config change, so it is a backlog line
#: rather than part of B-012.
REPEAT_FEN = "r1b1k1r1/pppp1p1p/8/4p1P1/1b1B4/1P2P3/P1P1B1nP/RN1K3R w q - 0 16"


def comparison_with_repeatable_lesson(drop: int = 200) -> Any:
    """A comparison whose best move (``Bc3``) attacks Black's undefended bishop on b4."""
    from chess_coach.models import ComparisonReport, PVLine

    return ComparisonReport(
        fen=REPEAT_FEN,
        user_move="e2c4",
        user_eval_cp=0,
        best_move="d4c3",
        best_eval_cp=0,
        eval_drop_cp=drop,
        classification="mistake",
        nag="?",
        best_move_idea="piece activity — improving piece placement",
        refutation_line=None,
        missed_tactics=[],
        top_lines=[PVLine(depth=8, eval_cp=0, moves=["d4c3"], theme="king attack")],
        critical_moment=False,
        critical_reason=None,
    )


@pytest.fixture
def repeatable_lesson_comparison() -> Callable[[int], Any]:
    """`comparison_with_repeatable_lesson`, injected.

    B-012's prompt check needs a comparison that reaches the achievement line; the
    synthetic report in `test_no_magnitude_leak` does not, and on its own it would let a
    withhold look complete while "The best move (Bc3) does this" still carried the token.
    """
    return comparison_with_repeatable_lesson
