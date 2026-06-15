"""Property tests for pedagogy-layer judge grounding + parity (Task 5.4).

The judge-side injection and the single-source selection helper are pure
logic over structured data, so Hypothesis can hammer them at hundreds of
iterations. Each property is tagged with its design number and the
requirements it validates.

* Property 9 — single-source parity: the guidance list handed to the coach
  prompt is identical (same entries, same order) to the list handed to the
  judge prompt, produced by the one selection helper
  (``guidance_for_position``) over the one ``KnowledgeResource``.
* Property 10 — judge grounding / not-graded: for any NON-EMPTY guidance
  set the judge prompt (rubric v2) contains each guidance entry and the
  instruction to grade ``teaches_principle`` only against it; for an EMPTY
  guidance set the criterion is omitted from the prompt AND a parsed verdict
  records it as *not graded* (neither pass nor fail).

Plus a unit test: a graded ``teaches_principle`` pass/fail still surfaces
normally when guidance is provided.

Entries embed a unique, delimiter-terminated token (``E{idx}Z``) into their
``theme`` and ``how_to_apply`` so substring assertions cannot be confounded
by accidental overlap between entries.
"""

from __future__ import annotations

import json

from hypothesis import given, settings
from hypothesis import strategies as st

from chess_coach.eval.benchmark import BenchmarkPosition, GroundTruthPoint
from chess_coach.eval.judge import (
    JudgeRubric,
    build_judge_prompt,
    default_rubric_path,
    judge_response,
    load_rubric,
)
from chess_coach.models import (
    EvalBreakdown,
    KingSafety,
    PawnFeatures,
    PositionReport,
)
from chess_coach.pedagogy.inject import JUDGE_GUIDANCE_HEADER
from chess_coach.pedagogy.resource import GuidanceEntry, KnowledgeResource
from chess_coach.pedagogy.selector import guidance_for_position
from chess_coach.prompts import build_rich_coaching_prompt

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

_LEVELS = ("beginner", "intermediate", "advanced")
TEACHES_PRINCIPLE = "teaches_principle"

# A stable substring of the engine-grounding instruction in the judge
# prompt — present in every judge prompt regardless of guidance.
JUDGE_GROUNDING_MARKER = "GROUND TRUTH"
# A stable substring of the teaches_principle grounding instruction.
SOLE_STANDARD_MARKER = "ONLY against the curated guidance"


def _v2_rubric() -> JudgeRubric:
    return load_rubric(default_rubric_path().parent / "rubric.v2.yaml")


def _v1_rubric() -> JudgeRubric:
    return load_rubric(default_rubric_path())


def _report(fen: str = START_FEN) -> PositionReport:
    """A minimal, valid quiet ``PositionReport`` for prompt construction."""
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


def _pos(level: str = "beginner") -> BenchmarkPosition:
    return BenchmarkPosition(
        id="t",
        fen=START_FEN,
        level=level,
        phase="opening",
        points=(GroundTruthPoint("free", "center"),),
    )


def _entry(idx: int, levels: frozenset[str]) -> GuidanceEntry:
    """A schema-valid principle whose theme/how_to_apply carry a unique
    token. Its single recorded feature (``passed_pawn``) is absent from the
    quiet start position, so the entry is only ever selected via the
    level-appropriate fallback — making the selection deterministic and
    independent of feature-extraction details.
    """
    token = f"E{idx}Z"
    return GuidanceEntry(
        id=f"e{idx:02d}",
        type="principle",
        theme=f"theme-{token}",
        focus=f"focus-{token}",
        how_to_apply=f"apply-{token}",
        levels=levels,
        features=frozenset({"passed_pawn"}),
        eco_codes=frozenset(),
        citation="citation",
        example=None,
    )


@st.composite
def _resource_and_level(draw: st.DrawFn) -> tuple[KnowledgeResource, str]:
    """A student level plus a resource of 0-5 principle entries, all
    appropriate for that level (so the fallback returns all of them)."""
    level = draw(st.sampled_from(_LEVELS))
    n = draw(st.integers(min_value=0, max_value=5))
    entries: list[GuidanceEntry] = []
    for idx in range(n):
        extra = draw(st.lists(st.sampled_from(_LEVELS), max_size=3, unique=True).map(frozenset))
        entries.append(_entry(idx, frozenset({level}) | extra))
    resource = KnowledgeResource(
        entries=tuple(entries),
        feature_vocab=frozenset({"passed_pawn"}),
        eco_vocab=frozenset(),
        levels=frozenset(_LEVELS),
    )
    return resource, level


