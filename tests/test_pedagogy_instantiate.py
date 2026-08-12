"""Tests for guidance instantiation (the board fact that fired a theme).

The architecture review's named flaw: the pedagogy YAML can only supply abstract
prose, which the model anchors to and echoes. These facts attach the specific
reason an entry was selected — composed, never invented.
"""

from __future__ import annotations

from chess_coach.models import (
    EvalBreakdown,
    HangingPiece,
    KingSafety,
    PawnFeatures,
    PositionReport,
    Threat,
)
from chess_coach.pedagogy.inject import format_guidance_block
from chess_coach.pedagogy.instantiate import feature_facts
from chess_coach.pedagogy.resource import GuidanceEntry

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
# White up a rook, White to move; a black knight on d5 is undefended.
LEAD = "4k3/8/8/3n4/8/8/8/R3K3 w - - 0 1"


def _report(
    fen: str = START,
    *,
    hanging_white: list[HangingPiece] | None = None,
    hanging_black: list[HangingPiece] | None = None,
    pawns_white: PawnFeatures | None = None,
    threats_white: list[Threat] | None = None,
    threats_black: list[Threat] | None = None,
) -> PositionReport:
    empty = PawnFeatures([], [], [])
    return PositionReport(
        fen=fen,
        eval_cp=0,
        eval_breakdown=EvalBreakdown(material=0, mobility=0, king_safety=0, pawn_structure=0),
        hanging_pieces={"white": hanging_white or [], "black": hanging_black or []},
        threats={"white": threats_white or [], "black": threats_black or []},
        pawn_structure={"white": pawns_white or empty, "black": empty},
        king_safety={"white": KingSafety(0, ""), "black": KingSafety(0, "")},
        top_lines=[],
        tactics=[],
        threat_map=[],
        threat_map_summary=None,
        critical_moment=False,
        critical_reason=None,
    )


def test_no_false_facts_in_the_starting_position() -> None:
    # Regression: an early version asserted "you are ahead in material" and
    # "a capture is available" unconditionally — both false at move 1. A
    # fabricated fact is worse than an abstract principle, so facts are filtered
    # to the features the position actually has.
    facts = feature_facts(_report(START))
    assert "material_lead" not in facts
    assert "favorable_capture" not in facts
    assert all(isinstance(v, str) and v for v in facts.values())


def test_facts_are_emitted_for_present_features() -> None:
    facts = feature_facts(
        _report(
            LEAD,
            hanging_black=[HangingPiece(square="d5", piece="knight", color="black")],
            pawns_white=PawnFeatures(isolated=["c"], doubled=[], passed=[]),
        )
    )
    # White really is up a rook here, and the black knight really is loose.
    assert facts["material_lead"] == "you are ahead in material"
    assert facts["hanging_piece_opponent"] == "their knight on d5 is undefended"


def test_guidance_block_instantiates_the_theme_with_the_fact() -> None:
    entry = GuidanceEntry(
        id="tactic.win_hanging_piece",
        type="principle",
        theme="win the loose piece",
        focus="Free material decides most club games.",
        how_to_apply="Scan for an undefended enemy piece.",
        levels=("beginner", "intermediate", "advanced"),
        features=("hanging_piece_opponent",),
        eco_codes=(),
        citation="Heisman",
        example=None,
    )
    facts = {"hanging_piece_opponent": "their knight on d5 is undefended"}
    block = format_guidance_block([entry], level="intermediate", facts=facts)
    assert "HERE: their knight on d5 is undefended." in block
    # Without facts the entry renders exactly as before (no behaviour change).
    assert "HERE:" not in format_guidance_block([entry], level="intermediate")


def _threat(target: str) -> Threat:
    return Threat(type="attack", source_square="c1", target_squares=[target], description="d")


def test_threat_fact_names_whose_threat_it_is() -> None:
    # Regression found by reading the coach's actual output: the fact used to say
    # "there is a live threat against c8" with no side, and the model read it as
    # a danger TO the student every time — in a position where the student had
    # mate in one it wrote "your king is vulnerable if you don't act". A
    # side-ambiguous fact is not a fact.
    # LEAD has a black knight on d5 and our rook on a1, and the fact names both the
    # side holding the threat and the piece it is aimed at (see the ply-28 test).
    mine = feature_facts(_report(LEAD, threats_white=[_threat("d5")]))
    assert mine["threat_present"] == "you threaten their knight on d5"

    theirs = feature_facts(_report(LEAD, threats_black=[_threat("a1")]))
    assert theirs["threat_present"] == "the opponent threatens your rook on a1"


def test_own_threat_is_stated_in_preference_to_the_opponents() -> None:
    # When both sides have one, the student's own threat is the actionable fact.
    both = feature_facts(
        _report(LEAD, threats_white=[_threat("d5")], threats_black=[_threat("a1")]),
    )
    assert both["threat_present"] == "you threaten their knight on d5"


def test_threat_fact_names_the_piece_under_threat() -> None:
    # Found by the frontier judge at ply 28. The fact said "the opponent threatens
    # e3", and the model read the bare square as a DESTINATION, writing "your
    # opponent plays e3, winning material because your pawn on e3 is undefended" —
    # for a square our own pawn occupies. A square alone is ambiguous between
    # "threatens to move there" and "threatens what stands there".
    fen = "r1b1k1r1/pppp1p1p/4p3/6P1/1bBB4/1P2P3/P1P3nP/RN1K3R w q - 0 15"
    facts = feature_facts(_report(fen, threats_black=[_threat("e3")]))
    assert facts["threat_present"] == "the opponent threatens your pawn on e3"

    # Our own threat points at THEIR piece, and the possessive follows ownership of
    # the threat rather than the wording of the fact.
    mine = feature_facts(_report(fen, threats_white=[_threat("b4")]))
    assert mine["threat_present"] == "you threaten their bishop on b4"


def test_threat_fact_falls_back_to_the_square_when_it_is_empty() -> None:
    # A threat can be aimed at a square nobody occupies (infiltration, mate).
    # Naming a piece that is not there would be worse than being vague.
    fen = "r1b1k1r1/pppp1p1p/4p3/6P1/1bBB4/1P2P3/P1P3nP/RN1K3R w q - 0 15"
    facts = feature_facts(_report(fen, threats_black=[_threat("f3")]))
    assert facts["threat_present"] == "the opponent threatens the f3 square"
