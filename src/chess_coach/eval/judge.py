"""Layer 2 — frontier LLM-as-judge.

Scores coaching quality against a fixed rubric, *grounded in the
engine report*. The judge is handed the engine's analysis as ground
truth and told not to use its own chess vision for factual claims —
that's what keeps even a strong model honest about a board it might
otherwise misread. See `.kiro/specs/coaching-eval/design.md` (Layer 2).

The judge reaches the model through the existing `LLMProvider`
abstraction, so the endpoint is pluggable: a direct frontier API, the
FITT gateway's `fitt-smart` alias, or any OpenAI-compatible shim.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

import chess
import yaml

from ..models import ComparisonReport, PositionReport
from ..pedagogy.inject import format_judge_guidance_block
from ..pedagogy.resource import GuidanceEntry
from .benchmark import BenchmarkPosition


class RubricError(Exception):
    """Malformed rubric file."""


class VerdictParseError(Exception):
    """The judge's reply could not be parsed into a complete verdict."""


# --------------------------------------------------------------- rubric


@dataclass(frozen=True)
class Criterion:
    """A single rubric criterion: its key, description, and scoring weight."""

    key: str
    description: str
    weight: float


@dataclass(frozen=True)
class JudgeRubric:
    """A judging rubric: a versioned set of weighted criteria with optional score gates."""

    version: str
    criteria: tuple[Criterion, ...]
    # Optional multiplicative score gates: (criterion_key, on_fail_multiplier).
    # When the named criterion fails, the weighted base score is multiplied
    # by the factor. Empty for rubrics with no `scoring.gates` block (v1).
    gates: tuple[tuple[str, float], ...] = ()

    def keys(self) -> list[str]:
        """Return the criterion keys in rubric order."""
        return [c.key for c in self.criteria]

    def total_weight(self) -> float:
        """Return the sum of all criterion weights."""
        return sum(c.weight for c in self.criteria)

    def weight_of(self, key: str) -> float:
        """Return the weight of the criterion with the given key, or 0.0 if not found."""
        for c in self.criteria:
            if c.key == key:
                return c.weight
        return 0.0