def _appearance_order(prompt: str, entries: list[GuidanceEntry]) -> list[str]:
    """Entry ids ordered by where each entry's theme first appears."""
    return [e.id for e in sorted(entries, key=lambda e: prompt.index(e.theme))]


# Feature: pedagogy-layer, Property 9: Single-source parity between coach and judge
@settings(max_examples=200)
@given(case=_resource_and_level())
def test_property_9_coach_judge_parity(case: tuple[KnowledgeResource, str]) -> None:
    """The single selection helper produces ONE guidance list; handed to
    both the coach prompt and the judge prompt it yields the same entries
    in the same order.

    Validates: Requirements 4.1, 4.5
    """
    resource, level = case
    n = max(1, len(resource.entries))

    # One selection, shared by both prompts (the single source).
    guidance = guidance_for_position(resource, _report(), level, max_entries=n)

    coach_prompt = build_rich_coaching_prompt(_report(), level=level, guidance=guidance)
    judge_prompt = build_judge_prompt("resp", _report(), _pos(level), _v2_rubric(), guidance=guidance)

    # Every selected entry surfaces in BOTH prompts (Req 4.1) ...
    for entry in guidance:
        assert entry.theme in coach_prompt
        assert entry.how_to_apply in coach_prompt
        assert entry.theme in judge_prompt
        assert entry.how_to_apply in judge_prompt

    # ... in the same order (Req 4.5): identical list, identical rendering.
    assert _appearance_order(coach_prompt, guidance) == _appearance_order(judge_prompt, guidance)
    assert _appearance_order(judge_prompt, guidance) == [e.id for e in guidance]


@st.composite
def _nonempty_resource_and_level(draw: st.DrawFn) -> tuple[KnowledgeResource, str]:
    """Like ``_resource_and_level`` but guarantees at least one entry, so
    the selection (via fallback) is non-empty."""
    level = draw(st.sampled_from(_LEVELS))
    n = draw(st.integers(min_value=1, max_value=5))
    entries: list[GuidanceEntry] = []
    for idx in range(n):
        extra = draw(st.lists(st.sampled_from(_LEVELS), max_size=3, unique=True).map(frozenset))
        entries.append(_entry(idx, frozenset({level}) | extra))
    resource = KnowledgeResource(
        entries=tuple(entries),
        feature_vocab=frozenset({"passed_pawn"}),
        eco_vocab=frozenset(),
        levels=frozenset(_LEVELS),
    )
    return resource, level


# Feature: pedagogy-layer, Property 10: Judge prompt grounds teaches_principle in the guidance
@settings(max_examples=200)
@given(case=_nonempty_resource_and_level())
def test_property_10_nonempty_guidance_grounds_prompt(case: tuple[KnowledgeResource, str]) -> None:
    """For any non-empty guidance set, the judge prompt (rubric v2) contains
    each guidance entry and the instruction to grade teaches_principle only
    against the provided guidance.

    Validates: Requirements 4.2
    """
    resource, level = case
    n = len(resource.entries)
    guidance = guidance_for_position(resource, _report(), level, max_entries=n)
    assert guidance  # fallback guarantees the level-appropriate principles

    prompt = build_judge_prompt("resp", _report(), _pos(level), _v2_rubric(), guidance=guidance)

    # The criterion is graded and grounded in the guidance.
    assert TEACHES_PRINCIPLE in prompt
    assert JUDGE_GUIDANCE_HEADER in prompt
    assert SOLE_STANDARD_MARKER in prompt
    # Each guidance entry (both bridge ends) is present as the standard.
    for entry in guidance:
        assert entry.theme in prompt
        assert entry.how_to_apply in prompt


def _v2_verdict_json(passes: dict[str, bool], contradictions: list[str] | None = None) -> str:
    return json.dumps(
        {
            "criteria": {k: {"pass": v, "reason": "because"} for k, v in passes.items()},
            "contradictions": contradictions or [],
            "notes": "ok",
        }
    )


class _FakeProvider:
    """Returns a fixed reply; records the prompt it was handed."""

    def __init__(self, reply: str):
        self.reply = reply
        self.model = "fake-judge"
        self.last_prompt = ""

    def generate(self, prompt: str, max_tokens: int = 900, temperature: float = 0.0) -> str:
        self.last_prompt = prompt
        return self.reply


