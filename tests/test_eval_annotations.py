"""Tests for the benchmark annotation guard (Task 9)."""

from __future__ import annotations

from chess_coach.eval.annotations import check_position_annotations
from chess_coach.eval.benchmark import BenchmarkPosition, GroundTruthPoint
from chess_coach.models import (
    EvalBreakdown,
    HangingPiece,
    KingSafety,
    PawnFeatures,
    PositionReport,
    TacticalMotif,
)

FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def _report(
    eval_cp: int = 0,
    hanging: list[HangingPiece] | None = None,
    tactics: list[TacticalMotif] | None = None,
) -> PositionReport:
    return PositionReport(
        fen=FEN,
        eval_cp=eval_cp,
        eval_breakdown=EvalBreakdown(0, 0, 0, 0),
        hanging_pieces={"white": [], "black": hanging or []},
        threats={"white": [], "black": []},
        pawn_structure={"white": PawnFeatures([], [], []), "black": PawnFeatures([], [], [])},
        king_safety={"white": KingSafety(0, ""), "black": KingSafety(0, "")},
        top_lines=[],
        tactics=tactics or [],
        threat_map=[],
        threat_map_summary=None,
        critical_moment=False,
        critical_reason=None,
    )


def _pos(*points: GroundTruthPoint) -> BenchmarkPosition:
    return BenchmarkPosition(id="t", fen=FEN, level="beginner", phase="opening", points=tuple(points))


def test_matching_eval_direction_passes() -> None:
    pos = _pos(GroundTruthPoint("eval_direction", "white_better"))
    assert check_position_annotations(pos, _report(eval_cp=200)) == []


def test_flipped_eval_direction_flagged() -> None:
    pos = _pos(GroundTruthPoint("eval_direction", "white_better"))
    issues = check_position_annotations(pos, _report(eval_cp=-200))
    assert len(issues) == 1
    assert "eval_direction" in issues[0]


def test_matching_hanging_piece_passes() -> None:
    pos = _pos(GroundTruthPoint("hanging_piece", "e5"))
    report = _report(hanging=[HangingPiece("e5", "knight", "black")])
    assert check_position_annotations(pos, report) == []


def test_wrong_hanging_square_flagged() -> None:
    pos = _pos(GroundTruthPoint("hanging_piece", "e4"))
    report = _report(hanging=[HangingPiece("e5", "knight", "black")])
    issues = check_position_annotations(pos, report)
    assert len(issues) == 1
    assert "hanging_piece" in issues[0]
    assert "e5" in issues[0]  # reports what the engine actually found


def test_matching_tactic_passes() -> None:
    pos = _pos(GroundTruthPoint("tactic", "fork"))
    report = _report(tactics=[TacticalMotif("fork", ["d5"], ["N"], True, "knight fork")])
    assert check_position_annotations(pos, report) == []


def test_wrong_tactic_flagged() -> None:
    pos = _pos(GroundTruthPoint("tactic", "pin"))
    report = _report(tactics=[TacticalMotif("fork", ["d5"], ["N"], True, "fork")])
    issues = check_position_annotations(pos, report)
    assert len(issues) == 1
    assert "tactic" in issues[0]


def test_free_and_phase_points_are_skipped() -> None:
    pos = _pos(
        GroundTruthPoint("free", "center"),
        GroundTruthPoint("phase", "opening"),
    )
    # These aren't engine-verifiable; never flagged regardless of report.
    assert check_position_annotations(pos, _report(eval_cp=999)) == []


def test_multiple_mismatches_all_reported() -> None:
    pos = _pos(
        GroundTruthPoint("eval_direction", "white_better"),
        GroundTruthPoint("hanging_piece", "h5"),
    )
    report = _report(eval_cp=-300, hanging=[])
    issues = check_position_annotations(pos, report)
    assert len(issues) == 2


def test_equal_band_respected() -> None:
    # +20cp is within the equal band -> 'equal' annotation is correct.
    pos = _pos(GroundTruthPoint("eval_direction", "equal"))
    assert check_position_annotations(pos, _report(eval_cp=20)) == []
    # ...and a 'white_better' annotation at +20 is a mismatch.
    pos2 = _pos(GroundTruthPoint("eval_direction", "white_better"))
    assert len(check_position_annotations(pos2, _report(eval_cp=20))) == 1
