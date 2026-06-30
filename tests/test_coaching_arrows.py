"""Tests for board-arrow extraction from tactics (the discovered-attack contract).

The engine emits a discovered_attack with ``squares = [revealed_attacker,
target, mover]``. The overlay must draw the revealed attack line
(attacker -> target) and must NOT draw attacker -> mover (the old bug, which
produced e.g. a c1->d2 arrow the bishop never makes).
"""

from __future__ import annotations

from chess_coach.coaching_templates import _extract_arrows
from chess_coach.models import (
    EvalBreakdown,
    KingSafety,
    PawnFeatures,
    PositionReport,
    TacticalMotif,
)

QG5_FEN = "rnb1kbnr/pppp1ppp/4p3/6q1/4P3/2N5/PPPP1PPP/R1BQKB1R w KQkq - 2 3"


def _report(tactics: list[TacticalMotif]) -> PositionReport:
    empty_pawns = PawnFeatures([], [], [])
    return PositionReport(
        fen=QG5_FEN,
        eval_cp=0,
        eval_breakdown=EvalBreakdown(material=0, mobility=0, king_safety=0, pawn_structure=0),
        hanging_pieces={"white": [], "black": []},
        threats={"white": [], "black": []},
        pawn_structure={"white": empty_pawns, "black": empty_pawns},
        king_safety={"white": KingSafety(0, ""), "black": KingSafety(0, "")},
        top_lines=[],
        tactics=tactics,
        threat_map=[],
        threat_map_summary=None,
        critical_moment=False,
        critical_reason=None,
    )


def _pairs(report: PositionReport) -> set[tuple[str, str]]:
    return {(a.from_sq, a.to_sq) for a in _extract_arrows(report)}


def test_discovered_attack_draws_only_the_revealed_attack_line() -> None:
    da = TacticalMotif(
        type="discovered_attack",
        squares=["c1", "g5", "d2"],  # [revealed_attacker, target, mover]
        pieces=["Bc1", "Qg5", "d2"],
        in_pv=False,
        description="Discovered attack: d2 moves to reveal Bc1 attacking Qg5",
    )
    pairs = _pairs(_report([da]))
    assert ("c1", "g5") in pairs  # the revealed attack
    assert ("c1", "d2") not in pairs  # the bogus attacker->mover arrow is gone


def test_fork_still_draws_forker_to_each_target() -> None:
    fork = TacticalMotif(
        type="fork",
        squares=["e5", "c6", "g6"],  # [forker, target1, target2]
        pieces=["Ne5", "Nc6", "Qg6"],
        in_pv=False,
        description="Fork: Ne5 attacks Nc6 and Qg6",
    )
    pairs = _pairs(_report([fork]))
    assert ("e5", "c6") in pairs
    assert ("e5", "g6") in pairs
