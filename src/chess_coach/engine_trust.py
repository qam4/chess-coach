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
    # --- ComparisonReport: eval-derived, now withheld from every coach surface ---
    #
    # These five were USED_UNVERIFIED until "stop asserting magnitude" (ledger row 63)
    # took them out of the prompt, the templates, the composed fallback and the web
    # badge. They still drive the coach INTERNALLY -- the severity tier, the word
    # limit, and the rule that keeps the coach silent on good moves are all computed
    # from eval_drop_cp -- so the drop is about what we ASSERT, not about what we read.
    # That distinction is the reinstatement criterion's whole point: the numbers become
    # sayable again when they are trustworthy, not when they are merely present.
    _t(
        "ComparisonReport.eval_drop_cp",
        DROPPED,
        EVAL,
        "Was rendered as 'Evaluation drop: N centipawns' when it is not in centipawns "
        "-- Blunder's pawn is 124 (MG) to 206 (EG), unnormalized -- and the magnitude "
        "is off by a signed +122cp on the turns the coach speaks. Now withheld from "
        "every coach surface. Still used internally to pick the severity tier and the "
        "word limit, and to decide whether to speak at all, which are OUR bands on OUR "
        "side of the boundary.",
        "ledger rows 60-63",
        reinstate_when=REFERENCE_CRITERION + ", and the unit relabelled or converted",
        compensated_by="the tier still scales tone and length; severity reaches the "
        "student as the board-verified consequence (what the opponent's reply wins)",
    ),
    _t(
        "ComparisonReport.user_eval_cp",
        DROPPED,
        EVAL,
        "Same unit problem; was rendered as 'centipawns'. Withheld.",
        "ledger rows 60, 63",
        reinstate_when=REFERENCE_CRITERION,
        compensated_by="describe_eval states the standing qualitatively where a standing is wanted at all",
    ),
    _t(
        "ComparisonReport.best_eval_cp",
        DROPPED,
        EVAL,
        "Same unit problem; was rendered as 'centipawns'. Withheld.",
        "ledger rows 60, 63",
        reinstate_when=REFERENCE_CRITERION,
        compensated_by="the engine's move ORDERING is kept, which is the part a 2500 "
        "engine is good at; the menu tag says which moves may be named",
    ),
    _t(
        "ComparisonReport.classification",
        DROPPED,
        EVAL,
        "The engine's verdict, formerly relayed verbatim into three prompt templates "
        "and out to the web badge. Its cut points sit on unnormalized units -- it calls "
        "a 37cp drop an 'inaccuracy', which is roughly 18-30 conventional cp, i.e. "
        "nothing -- and their provenance is unknown. No longer reaches the prompt or "
        "the student. Note it is still the value returned on MoveEvaluation and stored "
        "in eval transcripts, where it is a research field, not a claim.",
        "ledger rows 62-63; threshold extraction over 170 engine-labelled drops",
        reinstate_when="cut points are defined on normalized units AND " + REFERENCE_CRITERION,
        compensated_by="our own severity tier, computed from client-owned bands, plus "
        "a board-side material check for the severe cases",
    ),
    _t(
        "ComparisonReport.nag",
        DROPPED,
        EVAL,
        "Annotation glyph, same eval basis as classification. Withheld.",
        "ledger rows 62-63",
        reinstate_when="as classification",
        compensated_by="the coach names a stronger move instead of annotating the played one",
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
        USED_UNVERIFIED,
        PROSE,
        "A CATEGORY LABEL, not a fact: 44 turns produced only 10 distinct values ('king "
        "safety -- repositioning the king' x13). Still rendered, deliberately, but never "
        "alone -- it trails a composed board clause as the theme, '(piece activity -- "
        "improving piece placement)', which is ledger row 9 kept and row 13 made "
        "sufficient. It is NOT a partial drop: the position report has no such field, so "
        "there is no second path to be inconsistent with. The v1 template that rendered "
        "it as the ONLY explanation was deleted at row 63.\n"
        "Recorded honestly after an earlier version of this entry claimed it was fully "
        "dropped -- reading a real rendered prompt showed the label still there.",
        "ledger rows 9, 13, and row 63; report card 'an empty slot is worse than no slot'",
        reinstate_when="the label is derived per-phase and validated against the board, not emitted from the eval",
        compensated_by="a composed, board-derived clause always precedes it, and "
        "_label_wrong_for_phase suppresses it where the phase makes it wrong",
    ),
    _t(
        "ComparisonReport.critical_reason",
        DROPPED,
        PROSE,
        "Only ever formatted as 'eval spread between best and 3rd-best line is 107cp', "
        "which voices our eval bookkeeping at the student. Suppressed on the move path "
        "at v27 and, at row 63, on the position path too -- it was the last live half "
        "of a drop this register had recorded as partial.",
        "report card, 'Stop manufacturing fault + stop voicing eval bookkeeping'; row 63",
        reinstate_when="it carries a board-derived reason rather than an eval spread",
        compensated_by="the critical_moment flag alone, without the numeric reason",
    ),
    _t(
        "ComparisonReport.top_lines",
        USED_UNVERIFIED,
        EVAL,
        "Mixed, and the mix is now split. PVLine.moves are legality-checkable and their "
        "ORDER is the engine's preference, which is what we kept. PVLine.eval_cp is no "
        "longer rendered anywhere (row 63). PVLine.theme is engine prose. What remains "
        "unverified is the part that still SPEAKS: the move menu's best/sound/dubious/"
        "blunder tags are computed from eval_cp against the 50/100 thresholds, so a tag "
        "inherits the magnitude problem even though the number behind it is hidden. "
        "Deliberately not fixed with the rest: re-deriving the tags means choosing new "
        "bands, and choosing bands by hand is what produced the current ones.",
        "ledger rows 60-63",
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
        DROPPED,
        EVAL,
        "Same unit and magnitude problem as the comparison evals. The FIGURE is dropped "
        "-- it was rendered as 'Overall evaluation: N centipawns' and the prompt now "
        "carries a qualitative standing instead -- but the 30/100/300 bands behind that "
        "wording are still eval-derived and still inherit the problem: a position at "
        "-102 units reads 'clear advantage' where deflated it is a slight edge. Being "
        "~3x apart makes them less brittle than the 50/100 move bands; how often they "
        "land the wrong side of a boundary is NOT measured. Recorded as partial rather "
        "than claimed as safe.",
        "ledger rows 60-63",
        reinstate_when=REFERENCE_CRITERION,
        compensated_by="describe_eval renders one of four coarse words with no figure, "
        "which is a smaller claim than a number even where the band is wrong",
    ),
    _t(
        "PositionReport.eval_breakdown",
        DROPPED,
        EVAL,
        "material / mobility / king_safety / pawn_structure / tempo / piece_bonuses are "
        "the eval TERMS, in Blunder units. 'material: 206' reads as two pawns and means "
        "one. The two that were rendered ('Material: N cp', 'Mobility: N cp') are gone "
        "and nothing replaced them. A board-derived material count was written and then "
        "REMOVED: substituting our own chess logic for an untrustworthy engine field is "
        "the thing the division of labour forbids, and piece values are contested "
        "knowledge. This is therefore a real capability gap, deliberately left open -- "
        "the coach cannot state the material balance. It is not fatal, because the "
        "placement block lists every piece, so the model can count and verify.py checks "
        "what it claims. The remaining terms are still read by describe_eval to name the "
        "DOMINANT factor, which is a comparison between terms rather than a magnitude.",
        "ledger rows 60, 63 (pawn = 124 MG / 206 EG, unnormalized)",
        reinstate_when="terms are normalized, or converted at our boundary",
        compensated_by="",
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
        DROPPED,
        PROSE,
        "Was the live leak this register was written to catch: suppressed on the "
        "move-feedback path at v27 and still rendered on the position path. Closed at "
        "row 63 -- the position prompt now shows the critical-moment flag with no "
        "reason attached, matching the move path.",
        "report card, 'stop voicing eval bookkeeping'; row 63",
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
