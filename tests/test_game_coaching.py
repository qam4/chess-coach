"""Tests for the game-coaching eval pure core (eval/game_coaching.py).

The loop, trajectory model, and aggregation are driven by injected fakes —
no live engine, LLM, or judge — so they run fast and deterministically.
"""

from __future__ import annotations

import chess
from hypothesis import given
from hypothesis import strategies as st

from chess_coach.eval.game_coaching import (
    GameReport,
    GameTrajectory,
    TurnRecord,
    aggregate,
    play_game,
)

START = chess.STARTING_FEN


def _turn(ply: int, fen: str, move: str, *, feedback: str = "ok", fidelity: dict[str, int] | None = None) -> TurnRecord:
    return TurnRecord(
        ply=ply,
        fen_before=fen,
        student_move=move,
        engine_best=move,
        eval_before_cp=0,
        eval_after_cp=0,
        eval_drop_cp=0,
        classification="good",
        active_features=["phase:opening"],
        coach_feedback=feedback,
        fidelity_kinds=fidelity or {},
    )


def _scripted_move_fn(moves: list[str]):
    """A player that plays a fixed move list in order (UCI)."""
    seq = iter(moves)

    def move_fn(fen: str, elo: int) -> str:
        return next(seq)

    return move_fn


# --------------------------------------------------------------- loop


def test_play_game_one_turn_per_student_move_in_ply_order() -> None:
    # 1.e4 e5 2.Nf3 Nc6 — student is White, so plies 0 and 2 are coached.
    moves = ["e2e4", "e7e5", "g1f3", "b8c6"]
    coached: list[int] = []

    def coach_fn(ply: int, fen: str, move: str) -> TurnRecord:
        coached.append(ply)
        return _turn(ply, fen, move)

    traj = play_game(
        start_fen=START,
        student_elo=1350,
        opponent_elo=1350,
        student_is_white=True,
        ply_cap=4,
        move_fn=_scripted_move_fn(moves),
        coach_fn=coach_fn,
    )
    assert coached == [0, 2]  # only White's moves, in order
    assert [t.ply for t in traj.turns] == [0, 2]
    assert traj.result == "ply-cap"


def test_play_game_coaches_black_when_student_is_black() -> None:
    moves = ["e2e4", "e7e5", "g1f3", "b8c6"]

    def coach_fn(ply: int, fen: str, move: str) -> TurnRecord:
        return _turn(ply, fen, move)

    traj = play_game(
        start_fen=START,
        student_elo=1350,
        opponent_elo=1800,
        student_is_white=False,
        ply_cap=4,
        move_fn=_scripted_move_fn(moves),
        coach_fn=coach_fn,
    )
    assert [t.ply for t in traj.turns] == [1, 3]  # only Black's moves


def test_play_game_natural_termination_scholars_mate() -> None:
    # 1.e4 e5 2.Bc4 Nc6 3.Qh5 Nf6?? 4.Qxf7# — checkmate ends before ply cap.
    moves = ["e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6", "h5f7"]

    def coach_fn(ply: int, fen: str, move: str) -> TurnRecord:
        return _turn(ply, fen, move)

    traj = play_game(
        start_fen=START,
        student_elo=1350,
        opponent_elo=1350,
        student_is_white=True,
        ply_cap=50,
        move_fn=_scripted_move_fn(moves),
        coach_fn=coach_fn,
    )
    assert traj.result == "1-0"  # White (student) mates


def test_play_game_illegal_player_move_ends_with_error() -> None:
    def bad_move_fn(fen: str, elo: int) -> str:
        return "e2e5"  # illegal in the start position

    def coach_fn(ply: int, fen: str, move: str) -> TurnRecord:
        raise AssertionError("coach should not be called on an illegal move")

    traj = play_game(
        start_fen=START,
        student_elo=1350,
        opponent_elo=1350,
        student_is_white=True,
        ply_cap=4,
        move_fn=bad_move_fn,
        coach_fn=coach_fn,
    )
    assert traj.result == "error"
    assert traj.turns == []
    assert any("illegal move" in i for i in traj.issues)


def test_play_game_invalid_start_fen() -> None:
    traj = play_game(
        start_fen="not a fen",
        student_elo=1350,
        opponent_elo=1350,
        student_is_white=True,
        ply_cap=4,
        move_fn=_scripted_move_fn([]),
        coach_fn=lambda p, f, m: _turn(p, f, m),
    )
    assert traj.result == "error"
    assert any("invalid start FEN" in i for i in traj.issues)


