"""Tests for the coach report-card pure core (eval/coach_review.py)."""

from __future__ import annotations

from chess_coach.eval.coach_review import (
    PHASE_ENDGAME,
    PHASE_MIDDLEGAME,
    PHASE_OPENING,
    ReviewTurn,
    aggregate_review,
    build_coach_review_prompt,
)


def _turn(
    ply: int,
    phase: str,
    *,
    played: str = "Nf3",
    best: str = "Nf3",
    classification: str = "good",
    drop: int = 0,
    feedback: str = "Good developing move.",
    latency: float = 10.0,
    fidelity: dict[str, int] | None = None,
) -> ReviewTurn:
    return ReviewTurn(
        ply=ply,
        phase=phase,
        fen_before="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        student_move_san=played,
        best_move_san=best,
        classification=classification,
        eval_drop_cp=drop,
        coach_feedback=feedback,
        latency_s=latency,
        fidelity_kinds=fidelity or {},
    )


def test_aggregate_counts_and_latency() -> None:
    turns = [
        _turn(0, PHASE_OPENING, latency=5.0),
        _turn(2, PHASE_OPENING, classification="inaccuracy", drop=40, latency=15.0, fidelity={"off_menu": 1}),
        _turn(4, PHASE_MIDDLEGAME, classification="blunder", drop=300, latency=25.0, feedback="  "),
        _turn(6, PHASE_ENDGAME, latency=55.0, fidelity={"off_menu": 1, "placement": 2}),
    ]
    stats = aggregate_review(turns)
    assert stats.n_turns == 4
    assert stats.phase_counts == {PHASE_OPENING: 2, PHASE_MIDDLEGAME: 1, PHASE_ENDGAME: 1}
    assert stats.classification_counts == {"good": 2, "inaccuracy": 1, "blunder": 1}
    assert stats.fidelity_totals == {"off_menu": 2, "placement": 2}
    assert stats.empty_feedback == 1  # the "  " feedback
    assert stats.latency_mean_s == 25.0  # (5+15+25+55)/4
    assert stats.latency_max_s == 55.0
    assert stats.latency_mean_s <= stats.latency_p90_s <= stats.latency_max_s


def test_aggregate_empty_is_safe() -> None:
    stats = aggregate_review([])
    assert stats.n_turns == 0
    assert stats.latency_mean_s == 0.0 and stats.latency_max_s == 0.0
    assert stats.phase_counts == {}


def test_review_prompt_contains_standard_stats_and_transcript() -> None:
    turns = [
        _turn(0, PHASE_OPENING, played="e4", best="e4", feedback="Great central move."),
        _turn(3, PHASE_MIDDLEGAME, played="Qh5", best="Nc3", classification="mistake", drop=120, feedback="Too early."),
    ]
    stats = aggregate_review(turns)
    prompt = build_coach_review_prompt(turns, stats)
    # Standard + task
    assert "BRIDGE" in prompt
    assert "SCORE: X/10" in prompt
    assert "PHASE FIT" in prompt
    # Stats surfaced
    assert "Generation latency" in prompt
    # Transcript: the best-move-equals-played case is called out; the other names the engine best.
    assert "this IS the engine's top move" in prompt  # e4 == best
    assert "engine best: Nc3" in prompt
    assert "Great central move." in prompt
    assert "Too early." in prompt
