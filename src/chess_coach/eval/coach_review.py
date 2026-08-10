"""Coach report card — single-mode holistic review (pure core).

Unlike the pairwise A/B (which asks "is config A better than B?"), this asks
the honest product question: *is the coach the one the VISION describes* — a
bridge from a named principle to a concrete, sound action at the student's
level — and where does it fall short, including practical problems like
latency and verbosity?

This module is pure and I/O-free: a driver plays a game, coaches each student
move with the shipping config (timing each generation), and builds
:class:`ReviewTurn`s; here we aggregate them and compose the single review
prompt for a frontier reviewer. The reviewer call, the engine, and the LLM all
live in the driver so the assembly + stats stay unit-testable with fakes.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

# Phase tags (mirror pedagogy.features so the report speaks the same language).
PHASE_OPENING = "phase:opening"
PHASE_MIDDLEGAME = "phase:middlegame"
PHASE_ENDGAME = "phase:endgame"
_PHASE_LABEL = {PHASE_OPENING: "opening", PHASE_MIDDLEGAME: "middlegame", PHASE_ENDGAME: "endgame"}


@dataclass(frozen=True)
class ReviewTurn:
    """One coached student move with everything the reviewer needs to judge it."""

    ply: int
    phase: str  # one of the PHASE_* tags
    fen_before: str
    student_move_san: str
    best_move_san: str
    classification: str  # good | inaccuracy | mistake | blunder
    eval_drop_cp: int
    coach_feedback: str
    latency_s: float
    fidelity_kinds: dict[str, int] = field(default_factory=dict)
    # The exact prompt the local model received. Captured so an architecture
    # review can critique the real design, not guess at it from outputs alone.
    prompt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ply": self.ply,
            "phase": self.phase,
            "fen_before": self.fen_before,
            "student_move_san": self.student_move_san,
            "best_move_san": self.best_move_san,
            "classification": self.classification,
            "eval_drop_cp": self.eval_drop_cp,
            "coach_feedback": self.coach_feedback,
            "latency_s": round(self.latency_s, 2),
            "fidelity_kinds": dict(self.fidelity_kinds),
            "prompt": self.prompt,
        }


@dataclass(frozen=True)
class ReviewStats:
    """Aggregate, objective facts about a coaching transcript.

    Deterministic (no judge) so they anchor the frontier review in numbers:
    phase coverage, move-quality mix, fidelity-violation totals, latency, and
    the two *teaching* metrics below (specificity / principle-connection), which
    measure how concrete correct coaching is — the fidelity counts only measure
    what it gets wrong.
    """

    n_turns: int
    phase_counts: dict[str, int]
    classification_counts: dict[str, int]
    fidelity_totals: dict[str, int]
    empty_feedback: int
    latency_mean_s: float
    latency_p90_s: float
    latency_max_s: float
    # Fraction of turns naming a position-specific square/piece beyond the moved
    # piece itself — a proxy for "did it connect the principle to THIS position".
    specificity_rate: float = 0.0
    # Fraction of turns where a named principle keyword appears near a square
    # reference — i.e. the principle was instantiated, not just echoed.
    principle_connection_rate: float = 0.0
    # Fidelity violations broken down by phase (where to focus composer work).
    fidelity_by_phase: dict[str, dict[str, int]] = field(default_factory=dict)
    # Turns whose PROMPT still contained a raw UCI token (e.g. "f6g4"). SAN
    # conversion degrades to raw UCI silently when handed the wrong base
    # position; a log warning is not a guard, so this is surfaced in the stats
    # block of every run (and to the frontier reviewer). Should be 0.
    prompt_uci_leaks: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_turns": self.n_turns,
            "phase_counts": dict(self.phase_counts),
            "classification_counts": dict(self.classification_counts),
            "fidelity_totals": dict(self.fidelity_totals),
            "empty_feedback": self.empty_feedback,
            "latency_mean_s": round(self.latency_mean_s, 2),
            "latency_p90_s": round(self.latency_p90_s, 2),
            "latency_max_s": round(self.latency_max_s, 2),
            "specificity_rate": round(self.specificity_rate, 4),
            "principle_connection_rate": round(self.principle_connection_rate, 4),
            "fidelity_by_phase": {k: dict(v) for k, v in self.fidelity_by_phase.items()},
            "prompt_uci_leaks": self.prompt_uci_leaks,
        }


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Nearest-rank percentile of an already-sorted list (empty -> 0.0)."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = max(0, min(len(sorted_vals) - 1, round(pct / 100 * (len(sorted_vals) - 1))))
    return sorted_vals[rank]


# A square reference (a1..h8) anywhere in the text.
_SQUARE_RE = re.compile(r"\b[a-h][1-8]\b")
# A bare UCI move token ("f6g4"): should never appear in a rendered prompt, since
# every move is meant to be SAN. Detects silent SAN-conversion fallbacks.
_UCI_TOKEN_RE = re.compile(r"\b[a-h][1-8][a-h][1-8][qrbn]?\b")
# Principle keywords the coaching is expected to name (the pedagogy themes).
_PRINCIPLE_WORDS = (
    "development",
    "develop",
    "center",
    "central",
    "king safety",
    "castl",
    "pawn structure",
    "isolated",
    "passed pawn",
    "majority",
    "fork",
    "pin",
    "back rank",
    "material",
    "capture",
    "exchange",
    "trade",
    "activity",
    "outpost",
    "open file",
    "opposition",
    "threat",
)
# How close a principle word must be to a square reference to count as
# "instantiated" rather than merely stated (characters).
_CONNECTION_WINDOW = 120


def is_specific(turn: ReviewTurn) -> bool:
    """True if the response names a square/piece beyond the moved piece itself.

    Deterministic proxy for "did the coach connect the principle to THIS
    position". Squares mentioned by the student's own move or the engine best
    move are discounted, so merely echoing the move names does not count.
    """
    text = turn.coach_feedback
    if not text.strip():
        return False
    own = {s.lower() for s in _SQUARE_RE.findall(turn.student_move_san + " " + turn.best_move_san)}
    return any(sq.lower() not in own for sq in _SQUARE_RE.findall(text))


def connects_principle(turn: ReviewTurn) -> bool:
    """True if a named principle appears near a square reference.

    Measures whether the principle was *instantiated* on the board rather than
    stated abstractly ("develop your pieces") — the recycled-template failure.
    """
    text = turn.coach_feedback.lower()
    if not text.strip():
        return False
    squares = [m.start() for m in _SQUARE_RE.finditer(text)]
    if not squares:
        return False
    for word in _PRINCIPLE_WORDS:
        start = text.find(word)
        while start != -1:
            if any(abs(sq - start) <= _CONNECTION_WINDOW for sq in squares):
                return True
            start = text.find(word, start + 1)
    return False


def aggregate_review(turns: list[ReviewTurn]) -> ReviewStats:
    """Roll a list of :class:`ReviewTurn` into deterministic :class:`ReviewStats`."""
    n = len(turns)
    latencies = sorted(t.latency_s for t in turns)
    fidelity: Counter[str] = Counter()
    by_phase: dict[str, Counter[str]] = {}
    for t in turns:
        fidelity.update(t.fidelity_kinds)
        if t.fidelity_kinds:
            by_phase.setdefault(t.phase, Counter()).update(t.fidelity_kinds)
    return ReviewStats(
        n_turns=n,
        phase_counts=dict(Counter(t.phase for t in turns)),
        classification_counts=dict(Counter(t.classification for t in turns)),
        fidelity_totals=dict(fidelity),
        empty_feedback=sum(1 for t in turns if not t.coach_feedback.strip()),
        latency_mean_s=(sum(latencies) / n) if n else 0.0,
        latency_p90_s=_percentile(latencies, 90),
        latency_max_s=(latencies[-1] if latencies else 0.0),
        specificity_rate=(sum(1 for t in turns if is_specific(t)) / n) if n else 0.0,
        principle_connection_rate=(sum(1 for t in turns if connects_principle(t)) / n) if n else 0.0,
        fidelity_by_phase={k: dict(v) for k, v in by_phase.items()},
        prompt_uci_leaks=sum(1 for t in turns if t.prompt and _UCI_TOKEN_RE.search(t.prompt)),
    )


# The teaching standard the reviewer grades against — a compact restatement of
# the VISION "bridge" so the review is anchored to the product's own north star,
# not the reviewer's ad-hoc taste.
_BRIDGE_STANDARD = """\
The product is a TEACHER for a player trying to improve — not a position
analyst. Every piece of coaching should be a BRIDGE with two ends:
  1. WHAT TO FOCUS ON — a named principle/theme the student may know in the
     abstract (center control, development, king safety, a tactic, an endgame
     technique).
  2. A CONCRETE, SOUND WAY TO DO IT HERE — the specific move or plan in THIS
     position, at the student's level.
