"""Guidance data model for the pedagogy layer (loader lands in Task 1.2).

A ``GuidanceEntry`` is one curated record of *what is worth teaching* —
a Principle, Pattern, or Plan — carrying both ends of the teaching
bridge: a student-facing ``focus`` ("what to focus on") and a
``how_to_apply`` ("how to apply it here"). Entries are keyed for
selection by ``features`` (Position_Features) and, for plans, by
``eco_codes`` (opening contexts), and are scoped to one or more
``levels``.

The set lives as data (``data/pedagogy/knowledge.yaml``) so it grows
without code changes; this module defines only the frozen, immutable
shapes and the fail-fast error type that the loader (Task 1.2) and the
annotation guard (Task 6) raise. The dataclasses mirror the
benchmark-set models in ``eval/benchmark.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# The defined sets every entry is validated against (mirrors the
# benchmark loader's KNOWN_KINDS / _LEVELS). The loader (Task 1.2) and
# the annotation guard (Task 6) check entry fields against these.
GUIDANCE_TYPES = frozenset({"principle", "pattern", "plan"})
LEVELS = frozenset({"beginner", "intermediate", "advanced"})


class PedagogyError(Exception):
    """Raised when the knowledge resource is malformed. Fail-fast: the
    message names the offending entry id and field so the author can fix
    it immediately. No partial or best-effort loads."""


@dataclass(frozen=True)
class ExamplePosition:
    """Optional concrete example anchoring a Guidance_Entry. When
    present, the guard checks legality (Req 6.3) and engine-soundness
    (Req 6.4)."""

    fen: str
    move: str  # UCI; the recommended action to teach


@dataclass(frozen=True)
class GuidanceEntry:
    """One curated record of what is worth teaching and how.

    Exactly one ``type`` from {principle, pattern, plan}. ``features``
    key selection for principles/patterns (Req 1.6); ``eco_codes`` key
    selection for plans (Req 1.5). ``citation`` ties the guidance to
    instructional canon (Req 1.7).
    """

    id: str  # unique within the resource (Req 1.2, 1.9)
    type: str  # "principle" | "pattern" | "plan" (Req 1.2)
    theme: str  # named theme, e.g. "center control" (Req 1.2)
    focus: str  # student-facing "what to focus on" (Req 1.2)
    how_to_apply: str  # student-facing "how to apply it here" (Req 1.2)
    levels: frozenset[str]  # subset of LEVELS (Req 1.4)
    features: frozenset[str]  # Position_Features; required for principle/pattern (Req 1.6)
    eco_codes: frozenset[str]  # required for plan (Req 1.5)
    citation: str  # non-empty source authority (Req 1.7)
    example: ExamplePosition | None  # optional (Req 6.3, 6.4)

    def applies_to_level(self, level: str) -> bool:
        """True when this entry is appropriate for ``level`` (Req 1.4)."""
        return level in self.levels


@dataclass(frozen=True)
class KnowledgeResource:
    """The admitted guidance plus the defined sets it validates against.

    Wraps the admitted ``entries`` and exposes the lookups the selector
    needs, alongside the closed feature/ECO/level vocabularies the guard
    checks references against (Req 6.2).
    """

    entries: tuple[GuidanceEntry, ...]
    feature_vocab: frozenset[str]
    eco_vocab: frozenset[str]
    levels: frozenset[str]

    def by_id(self, entry_id: str) -> GuidanceEntry | None:
        """Return the entry with ``entry_id``, or None if absent."""
        for entry in self.entries:
            if entry.id == entry_id:
                return entry
        return None

    def principles(self) -> tuple[GuidanceEntry, ...]:
        """The foundational Principle entries (Req 1.3, fallback in 2.5)."""
        return tuple(e for e in self.entries if e.type == "principle")

    def entries_for_feature(self, feature: str) -> tuple[GuidanceEntry, ...]:
        """Entries that record ``feature`` among their Position_Features."""
        return tuple(e for e in self.entries if feature in e.features)

    def plans_for_eco(self, eco: str) -> tuple[GuidanceEntry, ...]:
        """Plan entries whose recorded ECO codes include ``eco`` (Req 2.2)."""
        return tuple(e for e in self.entries if e.type == "plan" and eco in e.eco_codes)


# --------------------------------------------------------------- loader
#
# Fail-fast loader, mirroring ``eval/benchmark.load_benchmark`` and
# ``eval/judge.load_rubric``: read YAML, validate each entry against the
# schema, and raise a single typed :class:`PedagogyError` naming the
# offending entry id and field. No partial or best-effort loads.

# Fields that must be present and non-empty on every entry (Req 1.2, 1.7).
_REQUIRED_STR_FIELDS = ("id", "type", "theme", "focus", "how_to_apply", "citation")


def _err(ctx: str, msg: str) -> PedagogyError:
    return PedagogyError(f"{ctx}: {msg}")


def _require_non_empty_str(raw: dict[str, Any], field: str, ctx: str) -> str:
    if field not in raw:
        raise _err(ctx, f"missing required field {field!r}")
    value = raw[field]
    if not isinstance(value, str) or not value.strip():
        raise _err(ctx, f"field {field!r} must be a non-empty string")
    return value


def _parse_str_set(raw: dict[str, Any], field: str, ctx: str, *, required: bool) -> frozenset[str]:
    """Parse a list-of-strings field into a frozenset.

    When ``required`` the list must be present and non-empty; otherwise
    an absent field yields the empty set. Every member must be a
    non-empty string.
    """
    if field not in raw or raw[field] is None:
        if required:
            raise _err(ctx, f"{field!r} must be a non-empty list")
        return frozenset()
    value = raw[field]
    if not isinstance(value, list):
        raise _err(ctx, f"{field!r} must be a list, got {type(value).__name__}")
    if required and not value:
        raise _err(ctx, f"{field!r} must be a non-empty list")
    members: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise _err(ctx, f"{field!r} entries must be non-empty strings, got {item!r}")
        members.append(item)
    return frozenset(members)


def _parse_example(raw: Any, ctx: str) -> ExamplePosition | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _err(ctx, f"'example' must be a mapping, got {type(raw).__name__}")
    fen = _require_non_empty_str(raw, "fen", f"{ctx}.example")
    move = _require_non_empty_str(raw, "move", f"{ctx}.example")
    return ExamplePosition(fen=fen, move=move)


def _parse_entry(raw: Any, index: int) -> GuidanceEntry:
    ctx = f"entries[{index}]"
    if not isinstance(raw, dict):
        raise _err(ctx, f"entry must be a mapping, got {type(raw).__name__}")

    entry_id = _require_non_empty_str(raw, "id", ctx)
    ctx = f"entries[{index}] ({entry_id})"

    # Remaining required non-empty string fields (Req 1.2, 1.7).
    fields = {field: _require_non_empty_str(raw, field, ctx) for field in _REQUIRED_STR_FIELDS}

    entry_type = fields["type"]
    if entry_type not in GUIDANCE_TYPES:
        raise _err(ctx, f"field 'type' must be one of {sorted(GUIDANCE_TYPES)}, got {entry_type!r}")

    # Levels: a non-empty subset of LEVELS (Req 1.4).
    levels = _parse_str_set(raw, "levels", ctx, required=True)
    bad_levels = levels - LEVELS
    if bad_levels:
        raise _err(ctx, f"field 'levels' has values outside {sorted(LEVELS)}: {sorted(bad_levels)}")

    # Selection keys: principle/pattern require features (Req 1.6); plan
    # requires eco_codes (Req 1.5). Each is optional for the other type.
    features = _parse_str_set(raw, "features", ctx, required=entry_type in ("principle", "pattern"))
    eco_codes = _parse_str_set(raw, "eco_codes", ctx, required=entry_type == "plan")

    example = _parse_example(raw.get("example"), ctx)

    return GuidanceEntry(
        id=entry_id,
        type=entry_type,
        theme=fields["theme"],
        focus=fields["focus"],
        how_to_apply=fields["how_to_apply"],
        levels=levels,
        features=features,
        eco_codes=eco_codes,
        citation=fields["citation"],
        example=example,
    )


def load_resource(path: str | Path) -> KnowledgeResource:
    """Load and validate the curated knowledge resource.

    Mirrors ``eval/benchmark.load_benchmark``: the top level is a mapping
    with a ``version`` and a non-empty ``entries`` list. Raises
    :class:`PedagogyError` (fail-fast) on the first malformed entry,
    naming the offending entry id and the field, and on a duplicate id
    (Req 1.8, 1.9). Returns a fully built :class:`KnowledgeResource`.

    The resource's ``feature_vocab`` / ``eco_vocab`` / ``levels`` are
    derived here from the union of values present across the loaded
    entries — a self-consistent interim vocabulary. The closed,
    code-defined ``FEATURE_VOCAB`` lands in ``features.py`` (Task 2); the
    annotation guard (Task 6) will validate each entry's feature/ECO
    references against that closed vocabulary once it exists (Req 6.2).
    """
    path = Path(path)
    if not path.exists():
        raise PedagogyError(f"knowledge resource file not found: {path}")

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise PedagogyError(f"{path}: invalid YAML: {e}") from e

    if not isinstance(data, dict):
        raise PedagogyError(f"{path}: top level must be a mapping with a 'version' and an 'entries' list")
    version = str(data.get("version") or "")
    if not version:
        raise PedagogyError(f"{path}: missing 'version'")
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise PedagogyError(f"{path}: 'entries' must be a non-empty list")

    entries = tuple(_parse_entry(e, i) for i, e in enumerate(raw_entries))

    # Duplicate-id guard — ids key the by_id lookup, so collisions would
    # silently shadow an entry. Catch them at load time (Req 1.9).
    seen: set[str] = set()
    for entry in entries:
        if entry.id in seen:
            raise PedagogyError(f"{path}: duplicate entry id {entry.id!r}")
        seen.add(entry.id)

    feature_vocab = frozenset().union(*(e.features for e in entries)) if entries else frozenset()
    eco_vocab = frozenset().union(*(e.eco_codes for e in entries)) if entries else frozenset()
    levels = frozenset().union(*(e.levels for e in entries)) if entries else frozenset()

    return KnowledgeResource(
        entries=entries,
        feature_vocab=feature_vocab,
        eco_vocab=eco_vocab,
        levels=levels,
    )


def default_resource_path() -> Path:
    """Repo-relative default location of the knowledge resource."""
    # src/chess_coach/pedagogy/resource.py -> repo root is three parents up.
    return Path(__file__).resolve().parents[3] / "data" / "pedagogy" / "knowledge.yaml"
