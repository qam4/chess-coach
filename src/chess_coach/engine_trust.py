"""What we believe from the engine, what we do not, and what would change our mind.

Why this exists
---------------
Measurement against Stockfish 18 established that Blunder's eval *magnitude* is not
trustworthy on quiet positions, and that everything downstream of it inherits the
problem -- the classification, the annotation, and the engine's own prose about its
evaluation. See ``docs/coach-report-card.md``, "Three problems, not one".

Dropping a field is the right response to untrustworthy data, but a silent drop is
a trap: the reason is forgotten, the engine is never fixed, and nobody notices when
a field creeps back in. Two "drops" recorded in the ledger turned out to be partial
-- ``critical_reason`` was suppressed on the move path and left live on the position
path, and ``best_move_idea`` survived in a v1 template after v26 removed it.

So each field carries a verdict, the reason, the evidence, a **measurable**
criterion for reinstating it, and what compensates for its absence. Where nothing
compensates, that is a capability gap and :func:`capability_gaps` reports it -- that
list is the priority queue for engine work, not a graveyard.

``tests/test_engine_trust.py`` fails if a report field has no entry, so a new engine
field cannot arrive without someone recording a judgement about it.
"""

from __future__ import annotations

import dataclasses
import typing
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------

BOARD_TRUTH = "board_truth"
"""We supply it, or it is trivially checkable. Believe it."""

BOARD_VERIFIED = "board_verified"
"""Engine-supplied, and checked against the board before the student sees it."""

BOARD_VERIFIABLE = "board_verifiable"
"""Checkable from the board in principle, but we do not check it yet. Debt."""

USED_UNVERIFIED = "used_unverified"
"""Sent to the model with no trust basis. The debt this module exists to expose."""

DROPPED = "dropped"
"""Deliberately not used. Needs a reason and a reinstatement criterion."""

DROPPED_PARTIAL = "dropped_partial"
"""Dropped on one path and still live on another. Always a defect."""

_VERDICTS = frozenset({BOARD_TRUTH, BOARD_VERIFIED, BOARD_VERIFIABLE, USED_UNVERIFIED, DROPPED, DROPPED_PARTIAL})

# A reinstatement criterion good enough to re-run rather than argue about. The
# harness that produced the original measurement is scripts/eval_check_breadth.py
# plus the Stockfish comparison described in the report card.
REFERENCE_CRITERION = (
    "mean absolute error under 25cp against Stockfish 18 at depth 22 on quiet "
    "positions, measured over at least five games"
)


@dataclass(frozen=True)
class FieldTrust:
    """Our standing judgement about one engine-reported field."""

    field: str
    """``ReportClass.field_name``."""

    verdict: str
    basis: str
    """Where trust would come from: board geometry, the eval, or engine prose."""

    reason: str
    evidence: str
    """Where to read the measurement. Ledger row or report-card section."""

    reinstate_when: str = ""
    """Measurable condition to start believing it. Required unless trusted."""

    compensated_by: str = ""
    """What covers the loss. Empty means a genuine capability gap."""

    def __post_init__(self) -> None:
        if self.verdict not in _VERDICTS:
            raise ValueError(f"{self.field}: unknown verdict {self.verdict!r}")
        if self.verdict in (DROPPED, DROPPED_PARTIAL, USED_UNVERIFIED) and not self.reinstate_when:
            raise ValueError(f"{self.field}: {self.verdict} needs a reinstate_when criterion")


def _t(field: str, verdict: str, basis: str, reason: str, evidence: str, **kw: str) -> FieldTrust:
    return FieldTrust(field=field, verdict=verdict, basis=basis, reason=reason, evidence=evidence, **kw)


EVAL = "eval magnitude"
PROSE = "engine prose about its own eval"
BOARD = "board geometry"


# ---------------------------------------------------------------------------
# The register
# ---------------------------------------------------------------------------

