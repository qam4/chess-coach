"""Tests for the pedagogy-layer knowledge-resource loader (Task 1.4).

Covers the fail-fast schema validation (Property 6) plus happy-path
round-trip parsing and the curated seed's foundational anchor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from chess_coach.pedagogy.resource import (
    GUIDANCE_TYPES,
    LEVELS,
    ExamplePosition,
    GuidanceEntry,
    KnowledgeResource,
    PedagogyError,
    default_resource_path,
    load_resource,
)

# Required non-empty string fields on every entry (Req 1.2, 1.7).
_REQUIRED_STR_FIELDS = ("id", "type", "theme", "focus", "how_to_apply", "citation")

# Tokens guaranteed to be outside both the type and the level vocab.
_BAD_TOKENS = ("grandmaster", "telepathy", "wizard", "expert", "club")

# Small closed pools keep generation cheap and YAML-safe.
_FEATURE_POOL = ("phase:opening", "undefended_piece", "tactic:fork", "passed_pawn", "isolated_pawn")
_ECO_POOL = ("C50", "B20", "E60")

# Lowercase letters only: always non-empty, never all-whitespace, YAML-safe.
_safe_text = st.text(alphabet=st.characters(min_codepoint=97, max_codepoint=122), min_size=1, max_size=12)
_levels = st.lists(st.sampled_from(sorted(LEVELS)), min_size=1, max_size=3, unique=True)
_features = st.lists(st.sampled_from(_FEATURE_POOL), min_size=1, max_size=3, unique=True)
_eco_codes = st.lists(st.sampled_from(_ECO_POOL), min_size=1, max_size=3, unique=True)


def _write_and_load(tmp_path: Path, entries: list[dict[str, Any]]) -> KnowledgeResource:
    """Write a knowledge.yaml with the given entries and load it."""
    path = tmp_path / "knowledge.yaml"
    path.write_text(yaml.safe_dump({"version": 1, "entries": entries}, sort_keys=False), encoding="utf-8")
    return load_resource(path)


@st.composite
def _valid_entry(
    draw: st.DrawFn,
    *,
    entry_id: str | None = None,
    entry_type: str | None = None,
) -> dict[str, Any]:
    """Build a dict for a schema-valid Guidance_Entry."""
    etype = entry_type if entry_type is not None else draw(st.sampled_from(sorted(GUIDANCE_TYPES)))
    eid = entry_id if entry_id is not None else draw(_safe_text)
    entry: dict[str, Any] = {
        "id": eid,
        "type": etype,
        "theme": draw(_safe_text),
        "focus": draw(_safe_text),
        "how_to_apply": draw(_safe_text),
        "levels": draw(_levels),
        "citation": draw(_safe_text),
    }
    if etype in ("principle", "pattern"):
        entry["features"] = draw(_features)
    else:  # plan requires eco_codes (Req 1.5)
        entry["eco_codes"] = draw(_eco_codes)
    return entry


@st.composite
def _malformed_case(draw: st.DrawFn) -> tuple[list[dict[str, Any]], str]:
    """A malformed resource plus a substring the error message must name.

    Derives an invalid variant from a valid base by: (a) dropping each
    required field, (b) an out-of-set type or level, (c) omitting
    features for a principle/pattern or eco_codes for a plan, or (d)
    duplicating an id across two entries.
    """
    kind = draw(
        st.sampled_from(["drop_field", "bad_type", "bad_level", "missing_features", "missing_eco", "duplicate_id"])
    )

    if kind == "drop_field":
        field = draw(st.sampled_from(_REQUIRED_STR_FIELDS))
        entry = draw(_valid_entry())
        del entry[field]
        return [entry], field

    if kind == "bad_type":
        entry = draw(_valid_entry(entry_type="principle"))
        entry["type"] = draw(st.sampled_from(_BAD_TOKENS))
        return [entry], "type"

    if kind == "bad_level":
        entry = draw(_valid_entry())
        entry["levels"] = [*entry["levels"], draw(st.sampled_from(_BAD_TOKENS))]
        return [entry], "levels"

    if kind == "missing_features":
        entry = draw(_valid_entry(entry_type=draw(st.sampled_from(["principle", "pattern"]))))
        entry.pop("features", None)
        return [entry], "features"

    if kind == "missing_eco":
        entry = draw(_valid_entry(entry_type="plan"))
        entry.pop("eco_codes", None)
        return [entry], "eco_codes"

    # duplicate_id: two otherwise-valid entries sharing one id (Req 1.9).
    shared = draw(_safe_text)
    first = draw(_valid_entry(entry_id=shared))
    second = draw(_valid_entry(entry_id=shared))
    return [first, second], shared


# Feature: pedagogy-layer, Property 6: Resource schema validation rejects malformed entries
@settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(case=_malformed_case())
def test_schema_validation_rejects_malformed_entries(
    case: tuple[list[dict[str, Any]], str],
    tmp_path: Path,
) -> None:
    """Malformed entries are rejected fail-fast, naming the offence.

    Validates: Requirements 1.2, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9
    """
    entries, expected = case
    with pytest.raises(PedagogyError) as exc:
        _write_and_load(tmp_path, entries)
    assert expected in str(exc.value), f"error did not name {expected!r}: {exc.value}"


# --------------------------------------------------------------- happy path


def test_happy_path_round_trip(tmp_path: Path) -> None:
    """A valid resource parses into typed entries with frozenset fields,
    and an entry's example maps to an ExamplePosition."""
    path = tmp_path / "knowledge.yaml"
    path.write_text(
        """
version: 1
entries:
  - id: principle.center
    type: principle
    theme: center control
    focus: Control the center.
    how_to_apply: Put a pawn or piece on a central square.
    levels: [beginner, intermediate]
    features: [phase:opening]
    citation: "Silman, How to Reassess Your Chess"
  - id: pattern.back_rank
    type: pattern
    theme: back-rank weakness
    focus: The back rank can be mated.
    how_to_apply: Land a rook on the undefended back rank.
    levels: [advanced]
    features: [tactic:back_rank]
    citation: "Chernev, Logical Chess"
    example:
      fen: "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1"
      move: a1a8
  - id: plan.italian
    type: plan
    theme: Italian slow build-up
    focus: Build slowly behind c3/d3.
    how_to_apply: Play c3, d3, castle, reroute the knight.
    levels: [intermediate, advanced]
    eco_codes: [C50]
    citation: "Seirawan, Winning Chess Openings"
""",
        encoding="utf-8",
    )
    resource = load_resource(path)

    assert isinstance(resource, KnowledgeResource)
    assert len(resource.entries) == 3
    assert all(isinstance(e, GuidanceEntry) for e in resource.entries)

    principle = resource.by_id("principle.center")
    assert principle is not None
    assert principle.type == "principle"
    assert principle.theme == "center control"
    assert principle.focus == "Control the center."
    assert principle.how_to_apply == "Put a pawn or piece on a central square."
    assert principle.levels == frozenset({"beginner", "intermediate"})
    assert principle.features == frozenset({"phase:opening"})
    assert principle.eco_codes == frozenset()
    assert principle.citation == "Silman, How to Reassess Your Chess"
    assert principle.example is None
    assert isinstance(principle.levels, frozenset)
    assert isinstance(principle.features, frozenset)

    pattern = resource.by_id("pattern.back_rank")
    assert pattern is not None
    assert pattern.example == ExamplePosition(fen="6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1", move="a1a8")

    plan = resource.by_id("plan.italian")
    assert plan is not None
    assert plan.type == "plan"
    assert plan.eco_codes == frozenset({"C50"})
    assert plan.features == frozenset()

    # Derived vocabularies are the union over the loaded entries.
    assert {"phase:opening", "tactic:back_rank"} <= resource.feature_vocab
    assert resource.eco_vocab == frozenset({"C50"})
    assert resource.levels == frozenset({"beginner", "intermediate", "advanced"})


# --------------------------------------------------------------- real seed


def test_default_seed_loads_with_foundational_principles() -> None:
    """The shipped knowledge.yaml loads and contains the five
    foundational opening principles as the labeled anchor (Req 1.3, as
    amended — the resource intentionally contains more entries)."""
    resource = load_resource(default_resource_path())

    assert len(resource.entries) >= 5
    principle_themes = {e.theme for e in resource.principles()}
    foundational = {
        "center control",
        "development",
        "king safety",
        "piece protection",
        "piece coordination",
    }
    missing = foundational - principle_themes
    assert missing == set(), f"foundational principles missing from the seed: {sorted(missing)}"
