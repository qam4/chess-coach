"""B-021: board claims written down by a reader, checked by python-chess.

The reader (the judge, or the agent) reads a draft and writes each board claim it makes in a fixed
form; `chess_coach.eval.claims` only parses that JSON and asks the board. These tests pin the
board half on real drafts from committed transcripts, so they fail if a verdict comes out wrong,
and the reply half on a reply shaped the way the judge sends one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chess_coach.eval import claims as cl

REPO = Path(__file__).resolve().parent.parent


def _turn(run: str, ply: int) -> dict:  # type: ignore[type-arg]
    data = json.loads((REPO / "output" / run / "transcript.json").read_text(encoding="utf-8"))
    return next(t for t in data["turns"] if t["ply"] == ply)


# v60 and v61 seed 13 ply 20: the same position. v60 said "The opponent replies Qc2, capturing your
# bishop on c1", v61 "... Qc2, attacking your bishop on c1". Both passed today's gate.
_QC2 = _turn("coach_review_v60_seed13", 20)
# v61 seed 23 ply 23: "Your move left Bh6 undefended, allowing Black to capture it with Kf8."
_KF8 = _turn("coach_review_v61_seed23", 23)


def test_a_reply_that_captures_nothing_is_false_and_its_attack_is_true() -> None:
    fen = _QC2["fen_before"]
    assert _QC2["student_move_san"] == "Bc1"
    capture = {"after": ["Bc1"], "kind": "capture", "move": "Qc2", "piece": "bishop"}
    attack = {"after": ["Bc1", "Qc2"], "kind": "attacks", "square": "c2", "target": "c1"}
    legal = {"after": ["Bc1"], "kind": "legal", "move": "Qc2"}
    assert cl.evaluate(fen, capture) is False
    assert cl.evaluate(fen, attack) is True
    assert cl.evaluate(fen, legal) is True


def test_undefended_is_a_negated_defended_claim() -> None:
    fen = _QC2["fen_before"]
    # "Your move left your pawn on c3 undefended": the bishop on d2 defended it before Bc1.
    left_undefended = {"after": ["Bc1"], "kind": "defended", "square": "c3", "negated": True}
    was_defended_before = {"after": [], "kind": "defended", "square": "c3"}
    assert cl.evaluate(fen, left_undefended) is True
    assert cl.evaluate(fen, was_defended_before) is True
    assert cl.evaluate(fen, {**left_undefended, "negated": False}) is False


def test_the_kf8_turn() -> None:
    fen = _KF8["fen_before"]
    assert _KF8["student_move_san"] == "Bh6"
    assert cl.evaluate(fen, {"after": ["Bh6"], "kind": "capture", "move": "Kf8"}) is False
    assert cl.evaluate(fen, {"after": ["Bh6"], "kind": "defended", "square": "h6", "negated": True}) is True
    assert cl.evaluate(fen, {"after": ["Bh6"], "kind": "attacked", "square": "h6", "by": "black"}) is True


def test_piece_and_empty_claims_read_the_square() -> None:
    fen = _QC2["fen_before"]
    assert cl.evaluate(fen, {"after": ["Bc1"], "kind": "piece", "square": "c1", "piece": "bishop", "color": "white"})
    assert not cl.evaluate(fen, {"after": ["Bc1"], "kind": "piece", "square": "c1", "piece": "knight"})
    black_bishop = {"after": ["Bc1"], "kind": "piece", "square": "c1", "piece": "bishop", "color": "black"}
    assert not cl.evaluate(fen, black_bishop)
    assert cl.evaluate(fen, {"after": ["Bc1"], "kind": "empty", "square": "d2"}) is True


def test_a_claim_the_board_cannot_be_asked_is_none_not_false() -> None:
    """A malformed claim is the reader's error, not the coach's, so it must not count as false."""
    fen = _QC2["fen_before"]
    assert cl.evaluate(fen, {"after": ["Zz9"], "kind": "empty", "square": "d2"}) is None
    assert cl.evaluate(fen, {"after": ["Bc1"], "kind": "no such kind"}) is None
    assert cl.evaluate(fen, {"after": ["Bc1"], "kind": "empty", "square": "z9"}) is None
    assert cl.evaluate(fen, {"after": ["Bc1"], "kind": "defended", "square": "e4"}) is None  # e4 is empty


def test_illegal_named_move_is_false() -> None:
    fen = _QC2["fen_before"]
    # After Bc1 it is Black to move, and White's Bd2 is not a move Black can play.
    assert cl.evaluate(fen, {"after": ["Bc1"], "kind": "legal", "move": "Bd2"}) is False


def test_mate_and_check() -> None:
    fen = "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1"
    assert cl.evaluate(fen, {"after": [], "kind": "mate", "move": "Ra8"}) is True
    assert cl.evaluate(fen, {"after": [], "kind": "check", "move": "Ra8"}) is True
    assert cl.evaluate(fen, {"after": [], "kind": "mate", "move": "Ra7"}) is False


def test_a_pin_to_a_piece_other_than_the_king_is_a_pin() -> None:
    """v62 seed 23 ply 33, "the pin involving c5 and c6": Qc5 pins Nc6 to the bishop on c8.

    The first `pinned` test asked only for a pin to the king, so this draft read as false while the
    pin is on the board. Geometry only: which piece is worth more is the engine's question.
    """
    fen = "2bk3r/1p4p1/B1n1p2n/p1Q1p2p/3Pp3/8/PP3PPP/1R1K2NR w - - 0 19"
    assert cl.evaluate(fen, {"after": [], "kind": "pinned", "square": "c6"}) is True
    # Qa1 hits the knight on c3 along the diagonal: a pin with the bishop on e5 behind it, none without.
    assert cl.evaluate("4k3/8/8/4b3/8/2n5/8/Q3K3 w - - 0 1", {"after": [], "kind": "pinned", "square": "c3"}) is True
    assert cl.evaluate("4k3/8/8/8/8/2n5/8/Q3K3 w - - 0 1", {"after": [], "kind": "pinned", "square": "c3"}) is False


def test_passed_and_isolated_pawns() -> None:
    fen = "4k3/8/8/3P4/8/8/P7/4K3 w - - 0 1"
    assert cl.evaluate(fen, {"after": [], "kind": "passed", "square": "d5"}) is True
    assert cl.evaluate(fen, {"after": [], "kind": "isolated", "square": "a2"}) is True
    blocked = "4k3/2p5/8/3P4/8/8/PP6/4K3 w - - 0 1"  # c7 stops d5; b2 neighbours a2
    assert cl.evaluate(blocked, {"after": [], "kind": "passed", "square": "d5"}) is False
    assert cl.evaluate(blocked, {"after": [], "kind": "isolated", "square": "a2"}) is False


def test_a_draft_is_false_when_any_claim_is() -> None:
    assert cl.draft_verdict([True, True]) == cl.CLEAN
    assert cl.draft_verdict([]) == cl.CLEAN
    assert cl.draft_verdict([True, False, None]) == cl.FALSE
    assert cl.draft_verdict([True, None]) == cl.UNRESOLVED


def test_distinct_drafts_once_each_in_order() -> None:
    """A retry that repeated the blocked draft word for word is one draft to read, not two."""
    transcript = {
        "turns": [
            {"ply": 4, "fen_before": "f", "student_move_san": "e4", "drafts": ["a", "a"]},
            {"ply": 6, "fen_before": "g", "student_move_san": "d4", "drafts": ["b", "c"]},
            {"ply": 8, "fen_before": "h", "student_move_san": "c4", "drafts": []},
        ]
    }
    got = cl.drafts_of(transcript, seed=7)
    assert [(d.id, d.text) for d in got] == [("7:4:0", "a"), ("7:6:0", "b"), ("7:6:1", "c")]


def test_the_prompt_carries_every_draft_and_its_position() -> None:
    drafts = cl.drafts_of({"turns": [_QC2 | {"drafts": ["first text", "second text"]}]}, seed=13)
    prompt = cl.build_claims_prompt(drafts)
    for d in drafts:
        assert d.id in prompt
        assert d.text in prompt
    assert _QC2["fen_before"] in prompt
    assert "Student plays White" in prompt
    # Every kind the evaluator knows is offered to the reader, and no other.
    for kind in cl.KINDS:
        assert f"- {kind}:" in prompt


def test_reply_parsing_reads_the_json_object_out_of_a_fenced_reply() -> None:
    reply = (
        "Here you go.\n```json\n"
        + json.dumps(
            {
                "drafts": [
                    {
                        "id": "13:20:0",
                        "claims": [{"sentence": "s", "after": ["Bc1"], "kind": "capture", "move": "Qc2"}],
                        "unchecked": ["Something about tempo."],
                    }
                ]
            }
        )
        + "\n```\n"
    )
    parsed = cl.parse_claims_reply(reply)
    assert list(parsed) == ["13:20:0"]
    assert parsed["13:20:0"].claims[0]["move"] == "Qc2"
    assert parsed["13:20:0"].unchecked == ["Something about tempo."]


def test_reply_without_drafts_raises() -> None:
    with pytest.raises(cl.ClaimsParseError):
        cl.parse_claims_reply('{"nothing": 1}')


def test_reading_scores_each_draft_and_counts_a_missing_one() -> None:
    drafts = cl.drafts_of({"turns": [_QC2 | {"drafts": ["false text", "true text"]}]}, seed=13)
    reply = {
        "13:20:0": cl.ReadDraft(
            claims=[{"sentence": "s", "after": ["Bc1"], "kind": "capture", "move": "Qc2", "piece": "bishop"}],
            unchecked=[],
        ),
    }
    scored = cl.score_reading(drafts, reply)
    assert scored["13:20:0"]["verdict"] == cl.FALSE
    assert scored["13:20:0"]["claims"][0]["holds"] is False
    assert scored["13:20:1"]["verdict"] == cl.MISSING


def test_agreement_counts_drafts_called_false_by_one_reader_only() -> None:
    a = {"x": cl.FALSE, "y": cl.CLEAN, "z": cl.CLEAN, "w": cl.MISSING}
    b = {"x": cl.FALSE, "y": cl.FALSE, "z": cl.UNRESOLVED, "w": cl.CLEAN}
    compared, differ = cl.disagreements(a, b)
    assert compared == 3  # a draft one reader never read is not compared
    assert differ == ["y"]