@settings(max_examples=200)
@given(level=st.sampled_from(_LEVELS))
def test_property_10_empty_guidance_omits_and_marks_not_graded(level: str) -> None:
    """For an empty guidance set (rubric v2), teaches_principle is omitted
    from the prompt AND the parsed verdict records it as not graded —
    neither pass nor fail.

    Validates: Requirements 4.6
    """
    rubric = _v2_rubric()

    # The criterion is dropped from the prompt entirely (Req 4.6).
    prompt = build_judge_prompt("resp", _report(), _pos(level), rubric, guidance=[])
    assert TEACHES_PRINCIPLE not in prompt
    assert JUDGE_GUIDANCE_HEADER not in prompt

    # The judge replies for only the graded criteria; the verdict records
    # teaches_principle as not-graded rather than passing/failing it.
    graded = {k: True for k in rubric.keys() if k != TEACHES_PRINCIPLE}
    provider = _FakeProvider(_v2_verdict_json(graded))
    verdict = judge_response(provider, "resp", _report(), _pos(level), rubric, guidance=[])

    assert TEACHES_PRINCIPLE in verdict.not_graded
    assert TEACHES_PRINCIPLE not in verdict.criteria
    assert verdict.is_graded(TEACHES_PRINCIPLE) is False
    # The omitted criterion's weight is excluded from the score, so all
    # remaining criteria passing yields a perfect 1.0 (no silent fail).
    assert verdict.quality_score == 1.0


def test_graded_teaches_principle_pass_and_fail_surface_normally() -> None:
    """When guidance IS provided, teaches_principle is graded normally: a
    pass and a fail both surface in the verdict (Req 5.3 boundary).
    """
    rubric = _v2_rubric()
    resource, level = (
        KnowledgeResource(
            entries=(_entry(0, frozenset({"beginner", "intermediate", "advanced"})),),
            feature_vocab=frozenset({"passed_pawn"}),
            eco_vocab=frozenset(),
            levels=frozenset(_LEVELS),
        ),
        "beginner",
    )
    guidance = guidance_for_position(resource, _report(), level, max_entries=1)
    assert guidance

    # Pass case: teaches_principle graded and passing.
    passes = {k: True for k in rubric.keys()}
    pass_provider = _FakeProvider(_v2_verdict_json(passes))
    pass_verdict = judge_response(pass_provider, "resp", _report(), _pos(level), rubric, guidance=guidance)
    assert pass_verdict.is_graded(TEACHES_PRINCIPLE) is True
    assert pass_verdict.criteria[TEACHES_PRINCIPLE][0] is True
    assert pass_verdict.not_graded == ()

    # Fail case: teaches_principle graded and failing — surfaces as a fail,
    # not silently dropped.
    fails = {k: True for k in rubric.keys()}
    fails[TEACHES_PRINCIPLE] = False
    fail_provider = _FakeProvider(_v2_verdict_json(fails))
    fail_verdict = judge_response(fail_provider, "resp", _report(), _pos(level), rubric, guidance=guidance)
    assert fail_verdict.is_graded(TEACHES_PRINCIPLE) is True
    assert fail_verdict.criteria[TEACHES_PRINCIPLE][0] is False
    # A failed (non-gated) criterion lowers the score below 1.0.
    assert fail_verdict.quality_score < 1.0


def test_v1_rubric_unaffected_by_guidance() -> None:
    """A rubric without teaches_principle (v1) is built identically whether
    or not guidance is supplied — no criterion is dropped, nothing marked
    not-graded.
    """
    rubric = _v1_rubric()
    assert TEACHES_PRINCIPLE not in rubric.keys()

    entry = _entry(0, frozenset({"beginner"}))
    base = build_judge_prompt("resp", _report(), _pos(), rubric)
    with_guidance = build_judge_prompt("resp", _report(), _pos(), rubric, guidance=[entry])
    empty_guidance = build_judge_prompt("resp", _report(), _pos(), rubric, guidance=[])

    # v1 has no teaches_principle, so the guidance block is never injected
    # and the rubric is unchanged.
    assert base == empty_guidance
    assert JUDGE_GUIDANCE_HEADER not in with_guidance
    assert JUDGE_GROUNDING_MARKER in base