_ENTRIES: tuple[FieldTrust, ...] = (
    # --- ComparisonReport: things we supply or can check -------------------
    _t("ComparisonReport.fen", BOARD_TRUTH, BOARD, "We pass it in.", "n/a"),
    _t("ComparisonReport.user_move", BOARD_TRUTH, BOARD, "We pass it in.", "n/a"),
    _t(
        "ComparisonReport.best_move",
        BOARD_VERIFIED,
        BOARD,
        "Legality and piece identity are checked before the student sees it; its "
        "QUALITY is not, and agreed with Stockfish on only 4 of 18 spoken turns.",
        "report card, 'Three problems, not one'",
        reinstate_when="quality is out of scope for verification; treat the move as a "
        "suggestion rather than the best move until " + REFERENCE_CRITERION,
        compensated_by="verify.py gating checks (legality, ownership, relation, terminal)",
    ),
    _t(
        "ComparisonReport.missed_tactics",
        BOARD_VERIFIABLE,
        BOARD,
        "type/squares/pieces are structural -- a fork is a fork on the board -- but we "
        "do not currently re-derive them.",
        "audit of engine-consumed fields, 2026-08-21",
        reinstate_when="a board-side check re-derives motif type and squares, as "
        "verify.py already does for the coach's own claims",
        compensated_by="",
    ),
    _t(
        "ComparisonReport.refutation_line",
        BOARD_VERIFIABLE,
        BOARD,
        "A move sequence: legality is checkable. v30 added an opponent_reply check that covers the first ply only.",
        "ledger row for v30 (opponent_reply)",
        reinstate_when="every ply of the line is legality-checked, not just the first",
        compensated_by="verify.py opponent_reply check (first ply)",
    ),
    # --- ComparisonReport: eval-derived, currently used unverified ---------
    _t(
        "ComparisonReport.eval_drop_cp",
        USED_UNVERIFIED,
        EVAL,
        "Rendered to the model as 'Evaluation drop: N centipawns' when it is NOT in "
        "centipawns -- Blunder's pawn is 124 (MG) to 206 (EG), unnormalized. And the "
        "magnitude is off by a signed +92cp on quiet positions.",
        "ledger rows 60-62",
        reinstate_when=REFERENCE_CRITERION + ", and the unit relabelled or converted",
        compensated_by="",
    ),
    _t(
        "ComparisonReport.user_eval_cp",
        USED_UNVERIFIED,
        EVAL,
        "Same unit problem; rendered as 'centipawns'.",
        "ledger row 60",
        reinstate_when=REFERENCE_CRITERION,
        compensated_by="",
    ),
    _t(
        "ComparisonReport.best_eval_cp",
        USED_UNVERIFIED,
        EVAL,
        "Same unit problem; rendered as 'centipawns'.",
        "ledger row 60",
        reinstate_when=REFERENCE_CRITERION,
        compensated_by="",
    ),
    _t(
        "ComparisonReport.classification",
        USED_UNVERIFIED,
        EVAL,
        "The engine's verdict, relayed verbatim into three prompt templates. Its cut "
        "points sit on unnormalized units -- it calls a 37cp drop an 'inaccuracy', which "
        "is roughly 18-30 conventional cp, i.e. nothing. Provenance of the cut points "
        "is unknown.",
        "ledger row 62; threshold extraction over 170 engine-labelled drops",
        reinstate_when="cut points are defined on normalized units AND " + REFERENCE_CRITERION,
        compensated_by="a board-side material check covers the severe cases (see "
        "capability note on losing material for nothing)",
    ),
    _t(
        "ComparisonReport.nag",
        USED_UNVERIFIED,
        EVAL,
        "Annotation glyph, same eval basis as classification.",
        "ledger row 62",
        reinstate_when="as classification",
        compensated_by="",
    ),
    _t(
        "ComparisonReport.critical_moment",
        USED_UNVERIFIED,
        EVAL,
        "Boolean derived from eval spread between lines, so it inherits the magnitude "
        "problem. Measured as a speech trigger: fires on 13 silent turns to catch 1 "
        "worth catching.",
        "ledger row 52",
        reinstate_when=REFERENCE_CRITERION,
        compensated_by="",
    ),
    # --- ComparisonReport: already dropped, and one of them only partly ----
    _t(
        "ComparisonReport.best_move_idea",
        DROPPED_PARTIAL,
        PROSE,
        "A CATEGORY LABEL, not a fact. It said 'king safety -- repositioning the king' "
        "on endgame turns, which is where v24-v26 chased phantom king-safety talk before "
        "finding the engine was the source. Dropped from the shipping v2 template, but "
        "still rendered by RICH_MOVE_EVALUATION_PROMPT at prompts.py:309.",
        "ledger rows for v24-v26; report card 'an empty slot is worse than no slot'",
        reinstate_when="the label is derived per-phase and validated against the board, not emitted from the eval",
        compensated_by="compose_safe_move_feedback builds the same sentence from board facts",
    ),
    _t(
        "ComparisonReport.critical_reason",
        DROPPED_PARTIAL,
        PROSE,
        "Only ever formatted as 'eval spread between best and 3rd-best line is 107cp', "
        "which voices our eval bookkeeping at the student. Suppressed on the move path "
        "(prompts.py:1773) but STILL RENDERED on the position path (prompts.py:881).",
        "report card, 'Stop manufacturing fault + stop voicing eval bookkeeping'",
        reinstate_when="it carries a board-derived reason rather than an eval spread",
        compensated_by="the critical_moment flag alone, without the numeric reason",
    ),
    _t(
        "ComparisonReport.top_lines",
        USED_UNVERIFIED,
        EVAL,
        "Mixed: PVLine.moves are legality-checkable, PVLine.eval_cp carries the unit and "
        "magnitude problem, PVLine.theme is engine prose. The move menu's soundness tags "
        "are computed from these eval_cp values, so our own tags inherit it.",
        "ledger rows 60-62",
        reinstate_when="tags are computed from normalized units, or from board facts",
        compensated_by="",
    ),
    # --- PositionReport: the board-derivable half, which is the useful half ---
    _t("PositionReport.fen", BOARD_TRUTH, BOARD, "We pass it in.", "n/a"),
    _t(
        "PositionReport.hanging_pieces",
        BOARD_VERIFIABLE,
        BOARD,
        "square/piece/colour is pure geometry. This is the field that covers 'you left "
        "your queen for nothing' WITHOUT any eval, which is why dropping the magnitude "
        "does not cost us the severe cases.",
        "audit of engine-consumed fields, 2026-08-21",
        reinstate_when="re-derived board-side with attackers/defenders, as verify.py "
        "already does for the coach's own placement claims",
        compensated_by="python-chess attackers/defenders can compute this independently",
    ),
    _t(
        "PositionReport.threat_map",
        BOARD_VERIFIABLE,
        BOARD,
        "Attacker and defender counts per square, and net_attacked. Pure geometry.",
        "audit of engine-consumed fields, 2026-08-21",
        reinstate_when="re-derived board-side",
        compensated_by="python-chess can compute this independently",
    ),
    _t(
        "PositionReport.threat_map_summary",
        BOARD_VERIFIABLE,
        BOARD,
        "Summary over threat_map; same basis as the map itself.",
        "audit of engine-consumed fields, 2026-08-21",
        reinstate_when="re-derived board-side",
        compensated_by="derivable from threat_map",
    ),
    _t(
        "PositionReport.threats",
        BOARD_VERIFIABLE,
        BOARD,
        "Structural: a threatened piece is checkable.",
        "audit of engine-consumed fields, 2026-08-21",
        reinstate_when="re-derived board-side",
        compensated_by="python-chess can compute this independently",
    ),
    _t(
        "PositionReport.pawn_structure",
        BOARD_VERIFIABLE,
        BOARD,
        "Isolated, doubled and passed pawns are structural facts.",
        "audit of engine-consumed fields, 2026-08-21",
        reinstate_when="re-derived board-side",
        compensated_by="python-chess can compute this independently",
    ),
    _t(
        "PositionReport.tactics",
        BOARD_VERIFIABLE,
        BOARD,
        "As ComparisonReport.missed_tactics: type/squares/pieces structural, description is prose.",
        "audit of engine-consumed fields, 2026-08-21",
        reinstate_when="motif type and squares re-derived board-side; description dropped",
        compensated_by="",
    ),
    # --- PositionReport: eval-derived ---------------------------------------
    _t(
        "PositionReport.eval_cp",
        USED_UNVERIFIED,
        EVAL,
        "Same unit and magnitude problem as the comparison evals.",
        "ledger rows 60-62",
        reinstate_when=REFERENCE_CRITERION,
        compensated_by="",
    ),
    _t(
        "PositionReport.eval_breakdown",
        USED_UNVERIFIED,
        EVAL,
        "material / mobility / king_safety / pawn_structure / tempo / piece_bonuses are "
        "the eval TERMS, in Blunder units. 'material: 206' reads as two pawns and means "
        "one.",
        "ledger row 60 (pawn = 124 MG / 206 EG, unnormalized)",
        reinstate_when="terms are normalized, or converted at our boundary",
        compensated_by="material specifically is recomputable from the board",
    ),
    _t(
        "PositionReport.king_safety",
        USED_UNVERIFIED,
        EVAL,
        "score is eval-derived and description is prose. king_square, castling_status and "
        "missing_shield_files are board facts and separable. This is the field behind "
        "three runs of phantom king-safety talk in endgames.",
        "report card, v24-v26 king-safety saga",
        reinstate_when="score normalized and phase-aware; description dropped in favour of the board-fact subfields",
        compensated_by="king_square / castling_status / missing_shield_files are board facts",
    ),
    _t(
        "PositionReport.top_lines",
        USED_UNVERIFIED,
        EVAL,
        "As ComparisonReport.top_lines: moves checkable, eval_cp and theme not.",
        "ledger rows 60-62",
        reinstate_when="as ComparisonReport.top_lines",
        compensated_by="",
    ),
    _t(
        "PositionReport.critical_moment",
        USED_UNVERIFIED,
        EVAL,
        "As ComparisonReport.critical_moment.",
        "ledger row 52",
        reinstate_when=REFERENCE_CRITERION,
        compensated_by="",
    ),
    _t(
        "PositionReport.critical_reason",
        DROPPED_PARTIAL,
        PROSE,
        "THIS is the live leak: suppressed on the move-feedback path but still rendered "
        "on the position path at prompts.py:881.",
        "report card, 'stop voicing eval bookkeeping'",
        reinstate_when="it carries a board-derived reason rather than an eval spread",
        compensated_by="the critical_moment flag alone",
    ),
)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