Pure analysis ("Nf3 is best, +0.4") is only end 2; a principle lecture is only
end 1. Good coaching connects both, grounded in the engine truth shown, at the
student's level, warm but concise.\
"""

_REVIEW_TASK = """\
You are a strong chess teacher AND a hard-nosed product reviewer. Judge HONESTLY
whether this local-LLM coach lives up to the standard above. Low scores are
welcome if deserved; do not flatter. Ground every point in specific plies from
the transcript.

Return:
1. SCORE: a single 0-10 rating of how well the coach realizes the bridge
   standard (0 = useless/misleading, 10 = exactly the envisioned teacher).
   One decimal allowed. State it as "SCORE: X/10".
2. STRENGTHS: the 2-4 things it does well (cite plies).
3. WEAKNESSES / PROBLEMS: the biggest issues (cite plies). Include PRACTICAL
   problems, not just content: latency (see the stats), verbosity, repetition
   across moves, filler/praise, missed teaching moments.
4. PHASE FIT: does the coaching suit each phase present (opening vs middlegame
   vs endgame)? Should the coach behave DIFFERENTLY by phase, and if so how?
   Note any phase that is under-covered in this transcript.
5. VERDICT: in 2-3 sentences, is this the coach the standard describes yet? What
   is the single highest-leverage change to get it closer?\
"""


