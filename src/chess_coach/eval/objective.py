"""Layer 1 — objective, engine-grounded checks.

Deterministic checks of a coaching response against ground truth
(the board and the engine's `PositionReport`). No LLM, no human, no
cost. This is the half of "does the model know chess" that we can
verify mechanically because chess-coach has an oracle.

Checks:

- **Piece hallucination** — "piece on square" claims that don't match
  the board.
- **Illegal move** — moves mentioned in the text that aren't legal.
- **Eval direction** — does a stated who's-better claim contradict the
  sign of the engine eval? (Conservative: only flags a *backwards*
  winner, never a near-equal judgment call.)
- **Key-fact coverage** — does the response reference the position's
  annotated ground-truth points (the hanging piece the engine found,
  the tactic, etc.)?

`evaluate_objective()` combines these into an `ObjectiveResult` with a
`factual_score`. Hallucinations and illegal moves are multiplicative
hard penalties — a single one drops the score well below the pass
threshold, because the entire point of the score is trust.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from ..coaching_phrases import build_move_menu
from ..models import PositionReport
from ..verify import check_coaching_fidelity, check_text_fidelity
from .benchmark import BenchmarkPosition, GroundTruthPoint

# Coaching on a position within this many centipawns of zero is treated
# as "equal" for the direction check. Deliberately more lenient than
# the templates' band so we don't flag a coach who calls a +0.40
# position "roughly equal" — that's a judgment call, not an error.
#
# Halved 2026-08-25 (was 50) with the rest of the cp thresholds: Blunder now normalizes
# its output (NORMALIZE_TO_PAWN = 200), so every score we read is half what it was. An
# algebraic conversion to preserve behaviour, not a re-judgement of the boundary.
EQUAL_THRESHOLD_CP = 25

# Multiplicative penalty applied per hard factual error (hallucination,
# illegal move, backwards eval direction). 0.3 < the 0.8 pass threshold,
# so a single error always fails and each additional one compounds.
_HARD_ERROR_PENALTY = 0.3

PASS_THRESHOLD = 0.8

# Coverage is measured over points that name a concrete thing the
# response can *reference*. eval_direction has its own check; phase
# drives appropriateness, not reference, so neither counts toward
# coverage totals.
_REFERENCEABLE_KINDS = frozenset({"hanging_piece", "tactic", "free"})


# --------------------------------------------------------------- hallucination


def check_piece_hallucinations(fen: str, response: str) -> list[str]:
    """Flag "piece on square" claims that don't match the board.

    Delegates to the single rules-tier checker (``verify.check_text_fidelity``)
    and surfaces its placement violations, so the probe, the scored harness,
    and the runtime coach all share one implementation (grounded-move-advice
    Req 5.4). Influence verbs and "weak/strong square X" assessments are
    skipped by the shared checker.
    """
    return [f"{v.text} — {v.detail}" for v in check_text_fidelity(response, fen) if v.kind == "placement"]


# --------------------------------------------------------------- move legality


def check_move_validity(fen: str, response: str) -> list[str]:
    """Flag clearly-illegal moves mentioned in the response.

    Delegates to the shared checker (Req 5.4). A bare pawn token like "e5" is
    a square reference, not a move, so the shared checker only flags tokens
    that are unambiguously move notation (piece letter, capture, castling, or
    a coordinate "from-to").
    """
    return [f"{v.text} — {v.detail}" for v in check_text_fidelity(response, fen) if v.kind == "illegal_move"]


# --------------------------------------------------------------- eval direction


def _claimed_direction(response: str) -> str | None:
    """Best-effort extraction of the who's-better claim from coaching
    text. Returns 'white_better' / 'black_better' / 'equal' / None.

    Ambiguous text that claims both sides better (e.g. "white is better
    on the kingside, black on the queenside") returns None — we won't
    guess.
    """
    text = response.lower()

    def _side_better(side: str) -> bool:
        # "<side> is better/winning/ahead", "advantage <side>",
        # "better/winning for <side>", "favors <side>".
        patterns = [
            rf"{side}\s+(?:is|stands|seems|looks)?\s*"
            rf"(?:clearly\s+|slightly\s+|much\s+)?(?:better|winning|ahead|on top)",
            rf"{side}\s+has\s+(?:a\s+|the\s+|an?\s+)?"
            rf"(?:clear\s+|slight\s+|small\s+|big\s+)?(?:advantage|edge|initiative)",
            rf"(?:advantage|edge|initiative)\s+(?:for|to)\s+{side}",
            rf"(?:better|winning)\s+for\s+{side}",
            rf"favou?rs\s+{side}",
        ]
        return any(re.search(p, text) for p in patterns)

    white = _side_better("white")
    black = _side_better("black")
    if white and black:
        return None
    if white:
        return "white_better"
    if black:
        return "black_better"

    equal_signals = (
        "roughly equal",
        "approximately equal",
        "about equal",
        "equal",
        "balanced",
        "level position",
        "is level",
        "even position",
        "roughly balanced",
        "symmetrical",
    )
    if any(s in text for s in equal_signals):
        return "equal"
    return None


def _engine_direction(eval_cp: int) -> str:
    if eval_cp > EQUAL_THRESHOLD_CP:
        return "white_better"
    if eval_cp < -EQUAL_THRESHOLD_CP:
        return "black_better"
    return "equal"


def check_eval_direction(response: str, report: PositionReport) -> bool | None:
    """Compare the response's who's-better claim against the engine.

    Returns:
    - True  — the response states a direction that matches the engine.
    - False — the response states the *opposite winner* (got it
      backwards). This is the only contradiction we flag; near-equal
      disagreements are judgment calls left to the Layer 2 judge.
    - None  — no clear claim, or a non-backwards mismatch.
    """
    claimed = _claimed_direction(response)
    if claimed is None:
        return None
    engine = _engine_direction(report.eval_cp)
    if claimed == engine:
        return True
    # Only a flipped winner is a hard contradiction.
    if {claimed, engine} == {"white_better", "black_better"}:
        return False
    return None


# --------------------------------------------------------------- coverage


def _references_point(response: str, point: GroundTruthPoint) -> bool:
    text = response.lower()
    if point.kind == "hanging_piece":
        return re.search(rf"\b{re.escape(point.value.lower())}\b", text) is not None
    if point.kind == "eval_direction":
        return _claimed_direction(response) == point.value
    # tactic + free: substring reference.
    return point.value.lower() in text


def check_coverage(response: str, position: BenchmarkPosition) -> tuple[list[str], int]:
    """Return (hits, total) over the position's *required, referenceable*
    ground-truth points.

    ``total`` counts required points whose kind is referenceable
    (hanging_piece / tactic / free) plus required eval_direction points.
    Phase points don't count — they drive appropriateness, not
    reference. ``hits`` is the descriptors actually referenced.
    """
    hits: list[str] = []
    total = 0
    for p in position.required_points():
        if p.kind == "phase":
            continue
        if p.kind not in _REFERENCEABLE_KINDS and p.kind != "eval_direction":
            continue
        total += 1
        if _references_point(response, p):
            hits.append(f"{p.kind}:{p.value}")
    return hits, total


# --------------------------------------------------------------- aggregate


@dataclass
class ObjectiveResult:
    """Layer 1 findings for one coaching response."""

    hallucinations: list[str]
    illegal_moves: list[str]
    eval_direction_ok: bool | None
    coverage_hits: list[str]
    coverage_total: int
    factual_score: float
    # Full menu-aware fidelity breakdown by violation kind (placement,
    # development, empty_source, illegal_move, unsound_move, off_menu,
    # piece_type, pawn_structure, geometry) — a diagnostic metric recorded for
    # the A/B; it does NOT feed factual_score (which stays comparable across
    # runs). ``unsound_move`` requires the engine move menu, so it is only
    # populated here, not by the standalone helpers.
    fidelity_counts: dict[str, int] = field(default_factory=dict)

    @property
    def coverage_fraction(self) -> float:
        """Fraction of required key facts mentioned in the response (1.0 when none are required)."""
        if self.coverage_total == 0:
            return 1.0
        return len(self.coverage_hits) / self.coverage_total

    @property
    def passed(self) -> bool:
        """True if the factual score meets the pass threshold."""
        return self.factual_score >= PASS_THRESHOLD


def evaluate_objective(
    response: str,
    report: PositionReport,
    position: BenchmarkPosition,
) -> ObjectiveResult:
    """Run all Layer 1 checks and compute the factual score.

    Score model (multiplicative, so a hard error strictly lowers the
    score relative to not having it):

        coverage_fraction * (0.3 ** num_hard_errors)

    where a hard error is a hallucination, an illegal move, or a
    backwards eval-direction claim. With no errors the score is the
    coverage fraction (1.0 when there's nothing to cover). A single
    hard error caps it at <= 0.3, below the 0.8 pass threshold.
    """
    # One menu-aware pass over the response yields every fidelity violation;
    # the scored buckets (placement -> hallucinations, illegal_move) are
    # identical with or without the menu, so factual_score is unchanged from
    # the standalone-helper version. The menu additionally surfaces
    # unsound_move for the diagnostic breakdown.
    violations = check_coaching_fidelity(response, report, build_move_menu(report))
    hallucinations = [f"{v.text} — {v.detail}" for v in violations if v.kind == "placement"]
    illegal_moves = [f"{v.text} — {v.detail}" for v in violations if v.kind == "illegal_move"]
    fidelity_counts = dict(Counter(v.kind for v in violations))
    direction_ok = check_eval_direction(response, report)
    hits, total = check_coverage(response, position)

    coverage_fraction = len(hits) / total if total else 1.0
    hard_errors = len(hallucinations) + len(illegal_moves)
    if direction_ok is False:
        hard_errors += 1
    score = coverage_fraction * (_HARD_ERROR_PENALTY**hard_errors)

    return ObjectiveResult(
        hallucinations=hallucinations,
        illegal_moves=illegal_moves,
        eval_direction_ok=direction_ok,
        coverage_hits=hits,
        coverage_total=total,
        factual_score=round(score, 4),
        fidelity_counts=fidelity_counts,
    )
