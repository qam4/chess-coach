"""The coach must be able to name the move the student played without being charged for it.

B-014. `_check_named_moves` skips tokens attributed to the opponent, piece references and
non-moves, then scores everything else against the engine's best/sound menu. It had no
exclusion for the PLAYED move — so "By moving Be2, you left your pawn on g5 undefended", which
is the coach correctly naming what just happened, was read as recommending `Be2`, a move that
is not on the best/sound menu precisely because the student just played a mistake.

Found while checking an apparent regression at v60 (`off_menu` 6 -> 9) that was not one: on all
five newly-flagged turns the only legal move token in the text was the student's own, and
`_recommended_tokens` read none of them as advice. Long-standing — 20 such turns at v57, 11 at
v58, 16 at v60 — and non-gating, so nothing reached a student wrongly. What it did do is make
those two counters incomparable across any change that alters how often the coaching names a
move, which is exactly what B-012 did.

Following ledger row 113: this is a ROUTING decision, not an exemption. The menu rule is "only
RECOMMEND best/sound moves", and the played move is not a recommendation, so only that
classification is skipped. Legality, piece-reference and claim checks still see it.
"""

from __future__ import annotations

import chess
import pytest

from chess_coach.coaching_phrases import MenuMove
from chess_coach.verify import check_text_fidelity

#: The real position from v60 seed 7 ply 28, not an invented one — the first draft of this test
#: used a hand-written FEN in which both Be2 and Ke2 were illegal. The student played Be2
#: (c4-e2); the engine wanted Ke2 (d1-e2). The coaching names the played move because that is
#: the move it is explaining.
_FEN = "r1b1k1r1/pppp1p1p/4p3/6P1/1bBB4/1P2P3/P1P3nP/RN1K3R w q - 0 15"
_TEXT = "By moving Be2, you left your pawn on g5 undefended."


def _menu() -> list[MenuMove]:
    """A menu that does NOT contain the played move — the shape every mistake turn has."""
    return [
        MenuMove(san="Ke2", uci="d1e2", eval_cp=40, drop_cp=0, tag="best", theme="king activity"),
        MenuMove(san="Bd3", uci="c4d3", eval_cp=20, drop_cp=20, tag="sound", theme="piece activity"),
    ]


def _played_uci() -> str:
    board = chess.Board(_FEN)
    return board.parse_san("Be2").uci()


def test_naming_the_played_move_is_not_a_recommendation() -> None:
    kinds = [v.kind for v in check_text_fidelity(_TEXT, _FEN, _menu(), _played_uci())]
    assert "off_menu" not in kinds, "the coach was charged for naming the move the student played"
    assert "unsound_move" not in kinds
    assert kinds == [], f"nothing else should fire either, got {kinds}"


def test_a_genuinely_off_menu_recommendation_still_fires() -> None:
    """The guard that makes the test above meaningful rather than a blanket exemption.

    A move that is NOT the played move and NOT on the menu must still be flagged, or the fix
    has simply disabled the check.
    """
    text = "A stronger move was Bb5, which keeps the bishop active."
    kinds = [v.kind for v in check_text_fidelity(text, _FEN, _menu(), _played_uci())]
    assert "off_menu" in kinds, f"an off-menu recommendation must still be caught, got {kinds}"


def test_the_exclusion_is_the_played_move_and_not_any_legal_move() -> None:
    """Keyed on `played_uci`, so the same text with a different played move still flags.

    If the exclusion were "any legal move the coach names", every turn would go unchecked.
    """
    board = chess.Board(_FEN)
    other = board.parse_san("Ke2").uci()  # pretend the student played Ke2 (d1-e2) instead
    kinds = [v.kind for v in check_text_fidelity(_TEXT, _FEN, _menu(), other)]
    assert "off_menu" in kinds, "Be2 is not the played move here, so it is a recommendation"


@pytest.mark.parametrize("played", ["", "not-a-uci"])
def test_no_played_move_supplied_behaves_as_before(played: str) -> None:
    """Callers that cannot supply the played move must not silently lose the check.

    Ledger row 114: a counter called the checker WITHOUT `played_uci` while the gate passed it,
    and reported six leaks on text the gate had cleared. The argument is optional, so the
    behaviour when it is absent has to stay what it always was.
    """
    kinds = [v.kind for v in check_text_fidelity(_TEXT, _FEN, _menu(), played)]
    assert "off_menu" in kinds


