"""Tests for Layer 1 objective checks (Task 2).

Covers the property-based guarantees (P1 hallucination penalty, P2
no-LLM) plus the eval-direction and coverage logic and the moved
hallucination/illegal-move checkers.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from chess_coach.eval.benchmark import BenchmarkPosition, GroundTruthPoint
from chess_coach.eval.objective import (
    PASS_THRESHOLD,
    ObjectiveResult,
    check_coverage,
    check_eval_direction,
    check_move_validity,
    check_piece_hallucinations,
    evaluate_objective,
)
from chess_coach.models import (
    EvalBreakdown,
    KingSafety,
    PawnFeatures,
    PositionReport,
)

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


# --------------------------------------------------------------- report helper


def _mk_report(fen: str = START_FEN, eval_cp: int = 0) -> PositionReport:
    """Minimal PositionReport for objective checks (only fen + eval_cp
    matter to Layer 1)."""
    eb = EvalBreakdown(material=0, mobility=0, king_safety=0, pawn_structure=0)
    empty_side = {"white": [], "black": []}
    pawns = {
        "white": PawnFeatures([], [], []),
        "black": PawnFeatures([], [], []),
    }
    ks = {
        "white": KingSafety(0, ""),
        "black": KingSafety(0, ""),
    }
    return PositionReport(
        fen=fen,
        eval_cp=eval_cp,
        eval_breakdown=eb,
        hanging_pieces=dict(empty_side),
        threats=dict(empty_side),
        pawn_structure=pawns,
        king_safety=ks,
        top_lines=[],
        tactics=[],
        threat_map=[],
        threat_map_summary=None,
        critical_moment=False,
        critical_reason=None,
    )


def _pos(points: list[GroundTruthPoint], fen: str = START_FEN) -> BenchmarkPosition:
    return BenchmarkPosition(id="t", fen=fen, level="beginner", phase="opening", points=tuple(points))


# --------------------------------------------------------------- hallucination


def test_hallucination_detected_on_empty_square() -> None:
    # Start position: e4 is empty.
    issues = check_piece_hallucinations(START_FEN, "Your knight on e4 is strong.")
    assert len(issues) == 1
    assert "e4" in issues[0]


def test_hallucination_skips_influence_verbs() -> None:
    # "controlling e4" is not a placement claim.
    assert check_piece_hallucinations(START_FEN, "The knight controlling e4 is nice.") == []


def test_hallucination_none_when_correct() -> None:
    # e2 has a white pawn in the start position.
    assert check_piece_hallucinations(START_FEN, "The pawn on e2 can advance.") == []


# --------------------------------------------------------------- legality


def test_illegal_move_flagged() -> None:
    # Bxf7 is illegal in the start position (bishop is blocked) and is
    # unmistakably move notation (piece + capture) -> flagged.
    issues = check_move_validity(START_FEN, "White should try Bxf7 immediately.")
    assert any("Bxf7" in i for i in issues)


def test_legal_move_not_flagged() -> None:
    assert check_move_validity(START_FEN, "White can open with e4 or d4.") == []


def test_bare_pawn_square_reference_not_flagged() -> None:
    # "e5" reads as a square reference, not a move — must NOT be flagged
    # even though e5 is not a legal first move. Avoids false positives.
    assert check_move_validity(START_FEN, "The e5 square is an outpost.") == []


# --------------------------------------------------------------- eval direction


def test_eval_direction_match_white() -> None:
    report = _mk_report(eval_cp=200)  # white clearly better
    assert check_eval_direction("White has a clear advantage here.", report) is True


def test_eval_direction_backwards_is_false() -> None:
    report = _mk_report(eval_cp=200)  # engine: white better
    # Response claims black better -> backwards -> contradiction.
    assert check_eval_direction("Black is winning this position.", report) is False


def test_eval_direction_no_claim_is_none() -> None:
    report = _mk_report(eval_cp=200)
    assert check_eval_direction("Develop your pieces and castle.", report) is None


def test_eval_direction_near_equal_mismatch_is_none() -> None:
    # Engine ~equal (within threshold); response says white slightly
    # better. Not a backwards winner -> None (judgment call, not error).
    report = _mk_report(eval_cp=20)
    assert check_eval_direction("White is a touch better.", report) is None


def test_eval_direction_equal_match() -> None:
    report = _mk_report(eval_cp=10)
    assert check_eval_direction("The position is roughly equal.", report) is True


# --------------------------------------------------------------- coverage


def test_coverage_hanging_piece_hit() -> None:
    pos = _pos([GroundTruthPoint("hanging_piece", "e4")])
    hits, total = check_coverage("Your knight on e4 hangs.", pos)
    assert total == 1
    assert hits == ["hanging_piece:e4"]


def test_coverage_miss() -> None:
    pos = _pos([GroundTruthPoint("hanging_piece", "e4")])
    hits, total = check_coverage("Develop your pieces.", pos)
    assert total == 1
    assert hits == []


def test_coverage_phase_points_excluded() -> None:
    pos = _pos(
        [
            GroundTruthPoint("phase", "endgame"),
            GroundTruthPoint("free", "king"),
        ]
    )
    hits, total = check_coverage("Activate your king.", pos)
    # phase doesn't count; only the free 'king' point does.
    assert total == 1
    assert hits == ["free:king"]


def test_coverage_empty_points_is_total_zero() -> None:
    pos = _pos([])
    hits, total = check_coverage("anything", pos)
    assert (hits, total) == ([], 0)


def test_coverage_optional_points_not_counted() -> None:
    pos = _pos(
        [
            GroundTruthPoint("free", "center", required=True),
            GroundTruthPoint("free", "tempo", required=False),
        ]
    )
    _hits, total = check_coverage("Fight for the center.", pos)
    assert total == 1  # only the required one


# --------------------------------------------------------------- factual score


def test_full_coverage_no_errors_scores_one() -> None:
    pos = _pos([GroundTruthPoint("free", "center")])
    report = _mk_report()
    r = evaluate_objective("Fight for the center early.", report, pos)
    assert r.factual_score == 1.0
    assert r.passed


# P1: a hallucination caps the score below pass AND strictly lowers it
# vs the same response without the hallucination.
def test_hallucination_caps_and_lowers_score() -> None:
    pos = _pos([GroundTruthPoint("free", "center")])
    report = _mk_report()
    clean = "Fight for the center early."
    dirty = "Fight for the center early. Your bishop on e4 is strong."

    r_clean = evaluate_objective(clean, report, pos)
    r_dirty = evaluate_objective(dirty, report, pos)

    assert r_dirty.hallucinations  # detected
    assert r_dirty.factual_score < PASS_THRESHOLD  # capped below pass
    assert r_dirty.factual_score < r_clean.factual_score  # strictly lower


def test_backwards_direction_penalized() -> None:
    pos = _pos([GroundTruthPoint("free", "center")])
    report = _mk_report(eval_cp=300)  # white winning
    r = evaluate_objective("Fight for the center. Black is clearly winning.", report, pos)
    assert r.eval_direction_ok is False
    assert r.factual_score < PASS_THRESHOLD


def test_multiple_errors_compound() -> None:
    pos = _pos([GroundTruthPoint("free", "center")])
    report = _mk_report()
    one = evaluate_objective("Center. Your rook on e4 is great.", report, pos)
    two = evaluate_objective("Center. Your rook on e4 and queen on d4 are great.", report, pos)
    assert len(two.hallucinations) > len(one.hallucinations)
    assert two.factual_score < one.factual_score


# P2: objective layer needs no LLM provider — this whole module imports
# nothing from chess_coach.llm.
def test_objective_imports_no_llm() -> None:
    import chess_coach.eval.objective as obj

    src = obj.__file__
    text = open(src, encoding="utf-8").read()
    assert "chess_coach.llm" not in text
    assert "import httpx" not in text


def test_objective_runs_without_provider() -> None:
    # Pure function call, no network / provider involved.
    pos = _pos([GroundTruthPoint("free", "develop")])
    report = _mk_report()
    r = evaluate_objective("Develop knights before bishops.", report, pos)
    assert isinstance(r, ObjectiveResult)


# --------------------------------------------------------------- property: score bounds


@given(st.integers(min_value=0, max_value=5), st.integers(min_value=0, max_value=5))
def test_factual_score_in_unit_interval(n_hits: int, n_total_extra: int) -> None:
    """Score is always within [0, 1] regardless of coverage shape."""
    total = n_hits + n_total_extra
    points = [GroundTruthPoint("free", f"kw{i}") for i in range(total)]
    pos = _pos(points)
    report = _mk_report()
    # Build a response that references the first n_hits keywords.
    response = " ".join(f"kw{i}" for i in range(n_hits))
    r = evaluate_objective(response or "nothing", report, pos)
    assert 0.0 <= r.factual_score <= 1.0
