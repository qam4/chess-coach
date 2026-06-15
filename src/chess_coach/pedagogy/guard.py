"""Annotation guard for the pedagogy layer (Task 6).

Mirrors the benchmark annotation guard (``eval/annotations.py`` +
``scripts/eval_check_annotations.py``): every curated ``GuidanceEntry``
is validated *before* it is visible to the ``Selector`` so the resource
never feeds ungrounded "what to teach" guidance into the coach or judge
(Req 6.1).

Each entry is checked, in order, using **only the schema and the
engine** — never an LLM (Req 6.7):

1. **Required fields** present and non-empty (Req 6.5).
2. **Referential integrity** — every referenced ``Position_Feature`` is
   in the closed, code-defined ``FEATURE_VOCAB`` (Task 2) and every
   ``ECO_Code`` is a well-formed ECO code (Req 6.2).
3. **Example legality** — where an entry carries a concrete example
   (``example_fen`` + ``example_move``), the move is legal in that
   position via ``python-chess`` (Req 6.3).
4. **Engine soundness** — where an example exists *and* an engine is
   supplied, the engine's ``compare`` must not classify the move as a
   blunder/losing move (Req 6.4). This is the only engine-bound check;
   it is skipped when ``engine is None`` so the schema/ref/legality
   checks run fully offline with no engine and no network (Req 7.2,
   7.4).

A failing entry is rejected *individually*: its id and the reasons are
recorded, it is withheld from the admitted set, and the batch continues
with the remaining entries (Req 6.6). Only admitted entries are returned
for the ``Selector`` (Req 6.1).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

import chess

from chess_coach.models import ComparisonReport
from chess_coach.pedagogy.features import FEATURE_VOCAB
from chess_coach.pedagogy.resource import (
    GUIDANCE_TYPES,
    LEVELS,
    GuidanceEntry,
)

# Well-formed ECO code: a single letter A-E followed by two digits
# (A00-E99). The design allows validating ECO references either against
# the resource's eco_vocab or against this canonical format; the format
# whitelist is chosen here because ECO is a fixed, externally-defined
# encoding (Encyclopaedia of Chess Openings) and a malformed code is the
# real authoring error the guard must catch (Req 6.2).
ECO_PATTERN = re.compile(r"^[A-E][0-9]{2}$")

# Engine classifications that mean the example move throws the game —
# the engine is the source of truth (Req 6.4). The Blunder coaching
# protocol emits one of {good, inaccuracy, mistake, blunder}; "blunder"
# is the losing/blunder category an engine-sound example must avoid.
UNSOUND_CLASSIFICATIONS = frozenset({"blunder"})

# Required non-empty fields on every entry (Req 6.5). Mirrors the loader's
# _REQUIRED_STR_FIELDS so the guard independently re-verifies presence and
# non-emptiness even for entries built outside the loader.
_REQUIRED_STR_FIELDS = ("id", "type", "theme", "focus", "how_to_apply", "citation")


class SoundnessEngine(Protocol):
    """The narrow engine interface the soundness check depends on.

    Declared as a ``Protocol`` so the guard never imports the concrete
    :class:`~chess_coach.engine.CoachingEngine` (keeping the
    schema/ref/legality path free of any engine dependency) and so tests
    can pass a lightweight stub returning a canned comparison report.
    """

    def get_comparison_report(
        self,
        fen: str,
        user_move: str,
        depth: int | None = None,
        movetime: int | None = None,
    ) -> ComparisonReport: ...


@dataclass(frozen=True)
class GuardResult:
    """Outcome of validating one entry.

    Mirrors the benchmark guard's mismatch-message style: ``reasons`` is
    empty iff the entry is admitted, and otherwise names every reason the
    entry was rejected so an author can fix them all at once.
    """

    entry_id: str
    admitted: bool
    reasons: tuple[str, ...]  # empty iff admitted


def _check_required_fields(entry: GuidanceEntry) -> list[str]:
    """Required-field presence and non-emptiness (Req 6.5)."""
    reasons: list[str] = []
    for field in _REQUIRED_STR_FIELDS:
        value = getattr(entry, field)
        if not isinstance(value, str) or not value.strip():
            reasons.append(f"required field {field!r} is missing or empty")
    if entry.type not in GUIDANCE_TYPES:
        reasons.append(f"field 'type' must be one of {sorted(GUIDANCE_TYPES)}, got {entry.type!r}")
    if not entry.levels:
        reasons.append(f"field 'levels' must be a non-empty subset of {sorted(LEVELS)}")
    else:
        bad_levels = entry.levels - LEVELS
        if bad_levels:
            reasons.append(f"field 'levels' has values outside {sorted(LEVELS)}: {sorted(bad_levels)}")
    return reasons


def _check_referential_integrity(entry: GuidanceEntry, feature_vocab: frozenset[str]) -> list[str]:
    """Feature/ECO references drawn from the defined sets (Req 6.2)."""
    reasons: list[str] = []
    bad_features = entry.features - feature_vocab
    if bad_features:
        reasons.append(f"references Position_Features outside the defined set: {sorted(bad_features)}")
    bad_eco = sorted(code for code in entry.eco_codes if not ECO_PATTERN.match(code))
    if bad_eco:
        reasons.append(f"references malformed ECO codes (expected A00-E99): {bad_eco}")
    return reasons


def _check_example_legality(entry: GuidanceEntry) -> list[str]:
    """Where an example exists, its move must be legal (Req 6.3)."""
    if entry.example is None:
        return []
    try:
        board = chess.Board(entry.example.fen)
    except ValueError as exc:
        return [f"example FEN is not a valid position: {exc}"]
    try:
        move = chess.Move.from_uci(entry.example.move)
    except ValueError:
        return [f"example move {entry.example.move!r} is not valid UCI"]
    if move not in board.legal_moves:
        return [f"example move {entry.example.move!r} is illegal in the example position"]
    return []


def _check_example_soundness(
    entry: GuidanceEntry,
    engine: SoundnessEngine,
    depth: int | None,
) -> list[str]:
    """Where an example exists, the engine must not call it a blunder (Req 6.4).

    The only engine-bound check. Assumes legality has already passed (an
    illegal move is never sent to the engine).
    """
    if entry.example is None:
        return []
    report = engine.get_comparison_report(entry.example.fen, entry.example.move, depth=depth)
    classification = report.classification.strip().lower()
    if classification in UNSOUND_CLASSIFICATIONS:
        return [
            f"engine classifies example move {entry.example.move!r} as "
            f"{classification!r} (not engine-sound; eval drop {report.eval_drop_cp}cp)"
        ]
    return []


def validate_entry(
    entry: GuidanceEntry,
    *,
    feature_vocab: frozenset[str] = FEATURE_VOCAB,
    engine: SoundnessEngine | None = None,
    depth: int | None = None,
) -> GuardResult:
    """Validate one entry and return its :class:`GuardResult`.

    Runs the schema, referential-integrity, and example-legality checks
    using only the schema and ``python-chess`` (no engine). When
    ``engine`` is supplied and the entry carries a legal example, the
    engine-soundness check (Req 6.4) runs as well; with ``engine=None``
    the soundness check is skipped and validation is fully offline
    (Req 6.7, 7.2, 7.4). All failing reasons are collected so the author
    sees every problem at once.
    """
    reasons: list[str] = []
    reasons.extend(_check_required_fields(entry))
    reasons.extend(_check_referential_integrity(entry, feature_vocab))

    legality_reasons = _check_example_legality(entry)
    reasons.extend(legality_reasons)

    # Only consult the engine when the example is present and legal — an
    # illegal/malformed move must never reach the engine.
    if engine is not None and not legality_reasons:
        reasons.extend(_check_example_soundness(entry, engine, depth))

    return GuardResult(entry_id=entry.id, admitted=not reasons, reasons=tuple(reasons))


def guard_entries(
    entries: Iterable[GuidanceEntry],
    *,
    feature_vocab: frozenset[str] = FEATURE_VOCAB,
    engine: SoundnessEngine | None = None,
    depth: int | None = None,
) -> tuple[tuple[GuidanceEntry, ...], tuple[GuardResult, ...]]:
    """Validate a batch and return the admitted subset and all results.

    Per-entry isolation (Req 6.6): a failing entry is rejected with its
    id and reasons, withheld from the admitted subset, and the remaining
    entries are still validated. Only the admitted subset is intended to
    reach the ``Selector`` (Req 6.1).
    """
    entry_tuple = tuple(entries)
    results = tuple(
        validate_entry(entry, feature_vocab=feature_vocab, engine=engine, depth=depth) for entry in entry_tuple
    )
    admitted = tuple(entry for entry, result in zip(entry_tuple, results) if result.admitted)
    return admitted, results
