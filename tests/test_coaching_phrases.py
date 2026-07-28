"""Tests for the coaching-phrase composer (single source of truth).

Feature: client-side-coaching-text.
Covers composer totality/determinism (Property 1/2), policy invariance
(Property 5), and pins representative sentences per motif/threat type.
"""

from __future__ import annotations

import chess
from hypothesis import given
from hypothesis import strategies as st

from chess_coach.coaching_phrases import (
    describe_eval,
    describe_hanging,
    describe_king_safety,
    describe_pawn_structure,
    describe_placement,
    describe_tactic,
    describe_threat,
    king_safety_relevant,
    select_tactics,
    suppress_threats_echoing_tactics,
)
from chess_coach.models import (
    EvalBreakdown,
    HangingPiece,
    KingSafety,
    PawnFeatures,
    PositionReport,
    TacticalMotif,
    Threat,
)

# A position with White Bc1, Black Qg5 — discovered attack by the d-pawn.
DA_FEN = "rnb1kbnr/pppp1ppp/4p3/6q1/4P3/2N5/PPPP1PPP/R1BQKB1R w KQkq - 2 3"
# Black bishop b4 pins White Nc3 to Ke1.
PIN_FEN = "4k3/8/8/8/1b6/2N5/8/4K3 b - - 0 1"

TACTIC_TYPES = ["fork", "pin", "skewer", "discovered_attack", "back_rank_threat", "overloaded_piece", "mystery_motif"]
THREAT_TYPES = ["check", "capture", "fork", "pin", "skewer", "discovered_attack", "mystery_threat"]


def _report(fen: str = DA_FEN, eval_cp: int = 0, tactics: list[TacticalMotif] | None = None) -> PositionReport:
    empty = PawnFeatures([], [], [])
    return PositionReport(
        fen=fen,
        eval_cp=eval_cp,
        eval_breakdown=EvalBreakdown(material=0, mobility=0, king_safety=0, pawn_structure=0),
        hanging_pieces={"white": [], "black": []},
        threats={"white": [], "black": []},
        pawn_structure={"white": empty, "black": empty},
        king_safety={"white": KingSafety(0, ""), "black": KingSafety(0, "")},
        top_lines=[],
        tactics=tactics or [],
        threat_map=[],
        threat_map_summary=None,
        critical_moment=False,
        critical_reason=None,
    )


# --------------------------------------------------------------- unit: tactics


def test_discovered_attack_sentence_from_structured_fields() -> None:
    board = chess.Board(DA_FEN)
    t = TacticalMotif("discovered_attack", ["c1", "g5", "d2"], ["Bc1", "Qg5", "d2"], False, "IGNORED ENGINE PROSE")
    s = describe_tactic(t, board)
    assert s == "White has a discovered attack: moving d2 reveals Bc1 hitting Qg5."
    assert "in PV" not in s
    assert "IGNORED" not in s  # engine description is never consumed


def test_pin_sentence_names_the_pinning_side() -> None:
    board = chess.Board(PIN_FEN)
    t = TacticalMotif("pin", ["b4", "c3", "e1"], ["Bb4", "Nc3", "Ke1"], False, "")
    assert describe_tactic(t, board) == "Black has a pin: Bb4 pins Nc3 to Ke1."


def test_pv_tactic_reads_as_main_line() -> None:
    board = chess.Board(DA_FEN)
    t = TacticalMotif("discovered_attack", ["c1", "g5", "d4"], ["Bc1", "Qg5", "d4"], True, "")
    s = describe_tactic(t, board)
    assert s.startswith("In the main line, White gets ")
    assert "in PV" not in s


# --------------------------------------------------------------- unit: threats


def test_check_threat_uses_uci_move_not_prose() -> None:
    board = chess.Board("6k1/5ppp/8/8/8/8/8/4R1K1 w - - 0 1")
    th = Threat("check", "e1", ["e8"], "PROSE THAT MUST NOT APPEAR", uci_move="e1e8")
    s = describe_threat(th, board)
    assert s == "White's rook can give check with e1-e8."
    assert "PROSE" not in s