# --- B-019: the played move offered back to the student as an option -------------------------
#
# B-014 is right that NAMING the played move is not a recommendation. It is wrong for one shape,
# which the five tests above never used: the coach telling the student that the move they just
# played "is still available". That is advice to play the move they already played, and after
# B-014 the checker passed all of them as clean.

#: v60 seed 23 ply 43, from the committed transcript. White played Qb6+ (c5b6). The first
#: sentence names the played move to say what it did, which is B-014's case and must stay clean;
#: the second offers it back, which is B-019's.
_FEN_43 = "2bk3r/6p1/4p3/p1Q1P2p/4B1n1/5p2/PP3PPP/1R1K3R w - - 3 24"
_CONSEQUENCE_43 = "Qb6+ leaves the pawn on e5 undefended."
_OFFERED_43 = "The move Qb6+ is still available."


def _kinds(text: str, fen: str, played_san: str) -> list[str]:
    played = chess.Board(fen).parse_san(played_san).uci()
    return [v.kind for v in check_text_fidelity(text, fen, [], played)]


def test_the_played_move_offered_as_still_available_is_flagged() -> None:
    kinds = _kinds(f"{_CONSEQUENCE_43} {_OFFERED_43}", _FEN_43, "Qb6+")
    assert "played_offered" in kinds, f"the student was told to play the move they just played, got {kinds}"


def test_naming_what_the_played_move_did_is_still_not_flagged() -> None:
    """The guard that keeps B-014: the same move, named to say what it did, stays clean."""
    assert "played_offered" not in _kinds(_CONSEQUENCE_43, _FEN_43, "Qb6+")
    assert "played_offered" not in _kinds(_TEXT, _FEN, "Be2")


def test_a_pawn_move_offered_as_still_available_is_flagged() -> None:
    """Half of the v60 cases are bare pawn moves, which `_check_named_moves` never judges.

    v60 seed 13 ply 26: White played c4 (c3c4). A check placed inside the menu classification
    would see Bc1, Bd3, dxe5 and Qb6+ and miss h4, c6, c4 and e3.
    """
    fen = "3k3r/p4ppp/p1p2n2/4p3/3P4/2P2P2/4PKPP/2q2BNR w - - 2 16"
    text = "Your move c4 left the pawn on d4 undefended. The move c4 is still available."
    assert "played_offered" in _kinds(text, fen, "c4")
    assert "played_offered" not in _kinds("Your move c4 left the pawn on d4 undefended.", fen, "c4")


def test_another_move_said_to_be_available_is_not_this_check() -> None:
    """Keyed on the PLAYED move. A different move named as available is a separate question."""
    assert "played_offered" not in _kinds(_OFFERED_43, _FEN_43, "Bd5")


_V60_OFFERED = {
    (7, 38),
    (7, 46),
    (13, 20),
    (13, 26),
    (13, 36),
    (23, 21),
    (23, 39),
    (23, 43),
}


def _flagged_turns(version: str) -> set[tuple[int, int]]:
    """Spoken turns of the committed five-seed run where the checker reports `played_offered`."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "output"
    out: set[tuple[int, int]] = set()
    for seed in (7, 11, 13, 17, 23):
        data = json.loads((root / f"coach_review_{version}_seed{seed}" / "transcript.json").read_text(encoding="utf-8"))
        for t in data["turns"]:
            text = (t.get("coach_feedback") or "").strip()
            if not text:
                continue
            fen = t["fen_before"]
            played = chess.Board(fen).parse_san(t["student_move_san"]).uci()
            if any(v.kind == "played_offered" for v in check_text_fidelity(text, fen, [], played)):
                out.add((seed, int(t["ply"])))
    return out


def test_v60_flags_exactly_the_eight_turns_that_offer_the_played_move() -> None:
    """Read by hand on the committed v60 transcripts: these 8 of 81 spoken turns, and no others."""
    assert _flagged_turns("v60") == _V60_OFFERED


def test_the_check_reports_and_does_not_gate() -> None:
    """It measures the prompt fix. The report card counts the SHIPPED text, so a gating kind would
    read zero after the fix whatever the prompt did."""
    from chess_coach.verify import GATING_VIOLATION_KINDS

    assert "played_offered" not in GATING_VIOLATION_KINDS


def test_v57_flags_nothing() -> None:
    """The control. v57 sent the same repeat instruction on 18 turns, while the prompt still carried
    the engine's move, and no turn offered the played move. A check that fires here is reading
    something other than the defect."""
    assert _flagged_turns("v57") == set()
