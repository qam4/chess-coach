"""Tests for the rules-tier verifier (verify.filter_illegal_threats).

The live bug that motivated this: after 1.e4 e6 2.Nc3 Qg5 3.d4 Qg6 4.Nf3 Nf6
5.e5 Bb4 6.exf6 Qe4+, the engine reported White threats that ignore the pin on
Nc3 and the fact that White is in check. python-chess (an independent rules
implementation) proves them illegal, so they should be dropped.
"""

from __future__ import annotations

from chess_coach.models import (
    EvalBreakdown,
    KingSafety,
    PawnFeatures,
    PositionReport,
    Threat,
)
from chess_coach.verify import filter_illegal_threats

# White to move, IN CHECK (Qe4+). White's only legal moves: Kd2, Be2, Qe2, Be3.
# Nc3 is pinned by Bb4; e4 queen's only White attacker is the pinned knight.
QE4_CHECK_FEN = "rnb1k2r/pppp1ppp/4pP2/8/1b1Pq3/2N2N2/PPP2PPP/R1BQKB1R w KQkq - 1 7"


def _report(fen: str, threats: dict[str, list[Threat]]) -> PositionReport:
    """Minimal PositionReport carrying only the threats under test."""
    empty_pawns = PawnFeatures([], [], [])
    return PositionReport(
        fen=fen,
        eval_cp=0,
        eval_breakdown=EvalBreakdown(material=0, mobility=0, king_safety=0, pawn_structure=0),
        hanging_pieces={"white": [], "black": []},
        threats=threats,
        pawn_structure={"white": empty_pawns, "black": empty_pawns},
        king_safety={"white": KingSafety(0, ""), "black": KingSafety(0, "")},
        top_lines=[],
        tactics=[],
        threat_map=[],
        threat_map_summary=None,
        critical_moment=False,
        critical_reason=None,
    )


def _descriptions(report: PositionReport, side: str) -> list[str]:
    return [t.description for t in report.threats[side]]


def test_drops_pinned_in_check_capture_from_description() -> None:
    # White's pinned knight cannot capture the checking queen; uci read from
    # the "via c3e4" token in the description (no structured uci_move).
    report = _report(
        QE4_CHECK_FEN,
        {
            "white": [
                Threat(
                    type="capture",
                    source_square="c3",
                    target_squares=["e4"],
                    description="Nc3 can capture undefended Qe4 via c3e4",
                )
            ],
            "black": [],
        },
    )
    out = filter_illegal_threats(report)
    assert out.threats["white"] == []


def test_drops_capture_that_ignores_check() -> None:
    # fxg7 is geometrically possible but illegal: White must answer the check.
    report = _report(
        QE4_CHECK_FEN,
        {
            "white": [
                Threat(
                    type="capture",
                    source_square="f6",
                    target_squares=["g7"],
                    description="f6 can capture undefended g7 via f6g7",
                )
            ],
            "black": [],
        },
    )
    out = filter_illegal_threats(report)
    assert out.threats["white"] == []


def test_drops_via_structured_uci_move_field() -> None:
    report = _report(
        QE4_CHECK_FEN,
        {
            "white": [
                Threat(type="capture", source_square="c3", target_squares=["e4"], description="", uci_move="c3e4")
            ],
            "black": [],
        },
    )
    out = filter_illegal_threats(report)
    assert out.threats["white"] == []


def test_keeps_legal_opponent_threats() -> None:
    # Black's threats are validated by simulating Black's turn. Bxc3 (check),
    # gxf6 (capture), and Qe2 are all legal for Black and must survive.
    report = _report(
        QE4_CHECK_FEN,
        {
            "white": [],
            "black": [
                Threat(
                    type="check", source_square="b4", target_squares=["c3"], description="Bb4 can give check via b4c3"
                ),
                Threat(
                    type="capture",
                    source_square="g7",
                    target_squares=["f6"],
                    description="g7 can capture undefended f6 via g7f6",
                ),
                Threat(
                    type="check", source_square="e4", target_squares=["e2"], description="Qe4 can give check via e4e2"
                ),
            ],
        },
    )
    out = filter_illegal_threats(report)
    assert len(out.threats["black"]) == 3


def test_keeps_relational_facts_without_a_move() -> None:
    # Pins/skewers are static facts, not move claims, and carry no uci token,
    # so they must never be dropped even if true.
    report = _report(
        QE4_CHECK_FEN,
        {
            "white": [],
            "black": [
                Threat(type="pin", source_square="b4", target_squares=["c3"], description="Bb4 pins Nc3 to Ke1"),
                Threat(
                    type="skewer", source_square="e4", target_squares=["f3", "g2"], description="Qe4 skewers Nf3 and g2"
                ),
            ],
        },
    )
    out = filter_illegal_threats(report)
    assert _descriptions(out, "black") == ["Bb4 pins Nc3 to Ke1", "Qe4 skewers Nf3 and g2"]


def test_returns_same_object_when_nothing_dropped() -> None:
    report = _report(QE4_CHECK_FEN, {"white": [], "black": []})
    assert filter_illegal_threats(report) is report


def test_malformed_fen_returns_report_unchanged() -> None:
    report = _report(
        "not-a-fen",
        {
            "white": [Threat(type="capture", source_square="c3", target_squares=["e4"], description="via c3e4")],
            "black": [],
        },
    )
    out = filter_illegal_threats(report)
    assert out is report


def test_mixed_drops_only_the_illegal_white_threats() -> None:
    # The full live example: two illegal White threats dropped, the legal
    # Black threats and relational facts kept.
    report = _report(
        QE4_CHECK_FEN,
        {
            "white": [
                Threat(
                    type="capture",
                    source_square="c3",
                    target_squares=["e4"],
                    description="Nc3 can capture undefended Qe4 via c3e4",
                ),
                Threat(
                    type="capture",
                    source_square="f6",
                    target_squares=["g7"],
                    description="f6 can capture undefended g7 via f6g7",
                ),
            ],
            "black": [
                Threat(
                    type="check", source_square="b4", target_squares=["c3"], description="Bb4 can give check via b4c3"
                ),
                Threat(type="pin", source_square="b4", target_squares=["c3"], description="Bb4 pins Nc3 to Ke1"),
            ],
        },
    )
    out = filter_illegal_threats(report)
    assert out.threats["white"] == []
    assert len(out.threats["black"]) == 2
