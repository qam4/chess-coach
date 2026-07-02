"""Tests for board-arrow extraction from tactics (the discovered-attack contract).

The engine emits a discovered_attack with ``squares = [revealed_attacker,
target, mover]``. The overlay must draw the revealed attack line
(attacker -> target) and must NOT draw attacker -> mover (the old bug, which
produced e.g. a c1->d2 arrow the bishop never makes).
"""

from __future__ import annotations

from chess_coach.coaching_templates import _extract_arrows, _threats_and_tactics_text
from chess_coach.models import (
    EvalBreakdown,
    KingSafety,
    PawnFeatures,
    PositionReport,
    TacticalMotif,
    Threat,
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


def test_tactic_line_is_not_double_labeled() -> None:
    # The engine description already leads with "Type (Side): ...", so the
    # rendered line must not repeat the type label (the old
    # "Discovered attack: Discovered attack: ..." bug) and must carry the side.
    da = TacticalMotif(
        type="discovered_attack",
        squares=["c1", "g5", "d2"],
        pieces=["Bc1", "Qg5", "d2"],
        in_pv=False,
        description="Discovered attack (White): d2 moves to reveal Bc1 attacking Qg5",
    )
    text = _threats_and_tactics_text(_report([da]))
    assert text is not None
    # Composed from structured fields — the engine prose is never rendered.
    assert "Discovered attack (White):" not in text
    assert "discovered attack: moving d2 reveals Bc1 hitting Qg5" in text
    assert text.lower().count("discovered attack") == 1


def _report_with_threats(
    tactics: list[TacticalMotif],
    threats: dict[str, list[Threat]],
) -> PositionReport:
    empty_pawns = PawnFeatures([], [], [])
    return PositionReport(
        fen=QG5_FEN,
        eval_cp=0,
        eval_breakdown=EvalBreakdown(material=0, mobility=0, king_safety=0, pawn_structure=0),
        hanging_pieces={"white": [], "black": []},
        threats=threats,
        pawn_structure={"white": empty_pawns, "black": empty_pawns},
        king_safety={"white": KingSafety(0, ""), "black": KingSafety(0, "")},
        top_lines=[],
        tactics=tactics,
        threat_map=[],
        threat_map_summary=None,
        critical_moment=False,
        critical_reason=None,
    )


def test_discovered_attack_variants_collapse_to_one_line() -> None:
    # The engine reports the same discovered attack (Bc1 -> Qg5) three ways:
    # on-board plus two PV moves (d3, d4). The coaching must show it once,
    # keeping the on-board detection (the general, reliable statement of the
    # motif) rather than an arbitrary PV move.
    onboard = TacticalMotif(
        type="discovered_attack",
        squares=["c1", "g5", "d2"],
        pieces=["Bc1", "Qg5", "d2"],
        in_pv=False,
        description="Discovered attack (White): d2 moves to reveal Bc1 attacking Qg5",
    )
    pv_d3 = TacticalMotif(
        type="discovered_attack",
        squares=["c1", "g5", "d3"],
        pieces=["Bc1", "Qg5", "d3"],
        in_pv=True,
        description="Discovered attack (White): d2-d3 reveals Bc1 attacking Qg5",
    )
    pv_d4 = TacticalMotif(
        type="discovered_attack",
        squares=["c1", "g5", "d4"],
        pieces=["Bc1", "Qg5", "d4"],
        in_pv=True,
        description="Discovered attack (White): d2-d4 reveals Bc1 attacking Qg5",
    )
    text = _threats_and_tactics_text(_report([onboard, pv_d3, pv_d4]))
    assert text is not None
    # One discovered-attack line total, and it is the on-board detection.
    assert text.lower().count("discovered attack") == 1
    assert "moving d2 reveals" in text
    assert "d3" not in text and "d4" not in text  # arbitrary PV mover squares dropped


def test_dedup_falls_back_to_pv_when_no_on_board_variant() -> None:
    # If a motif appears only in PV lines (no on-board detection), the
    # first PV variant is kept rather than dropping the tactic entirely.
    pv_d3 = TacticalMotif(
        type="discovered_attack",
        squares=["c1", "g5", "d3"],
        pieces=["Bc1", "Qg5", "d3"],
        in_pv=True,
        description="Discovered attack (White): d2-d3 reveals Bc1 attacking Qg5",
    )
    pv_d4 = TacticalMotif(
        type="discovered_attack",
        squares=["c1", "g5", "d4"],
        pieces=["Bc1", "Qg5", "d4"],
        in_pv=True,
        description="Discovered attack (White): d2-d4 reveals Bc1 attacking Qg5",
    )
    text = _threats_and_tactics_text(_report([pv_d3, pv_d4]))
    assert text is not None
    assert text.lower().count("discovered attack") == 1
    assert "moving d3 reveals" in text  # first PV variant kept as fallback


def test_threat_restating_a_tactic_is_suppressed() -> None:
    # A pin is reported as BOTH a tactic and a threat. The threat line that
    # merely restates the tactic must be dropped; distinct threats stay.
    pin = TacticalMotif(
        type="pin",
        squares=["b4", "c3", "e1"],
        pieces=["Bb4", "Nc3", "Ke1"],
        in_pv=False,
        description="Pin (Black): Bb4 pins Nc3 to Ke1",
    )
    threats = {
        "white": [],
        "black": [
            Threat("check", "b4", ["c3"], "Bb4 can give check via b4c3"),
            Threat("pin", "b4", ["c3"], "Bb4 pins Nc3 to Ke1"),
        ],
    }
    text = _threats_and_tactics_text(_report_with_threats([pin], threats))
    assert text is not None
    assert text.count("pins Nc3 to Ke1") == 1  # only the tactic, not the echoing pin threat
    assert "can give check" in text  # the distinct check threat survives
