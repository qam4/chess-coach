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
from dataclasses import dataclass

import chess

from ..models import PositionReport
from .benchmark import BenchmarkPosition, GroundTruthPoint

# Coaching on a position within this many centipawns of zero is treated
# as "equal" for the direction check. Deliberately more lenient than
# the templates' 30cp so we don't flag a coach who calls a +0.40
# position "roughly equal" — that's a judgment call, not an error.
EQUAL_THRESHOLD_CP = 50

# Multiplicative penalty applied per hard factual error (hallucination,
# illegal move, backwards eval direction). 0.3 < the 0.8 pass threshold,
# so a single error always fails and each additional one compounds.
_HARD_ERROR_PENALTY = 0.3

PASS_THRESHOLD = 0.8

_PIECE_NAMES = {
    "pawn": chess.PAWN,
    "knight": chess.KNIGHT,
    "bishop": chess.BISHOP,
    "rook": chess.ROOK,
    "queen": chess.QUEEN,
    "king": chess.KING,
}

# Coverage is measured over points that name a concrete thing the
# response can *reference*. eval_direction has its own check; phase
# drives appropriateness, not reference, so neither counts toward
# coverage totals.
_REFERENCEABLE_KINDS = frozenset({"hanging_piece", "tactic", "free"})


# --------------------------------------------------------------- hallucination


def check_piece_hallucinations(fen: str, response: str) -> list[str]:
    """Flag "piece on square" claims that don't match the board.

    Only placement claims are checked. Skips:
    - influence verbs ("controlling/targeting/attacking/defending X")
    - square assessments ("weak square X", "strong square X")

    Moved here from scripts/probe_llm_chess.py (Task 2) so the scored
    harness and the probe share one implementation.
    """
    board = chess.Board(fen)
    issues: list[str] = []
    response_lower = response.lower()

    square_assessment_pattern = r"(?:weak|strong)\s+square\s+([a-h][1-8])"
    assessment_spans: set[tuple[int, int]] = set()
    for m in re.finditer(square_assessment_pattern, response_lower):
        assessment_spans.add((m.start(), m.end()))

    influence_verbs = ("controlling", "targeting", "attacking", "defending")

    for piece_name, piece_type in _PIECE_NAMES.items():
        pattern = rf"{piece_name}\s+on\s+([a-h][1-8])"
        for match in re.finditer(pattern, response_lower):
            square_name = match.group(1)

            overlaps_assessment = any(
                a_start <= match.start() <= a_end or a_start <= match.end() <= a_end
                for a_start, a_end in assessment_spans
            )
            if overlaps_assessment:
                continue

            context_start = max(0, match.start() - 30)
            preceding = response_lower[context_start : match.start()]
            if any(verb in preceding for verb in influence_verbs):
                continue

            try:
                sq = chess.parse_square(square_name)
            except ValueError:
                continue
            actual = board.piece_at(sq)
            if actual is None:
                issues.append(f"claims {piece_name} on {square_name} — square is empty")
            elif actual.piece_type != piece_type:
                actual_name = chess.piece_name(actual.piece_type)
                issues.append(f"claims {piece_name} on {square_name} — actually a {actual_name}")

    return issues


# --------------------------------------------------------------- move legality


def check_move_validity(fen: str, response: str) -> list[str]:
    """Flag clearly-illegal moves mentioned in the response.

    Tension: a bare pawn token like "e5" is indistinguishable from a
    *square reference* ("the e5 square is weak"), so flagging it as an
    illegal move would produce false positives that erode trust. We
    therefore only flag tokens that are unambiguously move notation —
    a piece letter (K/Q/R/B/N), a capture (x), or castling (O-O) — when
    python-chess reports them illegal. Bare pawn-square tokens are left
    alone (the hallucination check and the judge cover the rest).

    Moved here from scripts/probe_llm_chess.py and tightened (Task 2).
    """
    board = chess.Board(fen)
    issues: list[str] = []

    san_pattern = r"\b([KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?|O-O(?:-O)?)\b"
    for match in re.finditer(san_pattern, response):
        move_str = match.group(1)
        clearly_a_move = move_str[0] in "KQRBNO" or "x" in move_str
        try:
            move = board.parse_san(move_str)
        except chess.IllegalMoveError:
            # Parsed as well-formed notation but not legal here. Only
            # flag if it's unmistakably a move (not a bare square ref).
            if clearly_a_move:
                issues.append(f"{move_str} is not legal in this position")
        except (chess.InvalidMoveError, chess.AmbiguousMoveError, ValueError):
            # Unparseable / ambiguous — could be prose or a future move.
            pass
        else:
            if move not in board.legal_moves:
                issues.append(f"{move_str} is not legal in this position")

    return issues


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

    @property
    def coverage_fraction(self) -> float:
        if self.coverage_total == 0:
            return 1.0
        return len(self.coverage_hits) / self.coverage_total

    @property
    def passed(self) -> bool:
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
    fen = report.fen
    hallucinations = check_piece_hallucinations(fen, response)
    illegal_moves = check_move_validity(fen, response)
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
    )