def _fmt_stats(stats: ReviewStats) -> str:
    phases = ", ".join(f"{_PHASE_LABEL.get(k, k)}: {v}" for k, v in sorted(stats.phase_counts.items()))
    cls = ", ".join(f"{k}: {v}" for k, v in sorted(stats.classification_counts.items()))
    fid = ", ".join(f"{k}: {v}" for k, v in sorted(stats.fidelity_totals.items())) or "none"
    by_phase = (
        "; ".join(
            f"{_PHASE_LABEL.get(ph, ph)}: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items()))
            for ph, kinds in sorted(stats.fidelity_by_phase.items())
        )
        or "none"
    )
    return (
        f"Coached moves: {stats.n_turns}\n"
        f"Phase coverage: {phases or 'none'}\n"
        f"Move quality (engine): {cls or 'none'}\n"
        f"Deterministic fidelity violations: {fid}\n"
        f"Fidelity by phase: {by_phase}\n"
        f"Specificity rate (names a square/piece beyond the move itself): "
        f"{stats.specificity_rate:.0%}\n"
        f"Principle-connection rate (principle named near a square): "
        f"{stats.principle_connection_rate:.0%}\n"
        f"Empty feedback turns: {stats.empty_feedback}\n"
        f"Prompts still containing raw UCI (should be 0): {stats.prompt_uci_leaks}\n"
        f"Generation latency (s): mean {stats.latency_mean_s:.1f}, "
        f"p90 {stats.latency_p90_s:.1f}, max {stats.latency_max_s:.1f}"
    )


def _fmt_turn(t: ReviewTurn) -> str:
    played = t.student_move_san
    best = t.best_move_san
    same = " (this IS the engine's top move)" if played == best else f"; engine best: {best}"
    return (
        f"[ply {t.ply} | {_PHASE_LABEL.get(t.phase, t.phase)} | {t.latency_s:.1f}s] "
        f"student played {played}{same} — {t.classification} (eval drop {t.eval_drop_cp}cp)\n"
        f"  coach: {t.coach_feedback.strip() or '(empty)'}"
    )


def build_coach_review_prompt(turns: list[ReviewTurn], stats: ReviewStats) -> str:
    """Compose the single holistic-review prompt for a frontier reviewer.

    Bundles the teaching standard, the objective stats, and the full coached
    transcript, then asks for a 0-10 score + honest critique + phase-fit
    assessment. Pure string assembly so it is unit-testable.
    """
    transcript = "\n\n".join(_fmt_turn(t) for t in turns)
    return (
        "=== TEACHING STANDARD (the bar) ===\n"
        f"{_BRIDGE_STANDARD}\n\n"
        "=== OBJECTIVE STATS (deterministic, engine-derived) ===\n"
        f"{_fmt_stats(stats)}\n\n"
        "=== COACHING TRANSCRIPT (one real game, shipping config) ===\n"
        f"{transcript}\n\n"
        "=== YOUR REVIEW ===\n"
        f"{_REVIEW_TASK}"
    )


