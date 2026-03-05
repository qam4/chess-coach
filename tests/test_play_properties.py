"""Property-based tests for move classification consistency.

Feature: chess-coaching-mvp, Property 4: Move classification consistency

**Validates: Requirements 8.5**

For any eval_before and eval_after integers in range [-3000, 3000],
the classification is deterministic and matches the threshold rules:
- good: eval drop <= 30 cp
- inaccuracy: eval drop 31-100 cp
- blunder: eval drop > 100 cp
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from chess_coach.coach import Coach


@settings(max_examples=200)
@given(
    eval_before=st.integers(min_value=-3000, max_value=3000),
    eval_after=st.integers(min_value=-3000, max_value=3000),
)
def test_classification_matches_thresholds(
    eval_before: int,
    eval_after: int,
) -> None:
    """Classification is deterministic and matches threshold rules.

    **Validates: Requirements 8.5**

    For any pair of eval values, the eval drop (clamped to >= 0)
    determines the classification:
    - good: drop <= 30
    - inaccuracy: 31 <= drop <= 100
    - blunder: drop > 100
    """
    eval_drop = max(0, eval_before - eval_after)
    classification = Coach.classify_move(eval_drop)

    if eval_drop <= 30:
        assert classification == "good", (
            f"drop={eval_drop} should be 'good', got '{classification}'"
        )
    elif eval_drop <= 100:
        assert classification == "inaccuracy", (
            f"drop={eval_drop} should be 'inaccuracy', got '{classification}'"
        )
    else:
        assert classification == "blunder", (
            f"drop={eval_drop} should be 'blunder', got '{classification}'"
        )


@settings(max_examples=200)
@given(
    eval_before=st.integers(min_value=-3000, max_value=3000),
    eval_after=st.integers(min_value=-3000, max_value=3000),
)
def test_classification_is_deterministic(
    eval_before: int,
    eval_after: int,
) -> None:
    """Calling classify_move twice with the same input gives the same result.

    **Validates: Requirements 8.5**
    """
    eval_drop = max(0, eval_before - eval_after)
    result1 = Coach.classify_move(eval_drop)
    result2 = Coach.classify_move(eval_drop)
    assert result1 == result2


@settings(max_examples=200)
@given(
    eval_before=st.integers(min_value=-3000, max_value=3000),
    eval_after=st.integers(min_value=-3000, max_value=3000),
)
def test_classification_is_one_of_three_values(
    eval_before: int,
    eval_after: int,
) -> None:
    """Classification always returns one of the three valid strings.

    **Validates: Requirements 8.5**
    """
    eval_drop = max(0, eval_before - eval_after)
    classification = Coach.classify_move(eval_drop)
    assert classification in {"good", "inaccuracy", "blunder"}


@settings(max_examples=200)
@given(
    eval_drop=st.integers(min_value=0, max_value=6000),
)
def test_classification_monotonic(eval_drop: int) -> None:
    """Worse drops never produce a better classification.

    **Validates: Requirements 8.5**

    If drop_a < drop_b, then classify(drop_a) should be at least
    as good as classify(drop_b) (good > inaccuracy > blunder).
    """
    severity = {"good": 0, "inaccuracy": 1, "blunder": 2}
    c = Coach.classify_move(eval_drop)
    # A slightly larger drop should be at least as severe
    c_plus = Coach.classify_move(eval_drop + 1)
    assert severity[c] <= severity[c_plus], (
        f"classify({eval_drop})={c} but classify({eval_drop + 1})={c_plus}"
    )
