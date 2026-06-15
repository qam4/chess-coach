"""Property tests for the pedagogy-layer Selector (Task 3.3).

The Selector is pure logic over structured data, so Hypothesis can hammer
it at hundreds of iterations. Each property is tagged with its design
number and the requirements it validates. Entries are built directly via
the dataclasses (no YAML round-trip) for speed; ids are assigned by index
so they are unique by construction.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from chess_coach.pedagogy.resource import GuidanceEntry, KnowledgeResource
from chess_coach.pedagogy.selector import SelectionInput, select

# Small closed pools keep generation cheap and the input space meaningful
# (overlap between entry features and selection features must be likely).
_FEATURES = ("phase:opening", "undefended_piece", "tactic:fork", "passed_pawn", "open_file")
_ECOS = ("C50", "B20", "E60")
_LEVELS = ("beginner", "intermediate", "advanced")
_TYPE_RANK = {"plan": 0, "pattern": 1, "principle": 2}

_levels_st = st.lists(st.sampled_from(_LEVELS), min_size=1, max_size=3, unique=True).map(frozenset)
_feature_set_st = st.lists(st.sampled_from(_FEATURES), min_size=0, max_size=4, unique=True).map(frozenset)
_nonempty_feature_set_st = st.lists(st.sampled_from(_FEATURES), min_size=1, max_size=4, unique=True).map(frozenset)
_eco_set_st = st.lists(st.sampled_from(_ECOS), min_size=1, max_size=3, unique=True).map(frozenset)


@st.composite
def _entry(draw: st.DrawFn, idx: int) -> GuidanceEntry:
    """A schema-valid GuidanceEntry with a unique id (``e{idx}``)."""
    etype = draw(st.sampled_from(["principle", "pattern", "plan"]))
    levels = draw(_levels_st)
    if etype == "plan":
        # Plans may carry features too, but typically match via ECO; allow
        # an empty feature set (which never feature-matches).
        features = draw(_feature_set_st)
        eco_codes = draw(_eco_set_st)
    else:
        features = draw(_nonempty_feature_set_st)
        eco_codes = frozenset()
    return GuidanceEntry(
        id=f"e{idx}",
        type=etype,
        theme="theme",
        focus="focus",
        how_to_apply="apply",
        levels=levels,
        features=features,
        eco_codes=eco_codes,
        citation="citation",
        example=None,
    )


@st.composite
def _resource(draw: st.DrawFn) -> KnowledgeResource:
    """A KnowledgeResource of 0-8 entries with unique ids."""
    n = draw(st.integers(min_value=0, max_value=8))
    entries = tuple(draw(_entry(i)) for i in range(n))
    return KnowledgeResource(
        entries=entries,
        feature_vocab=frozenset(_FEATURES),
        eco_vocab=frozenset(_ECOS),
        levels=frozenset(_LEVELS),
    )


@st.composite
def _selection_input(draw: st.DrawFn) -> SelectionInput:
    return SelectionInput(
        features=draw(_feature_set_st),
        eco=draw(st.one_of(st.none(), st.sampled_from(_ECOS))),
        level=draw(st.sampled_from(_LEVELS)),
        max_entries=draw(st.integers(min_value=1, max_value=10)),
    )


# --------------------------------------------------------- reference impl


def _ref_relevance(entry: GuidanceEntry, inp: SelectionInput) -> int:
    score = len(entry.features & inp.features)
    if inp.eco is not None and entry.type == "plan" and inp.eco in entry.eco_codes:
        score += 1
    return score


def _ref_select(resource: KnowledgeResource, inp: SelectionInput) -> list[GuidanceEntry]:
    """Independent brute-force reference for the 5-step algorithm."""
    main: list[GuidanceEntry] = []
    for e in resource.entries:
        if inp.level not in e.levels:
            continue
        feature_matched = len(e.features) > 0 and e.features.issubset(inp.features)
        eco_matched = inp.eco is not None and e.type == "plan" and inp.eco in e.eco_codes
        if feature_matched or eco_matched:
            main.append(e)
    candidates = main if main else [e for e in resource.entries if e.type == "principle" and inp.level in e.levels]
    ordered = sorted(
        candidates,
        key=lambda e: (-_ref_relevance(e, inp), _TYPE_RANK[e.type], e.id),
    )
    return ordered[: inp.max_entries]


def _ids(entries: list[GuidanceEntry]) -> list[str]:
    return [e.id for e in entries]


# Feature: pedagogy-layer, Property 1: Selection soundness and referential integrity
@settings(max_examples=200)
@given(resource=_resource(), inp=_selection_input())
def test_property_1_soundness_and_referential_integrity(
    resource: KnowledgeResource,
    inp: SelectionInput,
) -> None:
    """Every returned entry exists in the resource and (when not an
    ECO/fallback selection) has all its features present; no feature-
    matched, level-appropriate entry surviving the cap is omitted.

    Validates: Requirements 2.1, 2.7
    """
    result = select(resource, inp)
    resource_ids = {e.id for e in resource.entries}

    # Referential integrity (Req 2.7): never return an entry absent from
    # the resource.
    assert {e.id for e in result} <= resource_ids

    # Matches the obviously-correct brute-force reference exactly — this
    # pins soundness, completeness, ordering and the cap together.
    assert _ids(result) == _ids(_ref_select(resource, inp))

    # Feature soundness (Req 2.1): an entry selected on its features has
    # all of them present. ECO-keyed plans and the level-appropriate
    # fallback principles are the two deliberate exceptions.
    feature_matched_ids = {
        e.id for e in resource.entries if e.features and e.features <= inp.features and inp.level in e.levels
    }
    eco_matched_ids = {
        e.id
        for e in resource.entries
        if inp.eco is not None and e.type == "plan" and inp.eco in e.eco_codes and inp.level in e.levels
    }
    fallback_active = not (feature_matched_ids or eco_matched_ids)
    for e in result:
        if not fallback_active and e.id not in eco_matched_ids:
            assert e.features <= inp.features

    # No omission: when the cap is not binding, every feature-matched,
    # level-appropriate entry is returned.
    if len(result) < inp.max_entries:
        assert feature_matched_ids <= {e.id for e in result}


# Feature: pedagogy-layer, Property 2: ECO-keyed plan inclusion
@st.composite
def _resource_and_eco_input(draw: st.DrawFn) -> tuple[KnowledgeResource, SelectionInput]:
    """Resource + input with a known ECO and a non-binding cap, so ECO
    plan inclusion is observable without the cap truncating it."""
    resource = draw(_resource())
    inp = SelectionInput(
        features=draw(_feature_set_st),
        eco=draw(st.sampled_from(_ECOS)),
        level=draw(st.sampled_from(_LEVELS)),
        max_entries=max(1, len(resource.entries)),
    )
    return resource, inp


@settings(max_examples=200)
@given(case=_resource_and_eco_input())
def test_property_2_eco_plan_inclusion(case: tuple[KnowledgeResource, SelectionInput]) -> None:
    """Every Plan whose ECO codes include the context is selected, subject
    to the level filter (cap made non-binding here).

    Validates: Requirements 2.2
    """
    resource, inp = case
    result_ids = {e.id for e in select(resource, inp)}
    expected = {
        e.id
        for e in resource.entries
        if e.type == "plan" and inp.eco is not None and inp.eco in e.eco_codes and inp.level in e.levels
    }
    assert expected <= result_ids


# Feature: pedagogy-layer, Property 3: Cap is always respected
@settings(max_examples=200)
@given(resource=_resource(), inp=_selection_input())
def test_property_3_cap_respected(resource: KnowledgeResource, inp: SelectionInput) -> None:
    """The selection never exceeds the configured maximum.

    Validates: Requirements 2.3
    """
    result = select(resource, inp)
    assert len(result) <= inp.max_entries


# Feature: pedagogy-layer, Property 4: Deterministic, stable ordering
@settings(max_examples=200)
@given(resource=_resource(), inp=_selection_input())
def test_property_4_deterministic_stable_order(resource: KnowledgeResource, inp: SelectionInput) -> None:
    """Repeated calls return the same list, and ties (equal relevance and
    type) are broken by ascending id.

    Validates: Requirements 2.4, 2.6
    """
    first = select(resource, inp)
    second = select(resource, inp)
    assert _ids(first) == _ids(second)

    # The list is sorted by the documented total key, so any two adjacent
    # entries are in non-decreasing key order; in particular equal
    # (relevance, type) pairs appear in ascending-id order.
    keys = [(-_ref_relevance(e, inp), _TYPE_RANK[e.type], e.id) for e in first]
    assert keys == sorted(keys)


# Feature: pedagogy-layer, Property 5: Level-appropriate fallback when nothing matches
@st.composite
def _resource_and_nomatch_input(draw: st.DrawFn) -> tuple[KnowledgeResource, SelectionInput]:
    """Resource + an input guaranteed to match nothing: empty features
    (no entry feature-matches) and no ECO (no plan matches)."""
    resource = draw(_resource())
    inp = SelectionInput(
        features=frozenset(),
        eco=None,
        level=draw(st.sampled_from(_LEVELS)),
        max_entries=draw(st.integers(min_value=1, max_value=10)),
    )
    return resource, inp


@settings(max_examples=200)
@given(case=_resource_and_nomatch_input())
def test_property_5_level_appropriate_fallback(case: tuple[KnowledgeResource, SelectionInput]) -> None:
    """When nothing matches, the selection is exactly the level-appropriate
    foundational principles (ordered by id, capped).

    Validates: Requirements 2.5
    """
    resource, inp = case
    result = select(resource, inp)

    expected = sorted(
        (e for e in resource.entries if e.type == "principle" and inp.level in e.levels),
        key=lambda e: e.id,
    )[: inp.max_entries]
    assert _ids(result) == _ids(expected)
