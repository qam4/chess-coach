"""Tests for the output fidelity checker (verify.check_coaching_fidelity).

Precision-first checks of finished coaching text against the board, the rules,
and the engine-tagged move menu. The motivating live failure: after adding
piece placement the coach stopped inventing pieces but still suggested
``Nxe4`` in the Italian — a legal but unsound move that drops the knight.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from chess_coach.coaching_phrases import MenuMove
from chess_coach.models import (
    EvalBreakdown,
    KingSafety,
    PawnFeatures,
    PositionReport,
)
from chess_coach.verify import Violation, check_coaching_fidelity

# Black to move. Black minors developed: Nc6, Nf6, Bc5. b8/g8 empty. e4 is a
# White pawn defended by Nc3 and the d3 pawn — so Nxe4 drops the knight.
ITALIAN_FEN = "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQK2R b KQkq - 0 5"


def _report(fen: str = ITALIAN_FEN) -> PositionReport:
    empty = PawnFeatures([], [], [])
    return PositionReport(
        fen=fen,
        eval_cp=0,
        eval_breakdown=EvalBreakdown(material=0, mobility=0, king_safety=0, pawn_structure=0),
        hanging_pieces={"white": [], "black": []},
        threats={"white": [], "black": []},
        pawn_structure={"white": empty, "black": empty},
        king_safety={"white": KingSafety(0, ""), "black": KingSafety(0, "")},
        top_lines=[],
        tactics=[],
        threat_map=[],
        threat_map_summary=None,
        critical_moment=False,
        critical_reason=None,
    )


# The Italian menu: Nd5 sound (best), Nxe4 a blunder (drops the knight).
ITALIAN_MENU = [
    MenuMove(san="Nd5", uci="f6d5", eval_cp=20, drop_cp=0, tag="best", theme="piece development"),
    MenuMove(san="O-O", uci="e8g8", eval_cp=10, drop_cp=10, tag="sound", theme="king safety, castling"),
    MenuMove(san="Nxe4", uci="f6e4", eval_cp=-160, drop_cp=180, tag="blunder", theme="material win"),
]


def _kinds(violations: list[Violation]) -> list[str]:
    return [v.kind for v in violations]


def test_regression_unsound_move_is_flagged() -> None:
    # The live failure: coach names Nxe4, an engine-tagged blunder.
    text = "You could grab the pawn with Nxe4, but be careful."
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU)
    assert "unsound_move" in _kinds(v)


def test_regression_sound_move_is_not_flagged() -> None:
    # Naming the sound best move produces no violation.
    text = "Play Nd5 to centralize your knight on a strong square."
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU)
    assert v == []


def test_correct_advice_has_no_false_positive() -> None:
    text = (
        "Your knight on f6 is well placed and your bishop on c5 is active. "
        "A good plan is to castle to get your king safe."
    )
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU)
    assert v == []


def test_placement_lie_is_flagged() -> None:
    # b8 is empty in the Italian — "your knight on b8" is a placement lie.
    text = "Your knight on b8 should come into the game."
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU)
    assert _kinds(v) == ["placement"]


def test_placement_wrong_piece_is_flagged() -> None:
    # c5 holds a bishop, not a knight.
    text = "The knight on c5 eyes the center."
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU)
    assert _kinds(v) == ["placement"]
    assert "bishop" in v[0].detail


def test_false_undeveloped_claim_is_flagged() -> None:
    # Nf6 is developed; calling it undeveloped contradicts the board.
    text = "Your knight on f6 is undeveloped and needs to move."
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU)
    assert "development" in _kinds(v)


def test_developed_claim_true_is_not_flagged() -> None:
    text = "Your developed knight on f6 controls key squares."
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU)
    assert v == []


def test_empty_source_move_is_flagged() -> None:
    # The classic hallucination: "move your knight from b8" — b8 is empty.
    text = "You should move your knight from b8 into the center."
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU)
    assert _kinds(v) == ["empty_source"]


def test_empty_source_deduped_across_phrasings() -> None:
    # "from b8 to a6" matches both the coordinate-move and bare-from checks;
    # a single empty square must be one violation, not two.
    text = "Move your knight from b8 to a6."
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU)
    assert _kinds(v) == ["empty_source"]


def test_illegal_named_move_is_flagged() -> None:
    # Rd4 — no black rook can reach d4 here; clearly a move (piece letter).
    text = "The move Rd4 looks tempting."
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU)
    assert "illegal_move" in _kinds(v)


def test_bare_square_reference_not_flagged_as_move() -> None:
    # "the e4 square" is a reference, not a move — must not be an illegal_move.
    text = "The e4 pawn is a target and the d5 square is strong."
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU)
    assert "illegal_move" not in _kinds(v)


def test_empty_menu_disables_unsound_but_keeps_legality() -> None:
    text = "You could grab the pawn with Nxe4."
    v = check_coaching_fidelity(text, _report(), [])
    # No menu -> no soundness/adherence judgment, but the move is legal so
    # nothing flags (off_menu needs a menu to compare against).
    assert v == []


# A realistic menu that does NOT list Nxe4 (a knight-drop the engine ranks
# below the top candidates) — the real-world case where the coach naming
# Nxe4 is an off-menu recommendation, not a listed-but-bad one.
ITALIAN_MENU_NO_NXE4 = [
    MenuMove(san="Nd5", uci="f6d5", eval_cp=20, drop_cp=0, tag="best", theme="piece development"),
    MenuMove(san="O-O", uci="e8g8", eval_cp=10, drop_cp=10, tag="sound", theme="king safety, castling"),
]


def test_off_menu_move_is_flagged() -> None:
    # Nxe4 is legal but not in the sound menu -> off_menu (the coach was told
    # to recommend only listed moves). This is the real Nxe4 case.
    text = "You could grab the pawn with Nxe4."
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU_NO_NXE4)
    assert _kinds(v) == ["off_menu"]


def test_off_menu_not_flagged_for_listed_sound_move() -> None:
    text = "Play Nd5 to centralize; O-O is also fine."
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU_NO_NXE4)
    assert v == []


def test_off_menu_needs_a_menu() -> None:
    # Without a menu we cannot judge adherence, so no off_menu is emitted.
    text = "You could grab the pawn with Nxe4."
    assert check_coaching_fidelity(text, _report(), []) == []


def test_warned_against_move_is_not_flagged() -> None:
    # Naming a bad move to warn against it is allowed by the prompt.
    for text in (
        "Avoid Nxe4 — it drops the knight.",
        "Don't play Nxe4 here.",
        "Play Nd5 instead of Nxe4.",
        "You might be tempted to play Nxe4, but it loses a piece.",
    ):
        v = check_coaching_fidelity(text, _report(), ITALIAN_MENU_NO_NXE4)
        assert "off_menu" not in _kinds(v), text


def test_recommended_bad_move_still_flagged_without_warning() -> None:
    # No warning cue -> naming the off-menu move is a violation.
    v = check_coaching_fidelity("A strong try is Nxe4.", _report(), ITALIAN_MENU_NO_NXE4)
    assert _kinds(v) == ["off_menu"]


def test_illegal_move_flagged_even_when_warned() -> None:
    # Illegality is a factual error regardless of framing, so it still fires.
    v = check_coaching_fidelity("Avoid Rd4, it loses.", _report(), ITALIAN_MENU_NO_NXE4)
    assert "illegal_move" in _kinds(v)


def test_bad_fen_returns_empty() -> None:
    bad = _report(fen="not a fen")
    assert check_coaching_fidelity("Play Nxe4 from b8.", bad, ITALIAN_MENU) == []


@given(st.text(max_size=200))
def test_property_checker_is_total(text: str) -> None:
    # Property 3: never raises over arbitrary text.
    result = check_coaching_fidelity(text, _report(), ITALIAN_MENU)
    assert isinstance(result, list)


@given(st.text(max_size=200))
def test_property_checker_is_deterministic(text: str) -> None:
    assert check_coaching_fidelity(text, _report(), ITALIAN_MENU) == check_coaching_fidelity(
        text, _report(), ITALIAN_MENU
    )