def load_rubric(path: str | Path) -> JudgeRubric:
    """Load and validate a judging rubric from a YAML file, returning a JudgeRubric."""
    path = Path(path)
    if not path.exists():
        raise RubricError(f"rubric file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise RubricError(f"{path}: invalid YAML: {e}") from e
    if not isinstance(data, dict):
        raise RubricError(f"{path}: top level must be a mapping")
    version = str(data.get("version") or "")
    if not version:
        raise RubricError(f"{path}: missing 'version'")
    raw = data.get("criteria")
    if not isinstance(raw, list) or not raw:
        raise RubricError(f"{path}: 'criteria' must be a non-empty list")
    criteria: list[Criterion] = []
    seen: set[str] = set()
    for i, c in enumerate(raw):
        if not isinstance(c, dict) or "key" not in c or "description" not in c:
            raise RubricError(f"{path}: criteria[{i}] needs 'key' and 'description'")
        key = str(c["key"])
        if key in seen:
            raise RubricError(f"{path}: duplicate criterion key {key!r}")
        seen.add(key)
        criteria.append(
            Criterion(
                key=key,
                description=" ".join(str(c["description"]).split()),
                weight=float(c.get("weight", 1.0)),
            )
        )
    gates = _parse_gates(data.get("scoring"), {c.key for c in criteria}, path)
    return JudgeRubric(version=version, criteria=tuple(criteria), gates=gates)


def _parse_gates(
    scoring: object,
    valid_keys: set[str],
    path: Path,
) -> tuple[tuple[str, float], ...]:
    """Parse the optional ``scoring.gates`` block. Absent block -> no
    gates (v1 behaviour). Validates each gate names a real criterion."""
    if scoring is None:
        return ()
    if not isinstance(scoring, dict):
        raise RubricError(f"{path}: 'scoring' must be a mapping")
    raw = scoring.get("gates", [])
    if not isinstance(raw, list):
        raise RubricError(f"{path}: 'scoring.gates' must be a list")
    gates: list[tuple[str, float]] = []
    for i, g in enumerate(raw):
        if not isinstance(g, dict) or "criterion" not in g or "on_fail" not in g:
            raise RubricError(f"{path}: scoring.gates[{i}] needs 'criterion' and 'on_fail'")
        crit = str(g["criterion"])
        if crit not in valid_keys:
            raise RubricError(f"{path}: scoring.gates[{i}] references unknown criterion {crit!r}")
        gates.append((crit, float(g["on_fail"])))
    return tuple(gates)


def default_rubric_path() -> Path:
    """Return the path to the bundled default rubric (``data/eval/rubric.v1.yaml``)."""
    return Path(__file__).resolve().parents[3] / "data" / "eval" / "rubric.v1.yaml"


# --------------------------------------------------------------- verdict


@dataclass
class JudgeVerdict:
    """A judge's evaluation of one coaching response: per-criterion pass/fail, score, and metadata."""

    criteria: dict[str, tuple[bool, str]]  # key -> (pass, reason)
    contradictions: list[str]
    quality_score: float
    judge_model: str
    rubric_version: str
    # Criteria that were intentionally NOT graded for this position (Req
    # 4.6) — e.g. ``teaches_principle`` when no curated guidance exists.
    # A not-graded criterion is a distinct state from pass/fail: it is
    # absent from ``criteria`` and excluded from the weighted score so it
    # never silently counts as a free pass or a fail.
    not_graded: tuple[str, ...] = ()

    def passed_keys(self) -> list[str]:
        """Return the keys of criteria that passed."""
        return [k for k, (ok, _) in self.criteria.items() if ok]

    def is_graded(self, key: str) -> bool:
        """True when ``key`` was graded (i.e. not in ``not_graded``)."""
        return key not in self.not_graded


# --------------------------------------------------------------- prompt


def _fmt_eval(cp: int) -> str:
    side = "White" if cp > 0 else "Black" if cp < 0 else "neither side"
    return f"{cp}cp ({'+' if cp > 0 else ''}{cp / 100:.2f} pawns, favouring {side})"


def format_engine_report(report: PositionReport) -> str:
    """Compact, labelled rendering of the engine report. Empty
    sections are omitted to keep the judge prompt focused."""
    sections: list[str] = []
    eb = report.eval_breakdown
    sections.append(
        "--- Evaluation (ground truth) ---\n"
        f"Overall: {_fmt_eval(report.eval_cp)}\n"
        f"Material {eb.material}cp, mobility {eb.mobility}cp, "
        f"king safety {eb.king_safety}cp, pawn structure {eb.pawn_structure}cp"
    )

    hanging = [
        f"{side.title()}'s {hp.piece} on {hp.square}"
        for side in ("white", "black")
        for hp in report.hanging_pieces.get(side, [])
    ]
    if hanging:
        sections.append("--- Hanging pieces ---\n" + "\n".join(hanging))

    threats = [f"{side.title()}: {t.description}" for side in ("white", "black") for t in report.threats.get(side, [])]
    if threats:
        sections.append("--- Threats ---\n" + "\n".join(threats))

    if report.tactics:
        sections.append("--- Tactics ---\n" + "\n".join(f"{t.type}: {t.description}" for t in report.tactics))

    if report.top_lines:
        lines = []
        for i, ln in enumerate(report.top_lines[:3], 1):
            moves = " ".join(ln.moves[:5])
            lines.append(f"Line {i} ({ln.eval_cp}cp): {moves}")
        sections.append("--- Top engine lines ---\n" + "\n".join(lines))

    return "\n\n".join(sections)


_JSON_CONTRACT = (
    "Respond with ONLY a JSON object of this exact shape:\n"
    "{\n"
    '  "criteria": {\n'
    '    "<key>": {"pass": true|false, "reason": "<one clause>"},\n'
    "    ...one entry per rubric key...\n"
    "  },\n"
    '  "contradictions": ["<any response claim that contradicts the engine data>"],\n'
    '  "notes": "<optional overall note>"\n'
    "}"
)


_TEACHES_PRINCIPLE = "teaches_principle"


def _ungraded_criteria(
    rubric: JudgeRubric,
    guidance: list[GuidanceEntry] | None,
) -> tuple[str, ...]:
    """Criteria omitted from grading for this position (Req 4.6).

    ``teaches_principle`` is graded only against curated guidance (Req
    4.2, 4.3). When the rubric HAS that criterion but no guidance is
    available for the position, the criterion is dropped from the prompt
    and recorded as not-graded — never silently passed or failed. A rubric
    without ``teaches_principle`` (e.g. v1) is unaffected, and a non-empty
    guidance set grades the criterion normally.
    """
    if _TEACHES_PRINCIPLE in rubric.keys() and not guidance:
        return (_TEACHES_PRINCIPLE,)
    return ()


def build_judge_prompt(
    response: str,
    report: PositionReport,
    position: BenchmarkPosition,
    rubric: JudgeRubric,
    guidance: list[GuidanceEntry] | None = None,
) -> str:
    """Build the grounded judge prompt: engine ground truth + the
    coaching text + the rubric + a strict JSON output contract.

    When ``guidance`` is non-empty AND the rubric has ``teaches_principle``,
    the selected guidance entries are rendered as the **sole standard** for
    that criterion, with an instruction telling the judge to grade it only
    against the provided guidance and not its own chess knowledge (Req 4.2,
    4.3). The guidance handed here is the identical list the coach prompt
    received for this position (single-source parity, Req 4.5).

    When ``guidance`` is empty/``None`` and the rubric has
    ``teaches_principle``, that criterion is OMITTED from the rubric shown
    to the judge; the resulting verdict records it as *not graded* rather
    than passing or failing it (Req 4.6). A rubric without
    ``teaches_principle`` (v1) is built exactly as before regardless of
    ``guidance``.
    """
    board = chess.Board(report.fen)
    side = "White" if board.turn == chess.WHITE else "Black"

    has_teaches_principle = _TEACHES_PRINCIPLE in rubric.keys()
    not_graded = _ungraded_criteria(rubric, guidance)
    graded = [c for c in rubric.criteria if c.key not in not_graded]
    rubric_lines = "\n".join(f"- {c.key}: {c.description}" for c in graded)

    # Sole-standard guidance block for teaches_principle (Req 4.2). Only
    # injected when the rubric actually has that criterion AND guidance is
    # available — a rubric without teaches_principle (v1) is built exactly
    # as before, ignoring any guidance.
    guidance_block = ""
    if has_teaches_principle and guidance:
        guidance_block = format_judge_guidance_block(guidance)
    guidance_section = f"\n\n{guidance_block}" if guidance_block else ""

    return (
        "You are evaluating a chess coaching response for quality.\n"
        "You are given the chess engine's authoritative analysis of the "
        "position. TREAT THE ENGINE ANALYSIS AS GROUND TRUTH. Do NOT use "
        "your own chess calculation to judge factual claims — rely only "
        "on the engine data provided. Your job is to score the coaching "
        "text against the rubric and to flag any claim in it that "
        "contradicts the engine data.\n\n"
        f"Position FEN: {report.fen}\n"
        f"Side to move: {side}\n"
        f"Coaching target level: {position.level}\n\n"
        f"{format_engine_report(report)}\n\n"
        "--- Coaching response to grade ---\n"
        f"{response}\n\n"
        "--- Rubric (score each criterion pass/fail) ---\n"
        f"{rubric_lines}"
        f"{guidance_section}\n\n"
        f"{_JSON_CONTRACT}"
    )


# --------------------------------------------------------------- parsing


def _extract_json_object(text: str) -> str:
    """Pull the outermost {...} object out of a reply that may carry
    markdown fences or trailing prose (a common frontier quirk)."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise VerdictParseError("no JSON object found in judge reply")
    return text[start : end + 1]


def _quality_score(
    criteria: dict[str, tuple[bool, str]],
    rubric: JudgeRubric,
    not_graded: tuple[str, ...] = (),
) -> float:
    # A not-graded criterion (Req 4.6) is excluded from BOTH the numerator
    # and the denominator: it must not count as a free pass or a fail. Its
    # weight is dropped from the total so the remaining graded criteria are
    # scored on their own.
    ungraded = set(not_graded)
    total = sum(c.weight for c in rubric.criteria if c.key not in ungraded)
    if total <= 0:
        return 0.0
    earned = sum(rubric.weight_of(k) for k, (ok, _) in criteria.items() if ok)
    score = earned / total
    # Apply multiplicative gates: a failed gated criterion (e.g. grounded,
    # key_idea) curves the whole score down so fluent filler can't offset
    # a contradiction or a missed point. Gates compound. A not-graded
    # criterion never trips a gate.
    for crit_key, multiplier in rubric.gates:
        if crit_key in ungraded:
            continue
        entry = criteria.get(crit_key)
        if entry is not None and not entry[0]:
            score *= multiplier
    return round(score, 4)


def parse_verdict(
    text: str,
    rubric: JudgeRubric,
    *,
    judge_model: str,
    not_graded: tuple[str, ...] = (),
) -> JudgeVerdict:
    """Parse the judge's reply into a complete verdict, or raise.

    Enforces two invariants:
    * Every *graded* rubric criterion must be present (else
      VerdictParseError). Criteria in ``not_graded`` (Req 4.6) are neither
      required in the reply nor scored — they are recorded as not-graded.
    * ``grounded`` passes iff there are no contradictions — we derive
      it from the contradictions list rather than trusting the model's
      self-reported grounded flag (Property 5).
    """
    ungraded = set(not_graded)
    raw = _extract_json_object(text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise VerdictParseError(f"judge reply is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise VerdictParseError("judge reply JSON is not an object")

    raw_criteria = data.get("criteria")
    if not isinstance(raw_criteria, dict):
        raise VerdictParseError("judge reply missing 'criteria' object")

    contradictions = data.get("contradictions") or []
    if not isinstance(contradictions, list):
        raise VerdictParseError("'contradictions' must be a list")
    contradictions = [str(c) for c in contradictions]

    criteria: dict[str, tuple[bool, str]] = {}
    for key in rubric.keys():
        if key in ungraded:
            continue
        entry = raw_criteria.get(key)
        if not isinstance(entry, dict) or "pass" not in entry:
            raise VerdictParseError(f"judge reply missing criterion {key!r}")
        passed = bool(entry["pass"])
        reason = str(entry.get("reason", ""))
        criteria[key] = (passed, reason)

    # Property 5: grounded is derived from contradictions, not trusted.
    if "grounded" in criteria:
        has_contradiction = len(contradictions) > 0
        prev_reason = criteria["grounded"][1]
        criteria["grounded"] = (
            not has_contradiction,
            prev_reason or ("contradictions found" if has_contradiction else "no contradictions"),
        )

    return JudgeVerdict(
        criteria=criteria,
        contradictions=contradictions,
        quality_score=_quality_score(criteria, rubric, not_graded),
        judge_model=judge_model,
        rubric_version=rubric.version,
        not_graded=tuple(k for k in rubric.keys() if k in ungraded),
    )


# --------------------------------------------------------------- judging


def judge_response(
    provider: object,
    response: str,
    report: PositionReport,
    position: BenchmarkPosition,
    rubric: JudgeRubric,
    *,
    guidance: list[GuidanceEntry] | None = None,
    max_tokens: int = 900,
) -> JudgeVerdict:
    """Run the judge for one coaching response. Temperature 0 for
    reproducibility; one retry on a parse failure, then raise.

    ``guidance`` is the selector-chosen guidance for this position — the
    identical list the coach prompt received (Req 4.5). It grounds the
    ``teaches_principle`` criterion (Req 4.2); when it is empty and the
    rubric has that criterion, the criterion is omitted from the prompt and
    recorded as not-graded in the verdict (Req 4.6).
    """
    prompt = build_judge_prompt(response, report, position, rubric, guidance)
    not_graded = _ungraded_criteria(rubric, guidance)
    model = getattr(provider, "model", "unknown")
    last_err: Exception | None = None
    for _attempt in range(2):
        raw = provider.generate(prompt, max_tokens=max_tokens, temperature=0.0)  # type: ignore[attr-defined]
        try:
            return parse_verdict(raw, rubric, judge_model=model, not_graded=not_graded)
        except VerdictParseError as e:
            last_err = e
    raise VerdictParseError(f"judge verdict unparseable after retry: {last_err}")


# --------------------------------------------------------------- pairwise


@dataclass
class PairwiseResult:
    """A single pairwise judging outcome: which of two models won on a position, with audit fields."""

    position_id: str
    model_a: str
    model_b: str
    winner: str  # "model_a" | "model_b" | "tie"
    first_shown: str  # which model occupied slot 1 (randomized) — auditable
    reason: str


def build_pairwise_prompt(
    response_1: str,
    response_2: str,
    report: PositionReport,
    position: BenchmarkPosition,
) -> str:
    """Pairwise judge prompt: two coaching responses, same grounding,
    pick the better one. Slot order is randomized by the caller."""
    board = chess.Board(report.fen)
    side = "White" if board.turn == chess.WHITE else "Black"
    return (
        "You are comparing two chess coaching responses for the same "
        "position. TREAT THE ENGINE ANALYSIS AS GROUND TRUTH; do not use "
        "your own chess calculation. Pick the response that is the better "
        "coaching: grounded in the engine data (no contradictions), finds "
        "the key idea, explains why, is actionable, and fits the target "
        "level.\n\n"
        f"Position FEN: {report.fen}\nSide to move: {side}\n"
        f"Target level: {position.level}\n\n"
        f"{format_engine_report(report)}\n\n"
        f"--- Response 1 ---\n{response_1}\n\n"
        f"--- Response 2 ---\n{response_2}\n\n"
        'Respond with ONLY JSON: {"winner": "1"|"2"|"tie", "reason": "<one clause>"}'
    )


def parse_pairwise(text: str) -> tuple[str, str]:
    """Return (winner, reason) where winner is '1', '2', or 'tie'."""
    raw = _extract_json_object(text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise VerdictParseError(f"pairwise reply not valid JSON: {e}") from e
    winner = str(data.get("winner", "")).strip().lower()
    if winner not in ("1", "2", "tie"):
        raise VerdictParseError(f"pairwise winner must be 1/2/tie, got {winner!r}")
    return winner, str(data.get("reason", ""))


def pairwise_compare(
    provider: object,
    model_a: str,
    response_a: str,
    model_b: str,
    response_b: str,
    report: PositionReport,
    position: BenchmarkPosition,
    *,
    rng: random.Random,
    max_tokens: int = 400,
) -> PairwiseResult:
    """Compare two models' responses, randomizing which is shown first
    to cancel position bias, and recording the assignment (Property 6)."""
    a_first = rng.random() < 0.5
    if a_first:
        resp1, resp2, first_model = response_a, response_b, model_a
    else:
        resp1, resp2, first_model = response_b, response_a, model_b

    prompt = build_pairwise_prompt(resp1, resp2, report, position)
    raw = provider.generate(prompt, max_tokens=max_tokens, temperature=0.0)  # type: ignore[attr-defined]
    winner_slot, reason = parse_pairwise(raw)

    if winner_slot == "tie":
        winner = "tie"
    else:
        # Map the chosen slot back to the model that occupied it.
        slot1_model = model_a if a_first else model_b
        slot2_model = model_b if a_first else model_a
        winner = slot1_model if winner_slot == "1" else slot2_model

    return PairwiseResult(
        position_id=position.id,
        model_a=model_a,
        model_b=model_b,
        winner=winner,
        first_shown=first_model,
        reason=reason,
    )


# --------------------------------------------------- pairwise: move feedback


def build_move_feedback_pairwise_prompt(
    response_1: str,
    response_2: str,
    report: ComparisonReport,
    level: str,
) -> str:
    """Pairwise prompt for two coaching responses that give FEEDBACK on the
    move a student just played (the step-1 coaching moment, not position
    analysis). The engine comparison is the ground truth; the judge picks the
    better *teaching feedback*. Slot order is randomized by the caller."""
    return (
        "You are comparing two chess coaching responses that give FEEDBACK on "
        "a move a student just played. TREAT THE ENGINE DATA BELOW AS GROUND "
        "TRUTH; do not use your own chess calculation. Pick the response that "
        "is the better teaching feedback: it correctly conveys whether the move "
        "was good or a mistake, names the key idea or principle at stake, "
        "explains why in human terms, gives an actionable correction (the "
        "better move/plan), and fits the target level. Penalize feedback that "
        "misjudges the move or just narrates the position.\n\n"
        f"Position FEN: {report.fen}\n"
        f"Student's move: {report.user_move}\n"
        f"Engine best move: {report.best_move}\n"
        f"Eval drop from the student's move: {report.eval_drop_cp} cp\n"
        f"Engine classification: {report.classification}\n"
        f"What the best move achieves: {report.best_move_idea}\n"
        f"Target level: {level}\n\n"
        f"--- Response 1 ---\n{response_1}\n\n"
        f"--- Response 2 ---\n{response_2}\n\n"
        'Respond with ONLY JSON: {"winner": "1"|"2"|"tie", "reason": "<one clause>"}'
    )


def pairwise_compare_move(
    provider: object,
    label_a: str,
    response_a: str,
    label_b: str,
    response_b: str,
    report: ComparisonReport,
    level: str,
    *,
    rng: random.Random,
    max_tokens: int = 400,
) -> PairwiseResult:
    """Move-feedback counterpart of :func:`pairwise_compare`: compare two
    feedback responses for the same played move, randomizing slot order to
    cancel position bias and recording the assignment (Property 6)."""
    a_first = rng.random() < 0.5
    if a_first:
        resp1, resp2, first_model = response_a, response_b, label_a
    else:
        resp1, resp2, first_model = response_b, response_a, label_b

    prompt = build_move_feedback_pairwise_prompt(resp1, resp2, report, level)
    raw = provider.generate(prompt, max_tokens=max_tokens, temperature=0.0)  # type: ignore[attr-defined]
    winner_slot, reason = parse_pairwise(raw)

    if winner_slot == "tie":
        winner = "tie"
    else:
        slot1_model = label_a if a_first else label_b
        slot2_model = label_b if a_first else label_a
        winner = slot1_model if winner_slot == "1" else slot2_model

    return PairwiseResult(
        position_id=report.fen,
        model_a=label_a,
        model_b=label_b,
        winner=winner,
        first_shown=first_model,
        reason=reason,
    )
