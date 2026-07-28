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