BY_FIELD: dict[str, FieldTrust] = {e.field: e for e in _ENTRIES}


def entries() -> tuple[FieldTrust, ...]:
    """Every recorded judgement."""
    return _ENTRIES


def with_verdict(*verdicts: str) -> tuple[FieldTrust, ...]:
    """Entries matching any of ``verdicts``."""
    return tuple(e for e in _ENTRIES if e.verdict in verdicts)


def capability_gaps() -> tuple[FieldTrust, ...]:
    """Fields we cannot trust and have nothing to replace with.

    This is the priority queue for engine work. A field in here means the coach is
    measurably worse off, not merely quieter.
    """
    return tuple(
        e for e in _ENTRIES if e.verdict in (USED_UNVERIFIED, DROPPED, DROPPED_PARTIAL) and not e.compensated_by
    )


def inconsistent() -> tuple[FieldTrust, ...]:
    """Fields dropped on one path and live on another. Always defects."""
    return with_verdict(DROPPED_PARTIAL)


def covered_fields(report_cls: type) -> set[str]:
    """Field keys expected for ``report_cls`` given its dataclass fields."""
    if not dataclasses.is_dataclass(report_cls):
        raise TypeError(f"{report_cls!r} is not a dataclass")
    return {f"{report_cls.__name__}.{f.name}" for f in dataclasses.fields(report_cls)}


