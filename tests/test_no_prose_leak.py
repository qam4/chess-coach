"""Definition-of-done gates for the client-side-coaching-text feature.

Feature: client-side-coaching-text (Req 2.2 / Property 3, Req 9.3 / Property 4).

- Sentinel test: every engine ``description`` field is set to a unique marker;
  the marker must appear in NO built prompt and NO template/insights output.
  This proves no consumer renders the engine's prose — every fact-derived
  sentence is composed client-side.
- Parity test: the prompt path and the template path render the SAME composer
  sentence for the same fact (both consume ``coaching_phrases``).
"""

from __future__ import annotations

import chess

from chess_coach.coaching_phrases import describe_tactic
from chess_coach.coaching_templates import (
    generate_move_coaching,
    generate_position_coaching,
    generate_position_coaching_structured,
)
from chess_coach.eval.benchmark import BenchmarkPosition, GroundTruthPoint
from chess_coach.eval.judge import (
    build_judge_prompt,
    build_pairwise_prompt,
    default_rubric_path,
    load_rubric,
)
from chess_coach.insights import extract_move_insight, render_insight_text
from chess_coach.models import (
    ComparisonReport,
    EvalBreakdown,
    HangingPiece,
    KingSafety,
    PawnFeatures,
    PositionReport,
    PVLine,
    TacticalMotif,
    Threat,
    ThreatMapEntry,
)
from chess_coach.prompts import (
    build_rich_coaching_prompt,
    build_rich_move_evaluation_prompt,
    build_socratic_prompt,
)

SENTINEL = "__ENGINE_PROSE__"
# A busy middlegame FEN (>6 pieces, so king-safety commentary is relevant).
FEN = "rnb1kbnr/pppp1ppp/4p3/6q1/4P3/2N5/PPPP1PPP/R1BQKB1R w KQkq - 2 3"


def _ks(score: int) -> KingSafety:
    # description is the sentinel; the structured fields carry the real facts.
    return KingSafety(
        score=score,
        description=SENTINEL,
        king_square="g1",
        castling_status="displaced",
        missing_shield_files=["f", "g", "h"],
        open_file_near_king=True,
        pawn_storm=True,
    )


def _report(tactics: list[TacticalMotif] | None = None) -> PositionReport:
    if tactics is None:
        tactics = [
            TacticalMotif("fork", ["e5", "c6", "g6"], ["Ne5", "Nc6", "Qg6"], False, SENTINEL),
            TacticalMotif("discovered_attack", ["c1", "g5", "d2"], ["Bc1", "Qg5", "d2"], True, SENTINEL),
        ]
    return PositionReport(
        fen=FEN,
        eval_cp=150,
        eval_breakdown=EvalBreakdown(material=100, mobility=40, king_safety=-20, pawn_structure=-10),
        hanging_pieces={
            "white": [HangingPiece("e4", "pawn", "white")],
            "black": [HangingPiece("g5", "queen", "black")],
        },
        threats={
            "white": [
                Threat("check", "e1", ["e8"], SENTINEL, uci_move="e1e8"),
                Threat("capture", "d5", ["c7"], SENTINEL, uci_move="d5c7"),
            ],
            "black": [Threat("check", "b4", ["c3"], SENTINEL, uci_move="b4c3")],
        },
        pawn_structure={
            "white": PawnFeatures(isolated=["d"], doubled=[], passed=["e"]),
            "black": PawnFeatures(isolated=[], doubled=["c"], passed=[]),
        },
        king_safety={"white": _ks(-90), "black": _ks(-70)},
        top_lines=[PVLine(depth=12, eval_cp=150, moves=["e2e4"], theme="development")],
        tactics=tactics,
        threat_map=[ThreatMapEntry("e5", "N", 1, 1, 0, 1, True)],
        threat_map_summary=SENTINEL,  # unused — must never surface
        critical_moment=False,
        critical_reason=None,
    )


def _comparison() -> ComparisonReport:
    return ComparisonReport(
        fen=FEN,
        user_move="d2d4",
        user_eval_cp=-50,
        best_move="c3d5",  # Nc3-d5, legal in FEN
        best_eval_cp=150,
        eval_drop_cp=200,
        classification="blunder",
        nag="??",
        best_move_idea="develop the kingside",  # a short label, legitimately kept
        refutation_line=None,
        missed_tactics=[TacticalMotif("pin", ["b4", "c3", "e1"], ["Bb4", "Nc3", "Ke1"], False, SENTINEL)],
        top_lines=[PVLine(depth=12, eval_cp=150, moves=["c3d5"], theme="development")],
        critical_moment=False,
        critical_reason=None,
    )


def _judge_position() -> BenchmarkPosition:
    return BenchmarkPosition(
        id="t",
        fen=FEN,
        level="intermediate",
        phase="middlegame",
        points=(GroundTruthPoint("free", "center"),),
    )


def _all_surfaces() -> dict[str, str]:
    report = _report()
    comparison = _comparison()
    before = _report()
    after = _report(tactics=[])
    insight = extract_move_insight(before, after, "d2d4", "d4")
    structured = "\n".join(s.text for s in generate_position_coaching_structured(report))
    rubric = load_rubric(default_rubric_path().parent / "rubric.v2.yaml")
    pos = _judge_position()
    return {
        "rich_coaching_prompt": build_rich_coaching_prompt(report),
        "socratic_prompt": build_socratic_prompt(report),
        "rich_move_eval_prompt": build_rich_move_evaluation_prompt(comparison),
        "template_position": generate_position_coaching(report),
        "template_position_structured": structured,
        "template_move": generate_move_coaching(comparison),
        "insight_text": render_insight_text(insight) or "",
        "judge_prompt": build_judge_prompt("resp", report, pos, rubric),
        "pairwise_judge_prompt": build_pairwise_prompt("resp A", "resp B", report, pos),
    }


def test_no_engine_prose_reaches_any_surface() -> None:
    # Req 2.2 / Property 3: the sentinel appears in NO rendered output.
    for name, output in _all_surfaces().items():
        assert SENTINEL not in output, f"engine prose leaked into {name}: {output!r}"


def test_surfaces_are_non_trivial() -> None:
    # Guard against a vacuous sentinel pass (e.g. everything returning "").
    surfaces = _all_surfaces()
    for name in ("rich_coaching_prompt", "rich_move_eval_prompt", "template_position"):
        assert len(surfaces[name]) > 50, f"{name} unexpectedly empty/short"


def test_prompt_and_template_render_the_same_tactic_sentence() -> None:
    # Req 9.3 / Property 4: both consumers emit the composer's sentence.
    tactic = TacticalMotif("fork", ["e5", "c6", "g6"], ["Ne5", "Nc6", "Qg6"], False, SENTINEL)
    report = _report(tactics=[tactic])
    expected = describe_tactic(tactic, chess.Board(report.fen))
    assert expected in build_rich_coaching_prompt(report)
    assert expected in generate_position_coaching(report)