def test_capture_threat_names_target_square() -> None:
    board = chess.Board("r3k2r/ppp2ppp/8/3N4/8/8/PPP2PPP/R3K2R w KQkq - 0 1")
    th = Threat("capture", "d5", ["c7"], "", uci_move="d5c7")
    assert describe_threat(th, board) == "White's knight can capture on c7."


def test_threat_without_uci_move_degrades_gracefully() -> None:
    board = chess.Board("6k1/5ppp/8/8/8/8/8/4R1K1 w - - 0 1")
    th = Threat("check", "e1", ["e8"], "", uci_move="")  # engine gap: no structured move
    s = describe_threat(th, board)
    assert s == "White's rook can give check."  # move-less, no crash, no prose


# --------------------------------------------------- unit: hanging / pawns / eval


def test_placement_lists_pieces_and_development_from_the_board() -> None:
    # The Italian position that produced the Nb8 hallucination: Black's minors
    # are all developed (Nc6, Nf6, Bc5); only the c8 bishop is still home.
    board = chess.Board("r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQK2R b KQkq - 0 5")
    text = describe_placement(board)
    assert "Black to move." in text
    # Actual pieces are listed on their real squares.
    assert "N c6 f6" in text
    assert "B c5 c8" in text
    # Development is stated correctly — the anti-hallucination signal: Black's
    # minors are developed, only the c8 bishop is home.
    assert "developed minors: Nc6, Nf6, Bc5; still home: Bc8" in text
    # No phantom knight on b8 (it left c6/f6 are its squares now).
    assert "b8" not in text


def test_placement_empty_board_is_safe() -> None:
    assert describe_placement(None) == ""


def test_placement_starting_position_all_minors_home() -> None:
    text = describe_placement(chess.Board(chess.STARTING_FEN))
    assert "developed minors: none" in text


def test_hanging_piece_sentence() -> None:
    hp = HangingPiece(square="e5", piece="pawn", color="black")
    assert describe_hanging(hp) == "Black's pawn on e5 is undefended."


def test_pawn_structure_none_when_unremarkable() -> None:
    assert describe_pawn_structure(PawnFeatures([], [], []), "white") is None
    s = describe_pawn_structure(PawnFeatures(["d"], [], ["e"]), "white")
    assert s is not None and "isolated" in s and "passed" in s


def test_eval_summary_directions() -> None:
    assert describe_eval(_report(eval_cp=0)) == "The position is roughly equal."
    assert describe_eval(_report(eval_cp=800)).startswith("White is winning")
    assert describe_eval(_report(eval_cp=-800)).startswith("Black is winning")


# --------------------------------------------------------------- unit: king safety


def test_king_safety_solid_king_is_not_flagged() -> None:
    ks = KingSafety(score=0, description="IGNORED", castling_status="kingside_castled")
    assert describe_king_safety(ks, "white") is None


def test_king_safety_uncastled_with_shield_is_not_flagged() -> None:
    ks = KingSafety(score=0, description="", castling_status="uncastled_with_rights")
    assert describe_king_safety(ks, "black") is None


def test_king_safety_composes_from_structured_fields_not_prose() -> None:
    ks = KingSafety(
        score=-150,
        description="__ENGINE_PROSE_MUST_NOT_APPEAR__",
        king_square="e2",
        castling_status="displaced",
        missing_shield_files=["d", "e", "f"],
        open_file_near_king=True,
    )
    s = describe_king_safety(ks, "white")
    assert s is not None
    assert "__ENGINE_PROSE" not in s
    assert "displaced to e2" in s
    assert "d, e, f" in s
    assert "open file" in s


def test_king_safety_stuck_in_center_and_storm() -> None:
    ks = KingSafety(score=-30, description="", castling_status="stuck_in_center", pawn_storm=True)
    s = describe_king_safety(ks, "black")
    assert s is not None and "stuck in the center" in s and "pawn storm" in s


# --------------------------------------------------------------- policy layer


