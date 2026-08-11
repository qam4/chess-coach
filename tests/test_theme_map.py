"""Tests for the engine-theme -> knowledge-feature mapping and its use as a
soft ranking bias in the pedagogy selector (grounded-move-advice Task 4)."""

from __future__ import annotations

from chess_coach.pedagogy.resource import GuidanceEntry, KnowledgeResource
from chess_coach.pedagogy.selector import SelectionInput, select
from chess_coach.pedagogy.theme_map import theme_features


def test_theme_features_maps_known_themes() -> None:
    assert theme_features("piece development") == frozenset({"phase:opening"})
    assert theme_features("king safety, castling") == frozenset({"exposed_king"})
    assert theme_features("material win") == frozenset({"hanging_piece_opponent"})
    # Case/whitespace tolerant.
    assert theme_features("  Piece Development  ") == frozenset({"phase:opening"})


def test_theme_features_unmapped_is_empty() -> None:
    assert theme_features("general play") == frozenset()
    assert theme_features("something the engine added later") == frozenset()


def _entry(eid: str, features: frozenset[str]) -> GuidanceEntry:
    return GuidanceEntry(
        id=eid,
        type="principle",
        theme="t",
        focus="f",
        how_to_apply="a",
        levels=frozenset({"intermediate"}),
        features=features,
        eco_codes=frozenset(),
        citation="c",
        example=None,
    )


def _resource(*entries: GuidanceEntry) -> KnowledgeResource:
    return KnowledgeResource(
        entries=tuple(entries),
        feature_vocab=frozenset({"phase:opening", "exposed_king"}),
        eco_vocab=frozenset(),
        levels=frozenset({"beginner", "intermediate", "advanced"}),
    )


def test_preferred_features_breaks_tie_toward_theme() -> None:
    # Two equally-relevant entries (each matches exactly one position
    # feature). Without a preferred theme, ties break by id -> 'a' first.
    a = _entry("a", frozenset({"phase:opening"}))
    b = _entry("b", frozenset({"exposed_king"}))
    resource = _resource(a, b)
    position_features = frozenset({"phase:opening", "exposed_king"})

    unbiased = select(
        resource,
        SelectionInput(features=position_features, eco=None, level="intermediate", max_entries=2),
    )
    assert [e.id for e in unbiased] == ["a", "b"]

    # Biasing toward the king-safety theme surfaces entry 'b' first.
    biased = select(
        resource,
        SelectionInput(
            features=position_features,
            eco=None,
            level="intermediate",
            max_entries=2,
            preferred_features=frozenset({"exposed_king"}),
        ),
    )
    assert [e.id for e in biased] == ["b", "a"]


def test_preferred_features_is_additive_not_restrictive() -> None:
    # A preferred feature that no entry has does not drop or reorder anything.
    a = _entry("a", frozenset({"phase:opening"}))
    b = _entry("b", frozenset({"exposed_king"}))
    resource = _resource(a, b)
    position_features = frozenset({"phase:opening", "exposed_king"})

    result = select(
        resource,
        SelectionInput(
            features=position_features,
            eco=None,
            level="intermediate",
            max_entries=2,
            preferred_features=frozenset({"passed_pawn"}),  # unmatched by any entry
        ),
    )
    assert [e.id for e in result] == ["a", "b"]  # unchanged from unbiased order


def test_fact_features_outrank_the_theme_bias() -> None:
    # Regression for a measured collision between the two soft biases. The
    # engine's PV theme "piece development" maps to the broad `phase:opening`
    # feature, so the theme bias handed +1 to every abstract opening entry.
    # When the fact bias was folded into the same bonus it cancelled out, and
    # the id tie-break picked the abstraction: in real positions with a live
    # threat, "center control" beat "answer the threat first", and only 10 of 30
    # selected entries could be instantiated with a verified board fact.
    abstract = _entry("a", frozenset({"phase:opening"}))
    instantiable = _entry("b", frozenset({"exposed_king"}))
    resource = _resource(abstract, instantiable)
    position_features = frozenset({"phase:opening", "exposed_king"})

    result = select(
        resource,
        SelectionInput(
            features=position_features,
            eco=None,
            level="intermediate",
            max_entries=2,
            # What theme_features("piece development") actually returns.
            preferred_features=frozenset({"phase:opening"}),
            fact_features=frozenset({"exposed_king"}),
        ),
    )
    assert [e.id for e in result] == ["b", "a"]


def test_fact_features_do_not_override_relevance() -> None:
    # The fact bias is a tie-break, not an override: a genuinely more relevant
    # entry still wins even when it carries no composable fact.
    two_matches = _entry("a", frozenset({"phase:opening", "exposed_king"}))
    one_match_with_fact = _entry("b", frozenset({"passed_pawn"}))
    resource = KnowledgeResource(
        entries=(two_matches, one_match_with_fact),
        feature_vocab=frozenset({"phase:opening", "exposed_king", "passed_pawn"}),
        eco_vocab=frozenset(),
        levels=frozenset({"beginner", "intermediate", "advanced"}),
    )

    result = select(
        resource,
        SelectionInput(
            features=frozenset({"phase:opening", "exposed_king", "passed_pawn"}),
            eco=None,
            level="intermediate",
            max_entries=2,
            fact_features=frozenset({"passed_pawn"}),
        ),
    )
    assert [e.id for e in result] == ["a", "b"]