def test_play_game_flags_empty_feedback_only_when_move_deserved_comment() -> None:
    def coach_fn(ply: int, fen: str, move: str) -> TurnRecord:
        # Empty feedback on a blunder is a real problem to surface.
        t = _turn(ply, fen, move, feedback="   ")
        return TurnRecord(**{**t.to_dict(), "classification": "blunder"})

    traj = play_game(
        start_fen=START,
        student_elo=1350,
        opponent_elo=1350,
        student_is_white=True,
        ply_cap=2,
        move_fn=_scripted_move_fn(["e2e4", "e7e5"]),
        coach_fn=coach_fn,
    )
    assert any("empty coach feedback" in i for i in traj.issues)


# --------------------------------------------------------------- round-trip


def test_trajectory_round_trip() -> None:
    traj = GameTrajectory(
        meta={"student_elo": 1350, "seed": 7},
        turns=[
            _turn(0, START, "e2e4", fidelity={"off_menu": 1}),
            _turn(2, START, "g1f3"),
        ],
        result="ply-cap",
        issues=["something"],
    )
    assert GameTrajectory.from_dict(traj.to_dict()) == traj


@st.composite
def _trajectories(draw: st.DrawFn) -> GameTrajectory:
    n = draw(st.integers(min_value=0, max_value=6))
    turns = [
        _turn(
            2 * i,
            START,
            "e2e4",
            feedback=draw(st.sampled_from(["ok", "", "  "])),
            fidelity=draw(st.sampled_from([{}, {"off_menu": 1}, {"illegal_move": 2}])),
        )
        for i in range(n)
    ]
    return GameTrajectory(meta={"seed": draw(st.integers())}, turns=turns, result="ply-cap")


@given(_trajectories())
def test_property_trajectory_round_trip(traj: GameTrajectory) -> None:
    assert GameTrajectory.from_dict(traj.to_dict()) == traj


# --------------------------------------------------------------- aggregate


def test_aggregate_mean_quality_over_judged_only() -> None:
    traj = GameTrajectory(
        meta={},
        turns=[
            _turn(0, START, "e2e4"),
            _turn(2, START, "g1f3"),
            _turn(4, START, "b1c3"),
        ],
        result="ply-cap",
    )
    # Only plies 0 and 4 were judged.
    report = aggregate(traj, verdicts={0: 0.8, 4: 0.4})
    assert report.judged_n == 2
    assert report.unjudged_n == 1
    assert report.mean_quality == 0.6
    assert report.classification_counts == {"good": 3}


def test_aggregate_no_judge_is_none() -> None:
    traj = GameTrajectory(meta={}, turns=[_turn(0, START, "e2e4")], result="ply-cap")
    report = aggregate(traj)
    assert report.mean_quality is None
    assert report.judged_n == 0


def test_aggregate_surfaces_fidelity_and_empty_issues() -> None:
    empty_blunder = TurnRecord(**{**_turn(2, START, "g1f3", feedback="").to_dict(), "classification": "blunder"})
    traj = GameTrajectory(
        meta={},
        turns=[
            _turn(0, START, "e2e4", fidelity={"off_menu": 1}),
            empty_blunder,
        ],
        result="ply-cap",
        issues=["game-level thing"],
    )
    report = aggregate(traj)
    assert "game-level thing" in report.issues
    assert any("off_menu" in i for i in report.issues)
    assert any("empty coach feedback" in i for i in report.issues)
    assert report.mean_fidelity_violations == 0.5  # 1 violation over 2 turns


def test_aggregate_does_not_flag_empty_feedback_on_good_move() -> None:
    # The coach legitimately stays silent on good moves — not an issue.
    traj = GameTrajectory(meta={}, turns=[_turn(0, START, "e2e4", feedback="")], result="ply-cap")
    report = aggregate(traj)
    assert not any("empty coach feedback" in i for i in report.issues)


def test_student_moves_extracts_ply_fen_move() -> None:
    from chess_coach.eval.game_coaching import student_moves

    traj = GameTrajectory(
        meta={},
        turns=[_turn(0, START, "e2e4"), _turn(2, "somefen", "g1f3")],
        result="ply-cap",
    )
    assert student_moves(traj) == [(0, START, "e2e4"), (2, "somefen", "g1f3")]


def test_game_report_render_smoke() -> None:
    report = GameReport(
        result="1-0",
        n_turns=3,
        judged_n=2,
        unjudged_n=1,
        mean_quality=0.6,
        classification_counts={"good": 2, "blunder": 1},
        mean_fidelity_violations=0.33,
        issues=["ply 4: coach named 1 off_menu move(s)"],
    )
    text = report.render()
    assert "Game result: 1-0" in text
    assert "0.60" in text
    assert "off_menu" in text