def test_select_tactics_collapses_variants_prefers_on_board() -> None:
    onboard = TacticalMotif("discovered_attack", ["c1", "g5", "d2"], ["Bc1", "Qg5", "d2"], False, "")
    pv_d3 = TacticalMotif("discovered_attack", ["c1", "g5", "d3"], ["Bc1", "Qg5", "d3"], True, "")
    pv_d4 = TacticalMotif("discovered_attack", ["c1", "g5", "d4"], ["Bc1", "Qg5", "d4"], True, "")
    out = select_tactics([pv_d3, onboard, pv_d4])
    assert len(out) == 1
    assert out[0].in_pv is False  # on-board wins even when a PV variant came first


def test_select_tactics_keeps_pv_when_no_on_board() -> None:
    pv_d3 = TacticalMotif("discovered_attack", ["c1", "g5", "d3"], ["Bc1", "Qg5", "d3"], True, "")
    pv_d4 = TacticalMotif("discovered_attack", ["c1", "g5", "d4"], ["Bc1", "Qg5", "d4"], True, "")
    out = select_tactics([pv_d3, pv_d4])
    assert len(out) == 1 and out[0].in_pv is True


def test_suppress_threats_echoing_tactics() -> None:
    pin_tactic = TacticalMotif("pin", ["b4", "c3", "e1"], ["Bb4", "Nc3", "Ke1"], False, "")
    threats = [
        Threat("check", "b4", ["c3"], "", uci_move="b4c3"),  # distinct — kept
        Threat("pin", "b4", ["c3"], "", uci_move="b4c3"),  # echoes the tactic — dropped
    ]
    kept = suppress_threats_echoing_tactics(threats, [pin_tactic])
    assert [t.type for t in kept] == ["check"]


def test_king_safety_relevant_suppressed_in_endgame() -> None:
    assert king_safety_relevant(_report(fen="8/8/8/4k3/8/8/4K3/4R3 w - - 0 1")) is False  # K+R vs K
    assert king_safety_relevant(_report(fen=chess.STARTING_FEN)) is True


# --------------------------------------------------------------- properties

_SQUARES = ["a1", "c1", "d2", "e1", "e8", "g5", "c3", "b4", "c7", "d5"]


@st.composite
def _tactics(draw: st.DrawFn) -> TacticalMotif:
    ttype = draw(st.sampled_from(TACTIC_TYPES))
    squares = draw(st.lists(st.sampled_from(_SQUARES), min_size=0, max_size=4))
    pieces = draw(st.lists(st.sampled_from(["Bc1", "Qg5", "Nc3", "Ke1", "Re1", "d2"]), min_size=0, max_size=4))
    return TacticalMotif(ttype, squares, pieces, draw(st.booleans()), draw(st.text(max_size=20)))


@st.composite
def _threats(draw: st.DrawFn) -> Threat:
    ttype = draw(st.sampled_from(THREAT_TYPES))
    targets = draw(st.lists(st.sampled_from(_SQUARES), min_size=0, max_size=3))
    return Threat(
        ttype, draw(st.sampled_from(_SQUARES)), targets, draw(st.text(max_size=20)), draw(st.text(max_size=5))
    )


@given(_tactics())
def test_property_describe_tactic_is_total(t: TacticalMotif) -> None:
    # Property 1: never raises, never empty — over the full type enum.
    board = chess.Board(DA_FEN)
    s = describe_tactic(t, board)
    assert isinstance(s, str) and s.strip() != ""
    assert "in PV" not in s  # engine jargon never leaks


@given(_threats())
def test_property_describe_threat_is_total(th: Threat) -> None:
    board = chess.Board(DA_FEN)
    s = describe_threat(th, board)
    assert isinstance(s, str) and s.strip() != ""


@given(_tactics())
def test_property_describe_tactic_is_deterministic(t: TacticalMotif) -> None:
    # Property 2: identical input -> identical output.
    assert describe_tactic(t, chess.Board(DA_FEN)) == describe_tactic(t, chess.Board(DA_FEN))


@given(st.lists(_tactics(), max_size=6))
def test_property_select_tactics_idempotent_and_deduped(ts: list[TacticalMotif]) -> None:
    # Property 5: policy is stable — selecting twice equals selecting once,
    # and no two survivors share a motif identity.
    once = select_tactics(ts)
    twice = select_tactics(once)
    assert once == twice
