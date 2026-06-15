"""Pedagogy layer: the curated "what to teach" knowledge resource.

See `.kiro/specs/pedagogy-layer/`. The layer grounds the *first end of
the teaching bridge* — what to focus on — from chess authority rather
than the LLM's own chess sense. It holds curated principles, patterns,
and plans (the `Knowledge_Resource`), a deterministic selector that
picks the entries fitting a position, and two injection points that feed
the same selected guidance into both the coach prompt and the judge
prompt.

This module exposes the guidance data model; the loader, selector,
feature extraction, prompt injection, and annotation guard build on it.
"""

from __future__ import annotations

from .resource import (
    ExamplePosition,
    GuidanceEntry,
    KnowledgeResource,
    PedagogyError,
)

__all__ = [
    "ExamplePosition",
    "GuidanceEntry",
    "KnowledgeResource",
    "PedagogyError",
]
