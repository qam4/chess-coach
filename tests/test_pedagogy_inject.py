"""Property tests for pedagogy-layer coach-prompt injection (Task 4.4).

The injection builders are pure logic over structured data, so Hypothesis
can hammer them at hundreds of iterations. Each property is tagged with
its design number and the requirements it validates.

* Property 7 — the coach prompt carries both ends of the teaching bridge
  (each injected entry's theme text AND its how-to-apply text) and always
  retains the engine-grounding instructions; an empty selection leaves the
  grounding intact with no guidance block.
* Property 8 — level filtering excludes inapplicable entries from the
  injected prompt.

Entries embed a unique, delimiter-terminated token (``E{idx}Z``) into
their ``theme`` and ``how_to_apply`` so substring assertions cannot be
confounded by accidental overlap between entries.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from chess_coach.models import (
    EvalBreakdown,
    KingSafety,
    PawnFeatures,
    PositionReport,
)
from chess_coach.pedagogy.inject import GUIDANCE_BLOCK_HEADER
from chess_coach.pedagogy.resource import GuidanceEntry
from chess_coach.prompts import build_rich_coaching_prompt

# A stable substring of the engine-grounding instructions in
# ``SYSTEM_PROMPT_V2`` — its presence proves the grounding survived
# injection (Req 3.4, 3.6, 3.7).
GROUNDING_MARKER = "GROUNDING RULES (strict):"

_LEVELS = ("beginner", "intermediate", "advanced")
_FEATURES = ("phase:opening", "undefended_piece", "tactic:fork", "passed_pawn")

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

_levels_st = st.lists(st.sampled_from(_LEVELS), min_size=1, max_size=3, unique=True).map(frozenset)
_feature_set_st = st.lists(st.sampled_from(_FEATURES), min_size=1, max_size=3, unique=True).map(frozenset)


def _report(fen: str = START_FEN) -> PositionReport:
    """Build a minimal, valid ``PositionReport`` for prompt construction.

    The report's content is irrelevant to injection — the grounding comes
    from the system prompt and the guidance from the injected entries — so
    a quiet, feature-light report keeps the tests focused.
    """
    empty_pawns = PawnFeatures([], [], [])
    return PositionReport(
        fen=fen,
        eval_cp=0,
        eval_breakdown=EvalBreakdown(material=0, mobility=20, king_safety=0, pawn_structure=0),
        hanging_pieces={"white": [], "black": []},
        threats={"white": [], "black": []},
        pawn_structure={"white": empty_pawns, "black": empty_pawns},
        king_safety={"white": KingSafety(0, ""), "black": KingSafety(0, "")},
        top_lines=[],
        tactics=[],
        threat_map=[],
        threat_map_summary=None,
        critical_moment=False,
        critical_reason=None,
    )


def _entry(idx: int, levels: frozenset[str], features: frozenset[str]) -> GuidanceEntry:
    """A schema-valid entry whose theme/how_to_apply carry a unique token.

    The ``E{idx}Z`` token is delimiter-terminated so ``"E1Z"`` is never a
    substring of ``"E10Z"``, keeping per-entry substring assertions exact.
    """
    token = f"E{idx}Z"
    etype = "plan" if not features else "principle"
    return GuidanceEntry(
        id=f"e{idx}",
        type=etype,
        theme=f"theme-{token}",
        focus=f"focus-{token}",
        how_to_apply=f"apply-{token}",
        levels=levels,
        features=features if etype != "plan" else frozenset(),
        eco_codes=frozenset({"C50"}) if etype == "plan" else frozenset(),
        citation="citation",
        example=None,
    )


@st.composite
def _level_appropriate_case(draw: st.DrawFn) -> tuple[str, list[GuidanceEntry]]:
    """A student level plus 0-5 entries all appropriate for that level.

    Used by Property 7: every entry survives the level filter, so the
    prompt must surface all of them.
    """
    level = draw(st.sampled_from(_LEVELS))
    n = draw(st.integers(min_value=0, max_value=5))
    entries: list[GuidanceEntry] = []
    for idx in range(n):
        extra = draw(st.lists(st.sampled_from(_LEVELS), max_size=3, unique=True).map(frozenset))
        levels = frozenset({level}) | extra
        entries.append(_entry(idx, levels, draw(_feature_set_st)))
    return level, entries


@st.composite
def _mixed_level_case(draw: st.DrawFn) -> tuple[str, list[GuidanceEntry]]:
    """A student level plus 1-6 entries with arbitrary (mixed) levels.

    Used by Property 8: some entries' levels may exclude the student
    level, and those must not appear in the injected prompt.
    """
    level = draw(st.sampled_from(_LEVELS))
    n = draw(st.integers(min_value=1, max_value=6))
    entries = [_entry(idx, draw(_levels_st), draw(_feature_set_st)) for idx in range(n)]
    return level, entries


# Feature: pedagogy-layer, Property 7: Coach prompt carries both bridge ends and retains grounding
@settings(max_examples=200)
@given(case=_level_appropriate_case())
def test_property_7_both_bridge_ends_and_grounding(case: tuple[str, list[GuidanceEntry]]) -> None:
    """For any level-appropriate guidance set, the coach prompt contains
    both bridge ends (theme + how_to_apply) for every injected entry and
    always retains the engine-grounding instructions; an empty set yields
    grounding with no guidance block.

    Validates: Requirements 3.1, 3.2, 3.4, 3.5, 3.6, 3.7
    """
    level, entries = case
    prompt = build_rich_coaching_prompt(_report(), level=level, guidance=entries)

    # Grounding is always retained (Req 3.4, 3.6, 3.7).
    assert GROUNDING_MARKER in prompt

    if entries:
        # Both ends of the bridge present for every injected entry
        # (Req 3.1, 3.2, 3.5).
        for entry in entries:
            assert entry.theme in prompt
            assert entry.how_to_apply in prompt
        assert GUIDANCE_BLOCK_HEADER in prompt
    else:
        # Empty selection ⇒ no guidance block (Req 3.6, 3.7).
        assert GUIDANCE_BLOCK_HEADER not in prompt


@settings(max_examples=200)
@given(level=st.sampled_from(_LEVELS))
def test_property_7_none_guidance_matches_today(level: str) -> None:
    """Passing no guidance builds the prompt exactly as today: grounding
    intact, no guidance block, identical to omitting the argument.

    Validates: Requirements 3.6, 3.7
    """
    report = _report()
    with_none = build_rich_coaching_prompt(report, level=level, guidance=None)
    baseline = build_rich_coaching_prompt(report, level=level)
    assert with_none == baseline
    assert GROUNDING_MARKER in with_none
    assert GUIDANCE_BLOCK_HEADER not in with_none


# Feature: pedagogy-layer, Property 8: Level filtering excludes inapplicable entries
@settings(max_examples=200)
@given(case=_mixed_level_case())
def test_property_8_level_filtering_excludes_inapplicable(case: tuple[str, list[GuidanceEntry]]) -> None:
    """No entry whose recorded levels exclude the student level appears in
    the injected coach prompt; level-appropriate entries still appear.

    Validates: Requirements 3.3
    """
    level, entries = case
    prompt = build_rich_coaching_prompt(_report(), level=level, guidance=entries)

    for entry in entries:
        token_theme = entry.theme
        token_apply = entry.how_to_apply
        if level in entry.levels:
            assert token_theme in prompt
            assert token_apply in prompt
        else:
            assert token_theme not in prompt
            assert token_apply not in prompt


def test_guidance_block_carries_anti_fabrication_clause() -> None:
    """The injected guidance intro must explicitly forbid inventing a
    concrete tactic/move to fit a theme — the lever against the factual
    regression seen when guidance was switched on for capable models."""
    from chess_coach.pedagogy.inject import format_guidance_block

    entry = GuidanceEntry(
        id="e1",
        type="principle",
        theme="make a plan",
        focus="decide what the position is about",
        how_to_apply="improve the worst-placed piece",
        levels=frozenset({"intermediate"}),
        features=frozenset({"phase:middlegame"}),
        eco_codes=frozenset(),
        citation="citation",
        example=None,
    )
    block = format_guidance_block([entry], level="intermediate")
    lowered = block.lower()
    assert "never invent" in lowered
    assert "only if the analysis actually shows it" in lowered
    # The teaching content (both bridge ends) is still present.
    assert "make a plan" in block
    assert "improve the worst-placed piece" in block
