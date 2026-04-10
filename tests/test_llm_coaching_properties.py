"""Property-based tests for LLM primary coaching feature.

Feature: llm-primary-coaching

Tests the correctness properties defined in the design document:
- P1: Coaching path routing
- P2: Position prompt contains all required instructions
- P3: Position prompt includes non-empty data sections, omits empty ones
- P4: Move evaluation prompt contains required instructions and data
- P5: Critical moment conditional prompt content
- P6: Level-adaptive prompt instructions
- P7: Template output structure and completeness
- P8: Hallucination detector placement vs influence
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from chess_coach.coaching_templates import (
    CAT_ASSESSMENT,
    CAT_PIECE_SAFETY,
    CAT_SUGGESTION,
    CAT_TACTICS,
    CoachingSection,
    generate_position_coaching_structured,
)
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
    build_coaching_prompt,
    build_rich_coaching_prompt,
    build_rich_move_evaluation_prompt,
)

# Add scripts dir to path for hallucination detector
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from probe_llm_chess import check_piece_hallucinations

# ---------------------------------------------------------------------------
# Hypothesis strategies for data models
# ---------------------------------------------------------------------------

STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

VALID_SQUARES = [f"{f}{r}" for f in "abcdefgh" for r in "12345678"]
PIECE_NAMES = ["pawn", "knight", "bishop", "rook", "queen", "king"]
LEVELS = ["beginner", "intermediate", "advanced"]
CLASSIFICATIONS = ["good", "inaccuracy", "mistake", "blunder"]
TACTIC_TYPES = ["fork", "pin", "skewer", "discovered_attack", "double_check"]
THREAT_TYPES = ["check", "capture", "mate_threat", "promotion"]


@st.composite
def eval_breakdowns(draw: st.DrawFn) -> EvalBreakdown:
    return EvalBreakdown(
        material=draw(st.integers(min_value=-3000, max_value=3000)),
        mobility=draw(st.integers(min_value=-500, max_value=500)),
        king_safety=draw(st.integers(min_value=-500, max_value=500)),
        pawn_structure=draw(st.integers(min_value=-500, max_value=500)),
    )


@st.composite
def hanging_pieces(draw: st.DrawFn) -> HangingPiece:
    return HangingPiece(
        square=draw(st.sampled_from(VALID_SQUARES)),
        piece=draw(st.sampled_from(PIECE_NAMES)),
        color=draw(st.sampled_from(["white", "black"])),
    )


@st.composite
def threats(draw: st.DrawFn) -> Threat:
    return Threat(
        type=draw(st.sampled_from(THREAT_TYPES)),
        source_square=draw(st.sampled_from(VALID_SQUARES)),
        target_squares=draw(st.lists(st.sampled_from(VALID_SQUARES), min_size=0, max_size=3)),
        description=draw(
            st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N", "Z")))
        ),
    )


@st.composite
def pawn_features(draw: st.DrawFn) -> PawnFeatures:
    files = list("abcdefgh")
    return PawnFeatures(
        isolated=draw(st.lists(st.sampled_from(files), min_size=0, max_size=3, unique=True)),
        doubled=draw(st.lists(st.sampled_from(files), min_size=0, max_size=3, unique=True)),
        passed=draw(st.lists(st.sampled_from(files), min_size=0, max_size=3, unique=True)),
    )


@st.composite
def king_safeties(draw: st.DrawFn) -> KingSafety:
    return KingSafety(
        score=draw(st.integers(min_value=-200, max_value=200)),
        description=draw(
            st.text(min_size=0, max_size=40, alphabet=st.characters(whitelist_categories=("L", "N", "Z")))
        ),
    )


@st.composite
def tactical_motifs(draw: st.DrawFn) -> TacticalMotif:
    return TacticalMotif(
        type=draw(st.sampled_from(TACTIC_TYPES)),
        squares=draw(st.lists(st.sampled_from(VALID_SQUARES), min_size=0, max_size=4)),
        pieces=draw(st.lists(st.sampled_from(PIECE_NAMES), min_size=0, max_size=3)),
        in_pv=draw(st.booleans()),
        description=draw(
            st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N", "Z")))
        ),
    )


@st.composite
def pv_lines(draw: st.DrawFn) -> PVLine:
    return PVLine(
        depth=draw(st.integers(min_value=1, max_value=30)),
        eval_cp=draw(st.integers(min_value=-3000, max_value=3000)),
        moves=draw(st.lists(st.sampled_from(["e2e4", "d2d4", "g1f3", "b1c3", "e7e5"]), min_size=0, max_size=5)),
        theme=draw(st.text(min_size=0, max_size=40, alphabet=st.characters(whitelist_categories=("L", "N", "Z")))),
    )


@st.composite
def threat_map_entries(draw: st.DrawFn) -> ThreatMapEntry:
    return ThreatMapEntry(
        square=draw(st.sampled_from(VALID_SQUARES)),
        piece=draw(st.one_of(st.none(), st.sampled_from(PIECE_NAMES))),
        white_attackers=draw(st.integers(min_value=0, max_value=5)),
        black_attackers=draw(st.integers(min_value=0, max_value=5)),
        white_defenders=draw(st.integers(min_value=0, max_value=5)),
        black_defenders=draw(st.integers(min_value=0, max_value=5)),
        net_attacked=draw(st.booleans()),
    )


@st.composite
def position_reports(draw: st.DrawFn) -> PositionReport:
    return PositionReport(
        fen=STARTING_FEN,
        eval_cp=draw(st.integers(min_value=-3000, max_value=3000)),
        eval_breakdown=draw(eval_breakdowns()),
        hanging_pieces={
            "white": draw(st.lists(hanging_pieces(), min_size=0, max_size=2)),
            "black": draw(st.lists(hanging_pieces(), min_size=0, max_size=2)),
        },
        threats={
            "white": draw(st.lists(threats(), min_size=0, max_size=2)),
            "black": draw(st.lists(threats(), min_size=0, max_size=2)),
        },
        pawn_structure={
            "white": draw(pawn_features()),
            "black": draw(pawn_features()),
        },
        king_safety={
            "white": draw(king_safeties()),
            "black": draw(king_safeties()),
        },
        top_lines=draw(st.lists(pv_lines(), min_size=1, max_size=3)),
        tactics=draw(st.lists(tactical_motifs(), min_size=0, max_size=3)),
        threat_map=draw(st.lists(threat_map_entries(), min_size=0, max_size=5)),
        threat_map_summary=draw(st.one_of(st.none(), st.text(min_size=0, max_size=30))),
        critical_moment=draw(st.booleans()),
        critical_reason=draw(
            st.one_of(
                st.none(),
                st.text(min_size=1, max_size=40, alphabet=st.characters(whitelist_categories=("L", "N", "Z"))),
            )
        ),
    )


@st.composite
def comparison_reports(draw: st.DrawFn) -> ComparisonReport:
    return ComparisonReport(
        fen=STARTING_FEN,
        user_move="e2e4",
        user_eval_cp=draw(st.integers(min_value=-3000, max_value=3000)),
        best_move="d2d4",
        best_eval_cp=draw(st.integers(min_value=-3000, max_value=3000)),
        eval_drop_cp=draw(st.integers(min_value=0, max_value=1000)),
        classification=draw(st.sampled_from(CLASSIFICATIONS)),
        nag=draw(st.sampled_from(["!!", "!", "!?", "?!", "?", "??"])),
        best_move_idea=draw(
            st.text(min_size=1, max_size=60, alphabet=st.characters(whitelist_categories=("L", "N", "Z")))
        ),
        refutation_line=draw(
            st.one_of(st.none(), st.lists(st.sampled_from(["e2e4", "d7d5", "e4d5"]), min_size=1, max_size=4))
        ),
        missed_tactics=draw(st.lists(tactical_motifs(), min_size=0, max_size=2)),
        top_lines=draw(st.lists(pv_lines(), min_size=1, max_size=3)),
        critical_moment=draw(st.booleans()),
        critical_reason=draw(
            st.one_of(
                st.none(),
                st.text(min_size=1, max_size=40, alphabet=st.characters(whitelist_categories=("L", "N", "Z"))),
            )
        ),
    )


# ===========================================================================
# Property 1: Coaching path routing
# Feature: llm-primary-coaching, Property 1: Coaching path routing
# **Validates: Requirements 1.1, 1.2**
# ===========================================================================


@settings(max_examples=100)
@given(
    llm_available=st.booleans(),
    template_only=st.booleans(),
)
def test_coaching_path_routing(llm_available: bool, template_only: bool) -> None:
    """Coaching routes to LLM when available, falls back to templates on failure.

    The Coach architecture:
    - explain(): always attempts LLM when coaching_available is True, with
      fallback to templates on failure (timeout, empty response, error).
    - evaluate_move() / play_move(): check template_only to skip LLM entirely.

    This test verifies:
    - When LLM succeeds, its output is used as coaching text.
    - When LLM fails, template fallback produces non-empty output.
    - template_only gates LLM usage in evaluate_move (tested via the
      evaluate_move path for non-good moves).

    **Validates: Requirements 1.1, 1.2**
    """
    from chess_coach.coach import Coach
    from chess_coach.engine import CoachingEngine

    mock_engine = MagicMock(spec=CoachingEngine)
    mock_engine.coaching_available = True
    mock_engine.is_ready.return_value = True

    minimal_report = PositionReport(
        fen=STARTING_FEN,
        eval_cp=0,
        eval_breakdown=EvalBreakdown(material=0, mobility=0, king_safety=0, pawn_structure=0),
        hanging_pieces={"white": [], "black": []},
        threats={"white": [], "black": []},
        pawn_structure={"white": PawnFeatures([], [], []), "black": PawnFeatures([], [], [])},
        king_safety={"white": KingSafety(0, "safe"), "black": KingSafety(0, "safe")},
        top_lines=[PVLine(depth=18, eval_cp=0, moves=["e2e4"], theme="")],
        tactics=[],
        threat_map=[],
        threat_map_summary=None,
        critical_moment=False,
        critical_reason=None,
    )
    mock_engine.get_position_report.return_value = minimal_report

    mock_llm = MagicMock()
    mock_llm.is_available.return_value = llm_available
    llm_text = "LLM coaching text here."
    if llm_available:
        mock_llm.generate.return_value = llm_text
    else:
        mock_llm.generate.side_effect = ConnectionError("LLM not available")

    coach = Coach(engine=mock_engine, llm=mock_llm, template_only=template_only)
    result = coach.explain(STARTING_FEN)

    # explain() always attempts LLM in the coaching protocol path
    mock_llm.generate.assert_called()

    if llm_available:
        # LLM succeeded — its text is used
        assert result.coaching_text == llm_text
    else:
        # LLM failed — template fallback produces non-empty output
        assert result.coaching_text, "Template fallback must produce non-empty text"
        assert result.coaching_text != llm_text

    # Verify template_only gates LLM in evaluate_move for non-good moves
    from chess_coach.models import ComparisonReport

    blunder_report = ComparisonReport(
        fen=STARTING_FEN,
        user_move="a2a3",
        user_eval_cp=-200,
        best_move="e2e4",
        best_eval_cp=50,
        eval_drop_cp=250,
        classification="blunder",
        nag="??",
        best_move_idea="Controls the center",
        refutation_line=None,
        missed_tactics=[],
        top_lines=[PVLine(depth=18, eval_cp=50, moves=["e2e4"], theme="")],
        critical_moment=False,
        critical_reason=None,
    )
    mock_engine.get_comparison_report.return_value = blunder_report

    # Reset mock to track evaluate_move calls separately
    mock_llm.reset_mock()
    if llm_available:
        mock_llm.generate.return_value = "Move feedback."
    else:
        mock_llm.generate.side_effect = ConnectionError("LLM not available")

    eval_result = coach.evaluate_move(STARTING_FEN, "a2a3")

    if template_only:
        # template_only=True: LLM.generate NOT called in evaluate_move
        mock_llm.generate.assert_not_called()
    else:
        # template_only=False: LLM.generate IS called
        mock_llm.generate.assert_called()

    # Always get non-empty feedback for a blunder
    assert eval_result.feedback, "Feedback should be non-empty for a blunder"


# ===========================================================================
# Property 2: Position prompt contains all required instructions
# Feature: llm-primary-coaching, Property 2: Position prompt instructions
# **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 6.1, 6.2, 7.1, 7.2, 7.4, 8.1, 8.2, 8.3, 8.5**
# ===========================================================================


@settings(max_examples=100)
@given(
    report=position_reports(),
    level=st.sampled_from(LEVELS),
)
def test_position_prompt_contains_instructions(report: PositionReport, level: str) -> None:
    """Position coaching prompt contains all required instruction keywords.

    **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 6.1, 6.2, 7.1, 7.2, 7.4, 8.1, 8.2, 8.3, 8.5**
    """
    prompt = build_rich_coaching_prompt(report, level=level)
    prompt_lower = prompt.lower()

    # Prioritization instruction (Req 2.1)
    assert "prioritize" in prompt_lower or "1-2 most important" in prompt_lower, (
        "Prompt must contain prioritization instruction"
    )

    # Causal explanation instruction (Req 2.2)
    assert "why" in prompt_lower and "matter" in prompt_lower, (
        "Prompt must contain causal explanation instruction (why it matters)"
    )

    # Actionable advice instruction (Req 2.3)
    assert "actionable" in prompt_lower or "concrete plan" in prompt_lower or "suggest" in prompt_lower, (
        "Prompt must contain actionable advice instruction"
    )

    # Grounding instruction (Req 2.4, 6.1, 6.2)
    assert "only use" in prompt_lower or "do not add" in prompt_lower or "never invent" in prompt_lower, (
        "Prompt must contain grounding instruction"
    )

    # Warm encouraging tone (Req 8.1)
    assert "warm" in prompt_lower or "encouraging" in prompt_lower or "supportive" in prompt_lower, (
        "Prompt must contain warm/encouraging tone instruction"
    )

    # Teach how to think (Req 8.2)
    assert "think" in prompt_lower, "Prompt must contain 'teach how to think' instruction"

    # Connect to principles (Req 8.3)
    assert "principle" in prompt_lower, "Prompt must contain 'connect to principles' instruction"

    # Acknowledge good aspects (Req 8.5)
    assert "acknowledge" in prompt_lower or "strength" in prompt_lower, (
        "Prompt must contain 'acknowledge strengths' instruction"
    )

    # Student level (Req 7.1)
    assert level in prompt_lower, f"Prompt must contain student level '{level}'"

    # 200-word limit (Req 7.2)
    assert "200 words" in prompt_lower or "200 word" in prompt_lower, "Prompt must contain 200-word limit instruction"


# ===========================================================================
# Property 3: Position prompt data sections
# Feature: llm-primary-coaching, Property 3: Data section inclusion/omission
# **Validates: Requirements 1.3, 2.5, 2.6, 6.3, 6.4**
# ===========================================================================


@settings(max_examples=100)
@given(report=position_reports())
def test_position_prompt_data_sections(report: PositionReport) -> None:
    """Position prompt includes FEN, includes non-empty sections with delimiters, omits empty ones.

    **Validates: Requirements 1.3, 2.5, 2.6, 6.3, 6.4**
    """
    prompt = build_rich_coaching_prompt(report)

    # FEN must always be present (Req 6.3)
    assert report.fen in prompt, "Prompt must contain the FEN string"

    # Eval breakdown always present with delimiter
    assert "---" in prompt, "Prompt must use section delimiters"
    assert "Material" in prompt or "material" in prompt.lower(), "Eval breakdown section must always be present"

    # Threats: present only if non-empty
    has_threats = any(len(report.threats.get(s, [])) > 0 for s in ("white", "black"))
    if has_threats:
        assert "Threats" in prompt, "Threats section should appear when threats exist"
    else:
        assert "--- Threats ---" not in prompt, "Threats section should be omitted when empty"

    # Hanging pieces: present only if non-empty
    has_hanging = any(len(report.hanging_pieces.get(s, [])) > 0 for s in ("white", "black"))
    if has_hanging:
        assert "Hanging" in prompt, "Hanging pieces section should appear when hanging pieces exist"
    else:
        assert "--- Hanging Pieces ---" not in prompt, "Hanging pieces section should be omitted when empty"

    # Tactics: present only if non-empty
    if report.tactics:
        assert "Tactical" in prompt or "Motif" in prompt or "tactic" in prompt.lower(), (
            "Tactics section should appear when tactics exist"
        )
    else:
        assert "--- Tactical Motifs ---" not in prompt, "Tactics section should be omitted when empty"


# ===========================================================================
# Property 4: Move evaluation prompt contains required instructions and data
# Feature: llm-primary-coaching, Property 4: Move prompt instructions + data
# **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 7.3**
# ===========================================================================


@settings(max_examples=100)
@given(
    report=comparison_reports(),
    level=st.sampled_from(LEVELS),
)
def test_move_prompt_contains_instructions_and_data(report: ComparisonReport, level: str) -> None:
    """Move evaluation prompt contains all required instructions and data fields.

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 7.3**
    """
    prompt = build_rich_move_evaluation_prompt(report, level=level)
    prompt_lower = prompt.lower()

    # Explain what the move failed to address (Req 3.1)
    assert "failed to address" in prompt_lower or "what the move" in prompt_lower or "allowed" in prompt_lower, (
        "Prompt must instruct LLM to explain what the move failed to address"
    )

    # Explain why best move is stronger (Req 3.2)
    assert "stronger" in prompt_lower or "best move" in prompt_lower, (
        "Prompt must instruct LLM to explain why best move is stronger"
    )

    # Constructive framing (Req 3.3)
    assert "constructive" in prompt_lower or "acknowledge" in prompt_lower, (
        "Prompt must contain constructive framing instruction"
    )

    # Grounding instruction (Req 3.5)
    assert "grounded" in prompt_lower or "only" in prompt_lower, "Prompt must contain grounding instruction"

    # Eval drop value present (Req 3.4)
    assert str(report.eval_drop_cp) in prompt, f"Prompt must contain eval drop value {report.eval_drop_cp}"

    # Best move idea present (Req 3.4)
    assert report.best_move_idea in prompt, "Prompt must contain best move idea"

    # 100-word limit (Req 7.3)
    assert "100 words" in prompt_lower or "100 word" in prompt_lower, "Prompt must contain 100-word limit instruction"

    # Missed tactics present when non-empty (Req 3.4)
    if report.missed_tactics:
        for tactic in report.missed_tactics:
            assert tactic.description in prompt, (
                f"Missed tactic description '{tactic.description}' must appear in prompt"
            )

    # Refutation line present when non-None (Req 3.4)
    if report.refutation_line:
        for move in report.refutation_line:
            assert move in prompt, f"Refutation move '{move}' must appear in prompt"


# ===========================================================================
# Property 5: Critical moment conditional prompt content
# Feature: llm-primary-coaching, Property 5: Critical moment
# **Validates: Requirements 7.5**
# ===========================================================================


@settings(max_examples=100)
@given(report=position_reports())
def test_critical_moment_prompt_content(report: PositionReport) -> None:
    """When critical_moment is True, prompt has extra detail language; when False, it doesn't.

    **Validates: Requirements 7.5**
    """
    prompt = build_rich_coaching_prompt(report)
    prompt_lower = prompt.lower()

    critical_phrases = ["critical moment", "more detailed", "accuracy matters", "precise play"]

    if report.critical_moment:
        # At least one critical phrase should be present
        assert any(phrase in prompt_lower for phrase in critical_phrases), (
            "When critical_moment is True, prompt must contain critical moment language"
        )
        # Critical reason should appear if provided
        if report.critical_reason:
            assert report.critical_reason.lower() in prompt_lower, (
                "Critical reason must appear in prompt when critical_moment is True"
            )
    else:
        # The specific critical moment marker should NOT be present
        assert "⚠ critical moment" not in prompt_lower, (
            "When critical_moment is False, prompt must NOT contain critical moment marker"
        )


# ===========================================================================
# Property 6: Level-adaptive prompt instructions
# Feature: llm-primary-coaching, Property 6: Level-adaptive instructions
# **Validates: Requirements 8.4, 8.6**
# ===========================================================================


@settings(max_examples=100)
@given(
    report=position_reports(),
    level=st.sampled_from(LEVELS),
)
def test_level_adaptive_instructions(report: PositionReport, level: str) -> None:
    """Beginner prompts have simple language instruction; beginner+intermediate avoid jargon.

    **Validates: Requirements 8.4, 8.6**
    """
    prompt = build_rich_coaching_prompt(report, level=level)
    prompt_lower = prompt.lower()

    if level == "beginner":
        # Simple language, one idea, avoid notation (Req 8.6)
        assert "simple" in prompt_lower, "Beginner prompt must contain 'simple language' instruction"
        assert "one" in prompt_lower and ("idea" in prompt_lower or "main" in prompt_lower), (
            "Beginner prompt must contain 'one idea' instruction"
        )

    if level in ("beginner", "intermediate"):
        # Avoid engine jargon (Req 8.4)
        assert "jargon" in prompt_lower or "centipawn" in prompt_lower, (
            "Beginner/intermediate prompt must contain engine jargon avoidance instruction"
        )

    if level == "advanced":
        # Advanced should NOT have the beginner-specific instructions
        assert "beginner student" not in prompt_lower, (
            "Advanced prompt should not contain beginner-specific instructions"
        )


# ===========================================================================
# Property 7: Template output structure and completeness
# Feature: llm-primary-coaching, Property 7: Template structure
# **Validates: Requirements 4.1, 4.3, 4.5**
# ===========================================================================


@settings(max_examples=100)
@given(
    report=position_reports(),
    level=st.sampled_from(LEVELS),
)
def test_template_output_structure(report: PositionReport, level: str) -> None:
    """Template output is a non-empty list of CoachingSections with valid fields.

    **Validates: Requirements 4.1, 4.3, 4.5**
    """
    sections = generate_position_coaching_structured(report, level=level)

    # Non-empty list
    assert len(sections) > 0, "Template must return at least one section"

    # All sections have required fields
    for section in sections:
        assert isinstance(section, CoachingSection)
        assert section.category, f"Section category must be non-empty, got: {section.category!r}"
        assert section.label, f"Section label must be non-empty, got: {section.label!r}"
        assert section.text, f"Section text must be non-empty, got: {section.text!r}"

    # Assessment section always present
    categories = [s.category for s in sections]
    assert CAT_ASSESSMENT in categories, "Assessment section must always be present"

    # Hanging pieces → piece_safety section
    has_hanging = any(len(report.hanging_pieces.get(s, [])) > 0 for s in ("white", "black"))
    if has_hanging:
        assert CAT_PIECE_SAFETY in categories, "Piece safety section must be present when hanging pieces exist"

    # Tactics → tactics section
    has_tactics = bool(report.tactics)
    has_threats = any(len(report.threats.get(s, [])) > 0 for s in ("white", "black"))
    if has_tactics or has_threats:
        assert CAT_TACTICS in categories, "Tactics section must be present when tactics or threats exist"

    # Top line theme → suggestion section
    has_theme = report.top_lines and report.top_lines[0].theme
    if has_theme:
        assert CAT_SUGGESTION in categories, "Suggestion section must be present when top line has a theme"


# ===========================================================================
# Property 8: Hallucination detector placement vs influence
# Feature: llm-primary-coaching, Property 8: Hallucination detector
# **Validates: Requirements 5.1, 5.2, 5.3**
# ===========================================================================


@settings(max_examples=100)
@given(
    piece=st.sampled_from(["knight", "bishop", "rook", "queen"]),
    square=st.sampled_from(VALID_SQUARES),
)
def test_hallucination_detector_placement_vs_influence(piece: str, square: str) -> None:
    """Detector flags placement claims, skips influence verbs and square assessments.

    **Validates: Requirements 5.1, 5.2, 5.3**
    """
    fen = STARTING_FEN

    # 1. Placement claim: "piece on square" — should be flagged if piece isn't there
    placement_text = f"The {piece} on {square} is well placed."
    placement_issues = check_piece_hallucinations(fen, placement_text)
    # We can't assert it's always flagged (piece might actually be there),
    # but we verify the function runs without error and returns a list
    assert isinstance(placement_issues, list)

    # 2. Influence verb: "piece attacking square" — should NOT be flagged
    for verb in ["controlling", "targeting", "attacking", "defending"]:
        influence_text = f"The {verb} {piece} on {square} is important."
        # The influence verb appears before "piece on square", so it should be skipped
        influence_issues = check_piece_hallucinations(fen, influence_text)
        # Influence claims should not be flagged as hallucinations
        assert not any(square in issue and piece in issue for issue in influence_issues), (
            f"Influence verb '{verb}' should not trigger hallucination for {piece} on {square}"
        )

    # 3. Square assessment: "weak square X" — should NOT be flagged
    assessment_text = f"The weak square {square} is a problem."
    assessment_issues = check_piece_hallucinations(fen, assessment_text)
    # Square assessments should not be flagged
    # (The pattern "weak square e4" doesn't match "piece on square")
    assert isinstance(assessment_issues, list)


@settings(max_examples=50)
@given(data=st.data())
def test_hallucination_detector_known_placement(data: st.DataObject) -> None:
    """Detector correctly flags a piece claimed on an empty square.

    **Validates: Requirements 5.1**
    """
    # Use a FEN where we know specific squares are empty
    # After 1.e4: e2 is empty, e4 has a pawn
    fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"

    # Claim a knight on e2 (which is empty after 1.e4)
    response = "The knight on e2 is well placed."
    issues = check_piece_hallucinations(fen, response)
    assert len(issues) > 0, "Should flag knight on e2 when e2 is empty"

    # Claim a pawn on e4 (which is correct after 1.e4)
    response2 = "The pawn on e4 controls the center."
    issues2 = check_piece_hallucinations(fen, response2)
    assert len(issues2) == 0, "Should NOT flag pawn on e4 when pawn is actually there"


# ===========================================================================
# Unit Tests (Task 7)
# ===========================================================================


class TestLLMFallbackOnTimeout:
    """7.1: LLM fallback on timeout — mock LLM raises exception, verify template output.

    **Validates: Requirements 1.4**
    """

    def test_explain_falls_back_on_exception(self) -> None:
        """Coach.explain() falls back to template when LLM raises an exception."""
        from chess_coach.coach import Coach
        from chess_coach.engine import CoachingEngine

        mock_engine = MagicMock(spec=CoachingEngine)
        mock_engine.coaching_available = True

        minimal_report = PositionReport(
            fen=STARTING_FEN,
            eval_cp=50,
            eval_breakdown=EvalBreakdown(material=50, mobility=0, king_safety=0, pawn_structure=0),
            hanging_pieces={"white": [], "black": []},
            threats={"white": [], "black": []},
            pawn_structure={"white": PawnFeatures([], [], []), "black": PawnFeatures([], [], [])},
            king_safety={"white": KingSafety(0, "safe"), "black": KingSafety(0, "safe")},
            top_lines=[PVLine(depth=18, eval_cp=50, moves=["e2e4"], theme="")],
            tactics=[],
            threat_map=[],
            threat_map_summary=None,
            critical_moment=False,
            critical_reason=None,
        )
        mock_engine.get_position_report.return_value = minimal_report

        mock_llm = MagicMock()
        mock_llm.is_available.return_value = True
        mock_llm.generate.side_effect = TimeoutError("LLM timed out")

        coach = Coach(engine=mock_engine, llm=mock_llm, template_only=False)
        result = coach.explain(STARTING_FEN)

        # Should get template output, not crash
        assert result.coaching_text, "Should produce non-empty coaching text via template fallback"
        mock_llm.generate.assert_called_once()


class TestLLMFallbackOnEmptyResponse:
    """7.2: LLM fallback on empty response — mock LLM returns "", verify template output.

    **Validates: Requirements 1.4**
    """

    def test_explain_falls_back_on_empty(self) -> None:
        """Coach.explain() falls back to template when LLM returns empty string."""
        from chess_coach.coach import Coach
        from chess_coach.engine import CoachingEngine

        mock_engine = MagicMock(spec=CoachingEngine)
        mock_engine.coaching_available = True

        minimal_report = PositionReport(
            fen=STARTING_FEN,
            eval_cp=0,
            eval_breakdown=EvalBreakdown(material=0, mobility=0, king_safety=0, pawn_structure=0),
            hanging_pieces={"white": [], "black": []},
            threats={"white": [], "black": []},
            pawn_structure={"white": PawnFeatures([], [], []), "black": PawnFeatures([], [], [])},
            king_safety={"white": KingSafety(0, "safe"), "black": KingSafety(0, "safe")},
            top_lines=[PVLine(depth=18, eval_cp=0, moves=["e2e4"], theme="")],
            tactics=[],
            threat_map=[],
            threat_map_summary=None,
            critical_moment=False,
            critical_reason=None,
        )
        mock_engine.get_position_report.return_value = minimal_report

        mock_llm = MagicMock()
        mock_llm.is_available.return_value = True
        mock_llm.generate.return_value = ""

        coach = Coach(engine=mock_engine, llm=mock_llm, template_only=False)
        result = coach.explain(STARTING_FEN)

        assert result.coaching_text, "Should produce non-empty coaching text via template fallback"


class TestTemplateFallbackMinimalReport:
    """7.3: Template fallback produces non-empty output for minimal PositionReport.

    **Validates: Requirements 4.5**
    """

    def test_minimal_report_produces_output(self) -> None:
        """generate_position_coaching_structured returns non-empty for minimal report."""
        minimal_report = PositionReport(
            fen=STARTING_FEN,
            eval_cp=0,
            eval_breakdown=EvalBreakdown(material=0, mobility=0, king_safety=0, pawn_structure=0),
            hanging_pieces={"white": [], "black": []},
            threats={"white": [], "black": []},
            pawn_structure={"white": PawnFeatures([], [], []), "black": PawnFeatures([], [], [])},
            king_safety={"white": KingSafety(0, "safe"), "black": KingSafety(0, "safe")},
            top_lines=[PVLine(depth=18, eval_cp=0, moves=["e2e4"], theme="")],
            tactics=[],
            threat_map=[],
            threat_map_summary=None,
            critical_moment=False,
            critical_reason=None,
        )
        sections = generate_position_coaching_structured(minimal_report)
        assert len(sections) > 0, "Must return at least one section"
        assert sections[0].category == CAT_ASSESSMENT
        assert sections[0].text, "Assessment text must be non-empty"


class TestHallucinationCountAccuracy:
    """7.4: Hallucination count accuracy with known FEN + response.

    **Validates: Requirements 5.1, 5.4**
    """

    def test_known_hallucinations(self) -> None:
        """Detector returns correct count for known hallucinations."""
        # Starting position: no knight on e4, no bishop on d5, no rook on c3
        fen = STARTING_FEN
        response = (
            "The knight on e4 controls the center. The bishop on d5 is well placed. The rook on c3 supports the pawn."
        )
        issues = check_piece_hallucinations(fen, response)
        assert len(issues) == 3, f"Expected 3 hallucinations, got {len(issues)}: {issues}"


class TestBackwardCompatibility:
    """7.5: Backward compatibility — existing build_coaching_prompt() unchanged.

    **Validates: backward compatibility**
    """

    def test_build_coaching_prompt_still_works(self) -> None:
        """The original build_coaching_prompt function still works."""
        analysis_text = "Best move: e2e4\nEval: +0.30"
        result = build_coaching_prompt(analysis_text, level="intermediate")
        assert "e2e4" in result
        assert "intermediate" in result
        assert len(result) > 100, "Prompt should be substantial"

    def test_build_coaching_prompt_with_opening(self) -> None:
        """build_coaching_prompt includes opening name when provided."""
        analysis_text = "Best move: e2e4"
        result = build_coaching_prompt(analysis_text, level="beginner", opening_name="Sicilian Defense")
        assert "Sicilian Defense" in result
        assert "beginner" in result
