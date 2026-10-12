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
