"""Tests for the move-feedback benchmark loader."""

from __future__ import annotations

import pytest

from chess_coach.eval.move_feedback import (
    MoveFeedbackError,
    default_move_feedback_path,
    load_move_feedback_scenarios,
)

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def _write(tmp_path, text):
    p = tmp_path / "mf.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_loads_real_benchmark_and_moves_are_legal() -> None:
    scenarios = load_move_feedback_scenarios(default_move_feedback_path())
    assert len(scenarios) >= 4
    assert len({s.id for s in scenarios}) == len(scenarios)  # unique ids
    # The loader already enforces legality; assert a couple of known fields.
    by_id = {s.id for s in scenarios}
    assert "opening_e4_sound" in by_id
    assert all(s.level for s in scenarios)


def test_valid_minimal(tmp_path) -> None:
    p = _write(tmp_path, f'scenarios:\n  - id: a\n    fen: "{START}"\n    move: e2e4\n    level: beginner\n')
    s = load_move_feedback_scenarios(p)
    assert len(s) == 1
    assert s[0].id == "a" and s[0].move == "e2e4" and s[0].level == "beginner"


def test_illegal_move_rejected(tmp_path) -> None:
    # e2e5 is not a legal first move.
    p = _write(tmp_path, f'scenarios:\n  - id: a\n    fen: "{START}"\n    move: e2e5\n    level: beginner\n')
    with pytest.raises(MoveFeedbackError, match="illegal"):
        load_move_feedback_scenarios(p)


def test_invalid_fen_rejected(tmp_path) -> None:
    p = _write(tmp_path, 'scenarios:\n  - id: a\n    fen: "not-a-fen"\n    move: e2e4\n    level: beginner\n')
    with pytest.raises(MoveFeedbackError, match="invalid FEN"):
        load_move_feedback_scenarios(p)


def test_missing_field_rejected(tmp_path) -> None:
    p = _write(tmp_path, f'scenarios:\n  - id: a\n    fen: "{START}"\n    level: beginner\n')
    with pytest.raises(MoveFeedbackError, match="missing required 'move'"):
        load_move_feedback_scenarios(p)


def test_duplicate_id_rejected(tmp_path) -> None:
    body = (
        f'scenarios:\n  - id: a\n    fen: "{START}"\n    move: e2e4\n    level: beginner\n'
        f'  - id: a\n    fen: "{START}"\n    move: d2d4\n    level: beginner\n'
    )
    with pytest.raises(MoveFeedbackError, match="duplicate"):
        load_move_feedback_scenarios(_write(tmp_path, body))


def test_no_scenarios_rejected(tmp_path) -> None:
    with pytest.raises(MoveFeedbackError, match="no scenarios|scenarios"):
        load_move_feedback_scenarios(_write(tmp_path, "scenarios: []\n"))


# --------------------------------------------------- move-feedback pairwise


def _comparison_report():
    from chess_coach.models import ComparisonReport

    return ComparisonReport(
        fen=START,
        user_move="f7f6",
        user_eval_cp=-40,
        best_move="e2e4",
        best_eval_cp=10,
        eval_drop_cp=50,
        classification="inaccuracy",
        nag="?!",
        best_move_idea="contest the center",
        refutation_line=None,
        missed_tactics=[],
        top_lines=[],
        critical_moment=False,
        critical_reason=None,
    )


class _StubJudge:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def generate(self, prompt: str, max_tokens: int = 400, temperature: float = 0.0) -> str:
        self.prompts.append(prompt)
        return self.reply


def test_move_pairwise_prompt_has_move_context() -> None:
    from chess_coach.eval import build_move_feedback_pairwise_prompt

    p = build_move_feedback_pairwise_prompt("Resp A", "Resp B", _comparison_report(), "beginner")
    assert "f7f6" in p  # the student's move
    assert "e2e4" in p  # the engine best move
    assert "inaccuracy" in p  # the engine verdict
    assert "Response 1" in p and "Response 2" in p


def test_move_pairwise_compare_maps_winner() -> None:
    import random

    from chess_coach.eval import pairwise_compare_move

    judge = _StubJudge('{"winner": "1", "reason": "clearer correction"}')
    res = pairwise_compare_move(
        judge, "off", "feedback-off", "on", "feedback-on", _comparison_report(), "beginner", rng=random.Random(0)
    )
    assert res.winner in ("off", "on")
    assert res.first_shown in ("off", "on")
    assert len(judge.prompts) == 1


def test_move_pairwise_compare_tie() -> None:
    import random

    from chess_coach.eval import pairwise_compare_move

    judge = _StubJudge('{"winner": "tie", "reason": "equal"}')
    res = pairwise_compare_move(judge, "off", "x", "on", "y", _comparison_report(), "beginner", rng=random.Random(1))
    assert res.winner == "tie"