# ---------------------------------------------------------------------------
# Architecture review — critique the DESIGN, not just the prose.
# ---------------------------------------------------------------------------
#
# The report card above shows the reviewer only the coach's OUTPUT, so its advice
# is necessarily blind to the system: it cannot know an engine composes verified
# facts, that a deterministic fidelity checker exists, or that several of its
# past suggestions were already tried and regressed. This mode hands over the
# internals — the real rendered prompt, the architecture, the constraints, and
# the full lever history — and asks for an engineering critique instead.

_ARCH_TASK = """\
You are a senior engineer + chess-teaching expert doing a DESIGN review of this
system. You have its architecture, the exact prompt it sends, its outputs, and a
full log of changes already tried (with results). Your job is NOT to suggest
prose tweaks — several were already tried and regressed (see the lever log).

Answer these, concretely and in priority order:

1. FUNDAMENTAL SOUNDNESS: Is this architecture capable of producing the teacher
   the standard describes? If there is a fundamental flaw in the approach — not
   a bug, a *design* flaw — name it plainly. Say so if you think the current
   split of responsibilities cannot get there.
2. WHAT WE ARE GETTING WRONG: Given the prompt you can see and the outputs it
   produced, what is the actual mechanism behind the recurring failures
   (recycled templates, generic best-move explanations, invented piece
   identities)? Diagnose cause, not symptom.
3. HIGHEST-LEVERAGE DESIGN CHANGES: 2-4 changes to the SYSTEM (what is computed
   deterministically vs left to the LLM, what data the engine should supply,
   how work is decomposed, model choice/number of calls, caching, etc.).
   For each: what it fixes, roughly how to implement it, and the risk.
   Respect the constraints listed. Do NOT propose anything already marked
   REVERTED in the lever log unless you explain why it failed and how to do it
   differently.
4. WHAT TO STOP DOING: which current efforts are dead ends we should abandon.
5. MEASUREMENT: is our evaluation approach (this report card + deterministic
   fidelity counts) actually measuring the right thing? How would you measure
   teaching quality better?

Be blunt and specific. If our whole premise (a small local model as the
teaching voice over engine-composed facts) is the limiting factor, say so and
say what you would do instead within the constraints.\
"""


def build_architecture_review_prompt(
    *,
    architecture: str,
    constraints: str,
    lever_log: str,
    sample_prompt: str,
    sample_turns: list[ReviewTurn],
    stats: ReviewStats,
) -> str:
    """Compose a design-review request: internals + evidence + the ask.

    ``sample_prompt`` is the exact prompt one turn received (ground truth about
    what the model is told); ``sample_turns`` are representative outputs across
    severities; ``lever_log`` is the kept/reverted change history so the
    reviewer does not re-propose disproven ideas. Pure string assembly.
    """
    samples = "\n\n".join(_fmt_turn(t) for t in sample_turns)
    return (
        "=== THE STANDARD WE ARE BUILDING TO ===\n"
        f"{_BRIDGE_STANDARD}\n\n"
        "=== SYSTEM ARCHITECTURE (how coaching is produced) ===\n"
        f"{architecture}\n\n"
        "=== HARD CONSTRAINTS ===\n"
        f"{constraints}\n\n"
        "=== THE EXACT PROMPT SENT TO THE LOCAL MODEL (one real turn) ===\n"
        f"{sample_prompt}\n"
        "=== END OF PROMPT ===\n\n"
        "=== CHANGES ALREADY TRIED (kept / reverted, with measured results) ===\n"
        f"{lever_log}\n\n"
        "=== OBJECTIVE RESULTS OF THE CURRENT BUILD ===\n"
        f"{_fmt_stats(stats)}\n\n"
        "=== REPRESENTATIVE OUTPUTS ===\n"
        f"{samples}\n\n"
        "=== YOUR DESIGN REVIEW ===\n"
        f"{_ARCH_TASK}"
    )