def missing_for(report_cls: type) -> set[str]:
    """Fields of ``report_cls`` with no recorded judgement."""
    return covered_fields(report_cls) - set(BY_FIELD)


def format_report() -> str:
    """Human-readable summary, for a doc or a console."""
    lines: list[str] = []
    for verdict in (DROPPED_PARTIAL, USED_UNVERIFIED, DROPPED, BOARD_VERIFIABLE, BOARD_VERIFIED, BOARD_TRUTH):
        group = with_verdict(verdict)
        if not group:
            continue
        lines.append(f"## {verdict} ({len(group)})")
        for e in group:
            gap = "" if e.compensated_by else "   [CAPABILITY GAP]"
            lines.append(f"- {e.field}{gap}")
            lines.append(f"    basis: {e.basis}")
            lines.append(f"    why:   {e.reason}")
            if e.reinstate_when:
                lines.append(f"    trust it again when: {e.reinstate_when}")
            if e.compensated_by:
                lines.append(f"    covered by: {e.compensated_by}")
        lines.append("")
    return "\n".join(lines)


__all__ = [
    "BOARD_TRUTH",
    "BOARD_VERIFIABLE",
    "BOARD_VERIFIED",
    "BY_FIELD",
    "DROPPED",
    "DROPPED_PARTIAL",
    "REFERENCE_CRITERION",
    "USED_UNVERIFIED",
    "FieldTrust",
    "capability_gaps",
    "covered_fields",
    "entries",
    "format_report",
    "inconsistent",
    "missing_for",
    "with_verdict",
]

if typing.TYPE_CHECKING:  # pragma: no cover
    pass
