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
        }


@dataclass(frozen=True)
class ReviewStats:
    """Aggregate, objective facts about a coaching transcript.

    Deterministic (no judge) so they anchor the frontier review in numbers:
    phase coverage, move-quality mix, fidelity-violation totals, latency.
    """

    n_turns: int
    phase_counts: dict[str, int]
    classification_counts: dict[str, int]
    fidelity_totals: dict[str, int]
    empty_feedback: int
    latency_mean_s: float
    latency_p90_s: float
    latency_max_s: float

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
        }


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Nearest-rank percentile of an already-sorted list (empty -> 0.0)."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = max(0, min(len(sorted_vals) - 1, round(pct / 100 * (len(sorted_vals) - 1))))
    return sorted_vals[rank]


def aggregate_review(turns: list[ReviewTurn]) -> ReviewStats:
    """Roll a list of :class:`ReviewTurn` into deterministic :class:`ReviewStats`."""
    n = len(turns)
    latencies = sorted(t.latency_s for t in turns)
    fidelity: Counter[str] = Counter()
    for t in turns:
        fidelity.update(t.fidelity_kinds)
    return ReviewStats(
        n_turns=n,
        phase_counts=dict(Counter(t.phase for t in turns)),
        classification_counts=dict(Counter(t.classification for t in turns)),
        fidelity_totals=dict(fidelity),
        empty_feedback=sum(1 for t in turns if not t.coach_feedback.strip()),
        latency_mean_s=(sum(latencies) / n) if n else 0.0,
        latency_p90_s=_percentile(latencies, 90),
        latency_max_s=(latencies[-1] if latencies else 0.0),
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
    return (
        f"Coached moves: {stats.n_turns}\n"
        f"Phase coverage: {phases or 'none'}\n"
        f"Move quality (engine): {cls or 'none'}\n"
        f"Deterministic fidelity violations: {fid}\n"
        f"Empty feedback turns: {stats.empty_feedback}\n"
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
