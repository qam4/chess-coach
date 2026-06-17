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
#: curated "what to teach" standard, to be bridged to an engine-sound move —
#: with an explicit anti-fabrication clause. Applying a theme must never
#: tempt the model into asserting a concrete tactic/move that the analysis
#: does not actually show (the factual-regression failure mode seen when
#: guidance was switched on for qwen3:14b: teaching-more led to
#: asserting-more-wrong). The base SYSTEM_PROMPT_V2 grounding rules still
#: apply; this reinforces them specifically for the curated themes.
_GUIDANCE_INTRO = (
    "Curated coaching themes selected for this position. Name the most "
    "relevant theme and connect it to a concrete, engine-sound move FROM THE "
    "ANALYSIS ABOVE. Apply a theme only if the analysis actually shows it: "
    "never invent a move, capture, threat, or tactic to fit a theme — if the "
    "pattern is not in the data above, teach the idea in general terms instead."
)

#: Header that marks the curated teaches_principle standard inside the judge
#: prompt (Req 4.2).
JUDGE_GUIDANCE_HEADER = "--- teaches_principle standard (curated guidance) ---"

#: Instruction telling the judge to grade ``teaches_principle`` ONLY against
#: the curated guidance and not its own chess knowledge (Req 4.2, 4.3, 4.4).
_JUDGE_GUIDANCE_INTRO = (
    "Grade the teaches_principle criterion ONLY against the curated guidance "
    "below — this guidance is the sole standard for that criterion. Do NOT "
    "rely on chess knowledge outside this guidance. A response passes "
    "teaches_principle only when it names and soundly applies one of these "
    "themes in THIS position; if it teaches a principle that is absent from "
    "or contradicts this guidance, fail teaches_principle and name the "
    "unsupported or contradicting principle."
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


def format_judge_guidance_block(entries: list[GuidanceEntry]) -> str:
    """Render the selected entries as the sole standard for the judge's
    ``teaches_principle`` criterion (Req 4.2, 4.3).

    The block carries, for each entry, both ends of the teaching bridge
    (its named theme and its how-to-apply statement) plus an instruction
    telling the judge to grade ``teaches_principle`` ONLY against this
    guidance and not its own chess knowledge. Mirrors the coach block's
    per-entry rendering (``_render_entry``) so the judge sees exactly the
    same guidance text the coach was given (single-source parity, Req
    4.5).

    Unlike :func:`format_guidance_block`, no level filter is applied here:
    the entries handed to the judge are the identical list produced once by
    the ``Selector`` (already level-filtered) and shared with the coach, so
    re-filtering could only introduce divergence.

    Returns the empty string for an empty selection, so the caller can omit
    the ``teaches_principle`` standard (and the criterion itself) when there
    is no guidance for the position (Req 4.6).
    """
    lines = render_guidance_entries(entries, level=None)
    if not lines:
        return ""
    return "\n".join([JUDGE_GUIDANCE_HEADER, _JUDGE_GUIDANCE_INTRO, *lines])
