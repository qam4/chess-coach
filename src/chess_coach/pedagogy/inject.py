"""Coach-prompt injection for the pedagogy layer (Task 4.1).

The selector hands a list of :class:`~chess_coach.pedagogy.resource.GuidanceEntry`
records — the *what to focus on* half of the teaching bridge — to the
coach. This module renders those entries into a compact "What to focus
on" block that carries **both ends of the bridge** for every entry: its
named ``theme`` and its ``how_to_apply`` statement (Req 3.2).

The block is injected into ``build_rich_coaching_prompt`` *alongside* the
existing engine-grounding instructions — the grounding text is never
removed or weakened (Req 3.4). When the selection is empty (or becomes
empty after the level filter), the renderer returns the empty string so
callers can inject unconditionally and the prompt is built exactly as it
is today, with grounding intact and no guidance block (Req 3.6, 3.7).

Level filtering (Req 3.3) is enforced *here* as well as upstream: the
``Selector`` already drops entries whose recorded levels exclude the
student's level, but the renderer defensively re-applies the same filter
when given a ``level`` so that the injected prompt is level-appropriate by
construction regardless of how the entries were produced.
"""

from __future__ import annotations

from chess_coach.pedagogy.resource import GuidanceEntry

#: Header that marks the curated guidance block inside the coach prompt.
GUIDANCE_BLOCK_HEADER = "--- What to focus on ---"

#: One-line orientation so the coaching voice knows the block is the
#: curated "what to teach" standard, to be bridged to an engine-sound move.
_GUIDANCE_INTRO = (
    "Curated coaching themes selected for this position. Name the relevant "
    "theme and connect it to a concrete, engine-sound move from the data above."
)


def _level_filter(entries: list[GuidanceEntry], level: str | None) -> list[GuidanceEntry]:
    """Drop entries whose recorded levels exclude ``level`` (Req 3.3).

    A ``level`` of ``None`` disables the filter — callers that have
    already level-filtered upstream (the ``Selector``) can omit it.
    """
    if level is None:
        return list(entries)
    return [entry for entry in entries if entry.applies_to_level(level)]


def _render_entry(entry: GuidanceEntry) -> str:
    """Render one entry carrying both ends of the bridge (Req 3.2).

    Includes the named ``theme`` and the ``how_to_apply`` statement
    verbatim (plus the ``focus`` for context), so the coach prompt always
    contains both bridge ends for the entry.
    """
    return f"{entry.theme} — {entry.focus} How to apply: {entry.how_to_apply}"


def render_guidance_entries(
    entries: list[GuidanceEntry],
    level: str | None = None,
) -> list[str]:
    """Render the selected entries to a list of per-entry bullet lines.

    Applies the level filter (Req 3.3) and returns one ``"- ..."`` line
    per surviving entry. Returns an empty list when nothing survives, so
    callers (the template focus section and the prompt block) can decide
    whether to emit a section header at all.
    """
    return [f"- {_render_entry(entry)}" for entry in _level_filter(entries, level)]


def format_guidance_block(
    entries: list[GuidanceEntry],
    level: str | None = None,
) -> str:
    """Render the selected entries into the "What to focus on" block.

    For each surviving entry the block carries both its named theme and
    its how-to-apply statement — both ends of the teaching bridge (Req
    3.2). Returns the empty string for an empty selection (or an empty
    selection after the level filter), so callers can inject the result
    unconditionally without changing the prompt when there is no guidance
    (Req 3.6, 3.7).

    Args:
        entries: The selector-chosen guidance entries.
        level: When provided, entries whose recorded levels exclude this
            level are dropped before rendering (Req 3.3). When ``None``
            the entries are rendered as given (level filtering already
            happened upstream in the ``Selector``).

    Returns:
        The formatted guidance block, or ``""`` when there is nothing to
        inject.
    """
    lines = render_guidance_entries(entries, level)
    if not lines:
        return ""
    return "\n".join([GUIDANCE_BLOCK_HEADER, _GUIDANCE_INTRO, *lines])
