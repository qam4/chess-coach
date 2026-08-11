"""Pure selection logic for the pedagogy layer (Task 3).

The ``Selector`` answers the question *which curated Guidance_Entries fit
this position?* It is a **pure function** of its inputs — no I/O, no
engine, no network (Req 7.2, 7.4) — so it is cheap to hammer with
Hypothesis and trivially satisfies the offline guarantees. The engine is
needed only once, up front, to produce the ``PositionReport`` the feature
set is extracted from; the selection itself reads nothing but its
arguments.

Two entry points:

* :func:`select` is the pure core. It takes an already-extracted
  :class:`SelectionInput` (feature set, ECO context, level, cap) and the
  :class:`~chess_coach.pedagogy.resource.KnowledgeResource`, and returns
  the fitting entries deterministically ordered and capped. See the
  design's 5-step algorithm and Correctness Properties 1-5.

* :func:`select_for_position` is the thin, position-aware wrapper. It
  guards a malformed position *before* feature extraction and surfaces it
  as an error with an empty result (Req 2.8), then extracts the feature
  set / ECO context and delegates to :func:`select`. It deliberately
  takes the engine's :class:`~chess_coach.models.PositionReport` (which
  carries the analyzed FEN) rather than a bare FEN string, because
  extracting the position features requires that analysis; the wrapper's
  only added concerns are the malformed-position guard and the
  feature/ECO extraction, leaving :func:`select` pure over a feature set.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

from chess_coach.models import PositionReport
from chess_coach.pedagogy.features import eco_context, extract_features
from chess_coach.pedagogy.resource import GuidanceEntry, KnowledgeResource

# Type ordering for the relevance tie-break: a Plan is the most specific
# (it is keyed to a concrete opening context), a Pattern next, a Principle
# last (most general). Lower rank sorts earlier.
_TYPE_RANK: dict[str, int] = {"plan": 0, "pattern": 1, "principle": 2}
_TYPE_RANK_FALLBACK = 99  # any unexpected type sorts after the known ones


@dataclass(frozen=True)
class SelectionInput:
    """The position-derived inputs the pure :func:`select` keys off.

    ``features`` is the extracted ``Position_Feature`` set, ``eco`` the
    opening context (or ``None`` when unknown), ``level`` the student's
    coaching level, and ``max_entries`` the configured cap (Req 2.3, an
    integer ``>= 1``).
    """

    features: frozenset[str]
    eco: str | None
    level: str
    max_entries: int
    preferred_features: frozenset[str] = frozenset()
    """Soft ranking bias toward these features (e.g. the recommended move's
    theme). Additive only — never admits or drops an entry, just reorders
    ties (grounded-move-advice Req 4.2)."""

    fact_features: frozenset[str] = frozenset()
    """Features for which a verified board fact can be composed, so the entry
    can be *instantiated* rather than stated abstractly.

    Its own rank key rather than extra weight inside ``preferred_features``,
    because the two biases cancelled when combined: the PV theme "piece
    development" maps to the broad ``phase:opening`` feature, so the theme bonus
    went to every abstract opening entry too and the id tie-break then picked the
    abstraction.

    Ranked BELOW ``preferred_features``. A first version put it above, and the
    coach report card showed the cost: "rooks on open files" guidance appeared on
    8 turns, and on 6 of them the move being taught was a KING move — because
    ``open_file`` has a composable fact and so outranked the entry that actually
    matched the move. Guidance about the wrong piece is worse than guidance that
    is abstract, so matching the move comes first and instantiability breaks the
    remaining ties. Still a tie-break either way: it never admits or drops an
    entry, and a genuinely more relevant entry always wins."""

    def __post_init__(self) -> None:
        if self.max_entries < 1:
            raise ValueError(f"max_entries must be >= 1, got {self.max_entries}")


def _eco_matches(entry: GuidanceEntry, eco: str | None) -> bool:
    """True when ``entry`` is a Plan whose ECO codes include ``eco`` (Req 2.2)."""
    return eco is not None and entry.type == "plan" and eco in entry.eco_codes


def _feature_matches(entry: GuidanceEntry, features: frozenset[str]) -> bool:
    """True when every recorded feature of ``entry`` is present (Req 2.1).

    An entry with no recorded features never matches here — it can only be
    selected via the ECO path (design step 1).
    """
    return bool(entry.features) and entry.features <= features


def _relevance(entry: GuidanceEntry, inp: SelectionInput) -> int:
    """Relevance score for ranking: the number of matched keys.

    Counts the recorded features present in the position, plus one for an
    ECO-keyed Plan match so a plan that fits the opening context ranks
    sensibly alongside feature-matched entries (design step 5).
    """
    score = len(entry.features & inp.features)
    if _eco_matches(entry, inp.eco):
        score += 1
    return score


def _sort_key(entry: GuidanceEntry, inp: SelectionInput) -> tuple[int, int, int, int, str]:
    """Total, deterministic ordering key (Req 2.4, 2.6).

    Primary: relevance descending (more matched keys first) — negated so a
    plain ascending sort puts the most relevant first. Secondary: a soft bias
    toward the recommended move's theme (``preferred_features``), so the taught
    principle is about the move being taught (grounded-move-advice Req 4.2).
    Tertiary: whether the entry can be instantiated with a verified board fact
    (``fact_features``) — among entries equally relevant AND equally on-theme,
    prefer the one that can state a fact instead of an abstraction. Then type
    order plan > pattern > principle. Final tie-break: ascending ``id`` for a
    stable, total order.

    The theme bias sits above the fact bias on measured evidence: with the order
    reversed, "rooks on open files" was selected on six turns whose best move was
    a king move, because ``open_file`` carries a composable fact. Both remain
    additive, so neither changes which entries are eligible.
    """
    preferred_bonus = len(entry.features & inp.preferred_features)
    has_fact = 1 if entry.features & inp.fact_features else 0
    return (
        -_relevance(entry, inp),
        -preferred_bonus,
        -has_fact,
        _TYPE_RANK.get(entry.type, _TYPE_RANK_FALLBACK),
        entry.id,
    )


def select(resource: KnowledgeResource, inp: SelectionInput) -> list[GuidanceEntry]:
    """Return the Guidance_Entries that fit this position.

    Pure function of ``(resource, inp)`` implementing the design's
    five-step algorithm:

    1. **Feature match** — keep every entry all of whose recorded features
       are present in ``inp.features`` (Req 2.1).
    2. **ECO match** — additionally keep every Plan whose recorded ECO
       codes include ``inp.eco`` (Req 2.2).
    3. **Level filter** — drop entries whose recorded levels do not
       include ``inp.level`` so the coach and judge see the same
       level-appropriate set (design step 3).
    4. **Fallback** — if steps 1-2 (after the level filter) yield nothing,
       return the foundational Principle entries whose levels include
       ``inp.level`` (Req 2.5).
    5. **Rank & cap** — order by relevance (matched-key count desc, then
       plan > pattern > principle, then ascending ``id``) and truncate to
       ``inp.max_entries`` (Req 2.3, 2.4).

    Determinism falls out of using only the inputs and a total order on
    ``id`` (Req 2.6); referential integrity falls out of only ever
    returning entries drawn from ``resource`` (Req 2.7).
    """
    # Steps 1-3: feature/ECO match, then level filter. A dict keyed by id
    # both de-duplicates a plan that matches on both features and ECO and
    # preserves only resource entries (referential integrity, Req 2.7).
    matched: dict[str, GuidanceEntry] = {}
    for entry in resource.entries:
        if inp.level not in entry.levels:
            continue
        if _feature_matches(entry, inp.features) or _eco_matches(entry, inp.eco):
            matched[entry.id] = entry

    # Step 4: fallback to level-appropriate foundational principles.
    if matched:
        candidates = list(matched.values())
    else:
        candidates = [e for e in resource.principles() if inp.level in e.levels]

    # Step 5: rank by relevance with the deterministic tie-break, then cap.
    candidates.sort(key=lambda e: _sort_key(e, inp))
    return candidates[: inp.max_entries]


def select_for_position(
    resource: KnowledgeResource,
    report: PositionReport,
    level: str,
    max_entries: int,
    preferred_features: frozenset[str] = frozenset(),
    fact_features: frozenset[str] = frozenset(),
) -> tuple[list[GuidanceEntry], str | None]:
    """Select guidance for an analyzed position, guarding malformed input.

    Wraps the pure :func:`select` with the position-aware concerns the
    selector needs but :func:`select` deliberately stays free of: it
    validates ``report.fen`` *before* feature extraction and, if the
    position is malformed or invalid, returns no entries plus an error
    indication (Req 2.8); otherwise it extracts the feature set and ECO
    context and delegates to :func:`select`.

    Returns ``(entries, error)``: on success ``error`` is ``None``; on a
    malformed position ``entries`` is empty and ``error`` is a
    human-readable indication of why the position was rejected.

    The engine's :class:`~chess_coach.models.PositionReport` is taken
    (rather than a bare FEN) because feature extraction reads the engine's
    analysis; this wrapper performs no engine, network, or file I/O beyond
    the local opening-book lookup, so the offline guarantees hold (Req
    7.2, 7.4).
    """
    try:
        chess.Board(report.fen)
    except ValueError as exc:
        return [], f"malformed position: {report.fen!r} ({exc})"

    inp = SelectionInput(
        features=extract_features(report),
        eco=eco_context(report.fen),
        level=level,
        max_entries=max_entries,
        preferred_features=preferred_features,
        fact_features=fact_features,
    )
    return select(resource, inp), None


def guidance_for_position(
    resource: KnowledgeResource,
    report: PositionReport,
    level: str,
    max_entries: int,
    preferred_features: frozenset[str] = frozenset(),
    fact_features: frozenset[str] = frozenset(),
) -> list[GuidanceEntry]:
    """The single source of guidance for BOTH prompts (Req 4.1, 4.5).

    The harness builds **one** selection per position with this helper and
    hands the identical list to the coach prompt (``build_rich_coaching_prompt``)
    and the judge prompt (``build_judge_prompt``). Routing both through the
    one ``Selector`` over the one ``KnowledgeResource`` guarantees the judge
    grades ``teaches_principle`` against the very guidance the coach was
    given — there is no second selection path that could drift (design's
    single-source decision; Property 9).

    Returns the selected entries (already feature/ECO-matched, level-filtered,
    ranked, and capped by :func:`select`). A malformed position yields an
    empty list, exactly as :func:`select_for_position` reports; the error
    indication is dropped here because both prompts treat an empty selection
    the same way — the coach omits the guidance block and the judge omits the
    ``teaches_principle`` criterion (Req 3.6, 4.6). Callers needing the error
    indication should use :func:`select_for_position` directly.
    """
    entries, _error = select_for_position(resource, report, level, max_entries, preferred_features, fact_features)
    return entries
