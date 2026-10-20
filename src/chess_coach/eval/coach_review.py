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

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def resolve_judge_agent(agent: str, expected_model: str, *, repo_root: Path | None = None) -> str:
    """The model a `--agent` run will actually use, or raise if it cannot be guaranteed.

    Judge provenance in this project was wrong for every run until 2026-09-21. The harness
    passed `kiro-cli chat --no-interactive --model claude-opus-5` and recorded "claude-opus-5"
    in the ledger, but `--model` is a NO-OP in kiro-cli 2.22.1 — it warns "failed to set
    model: Method not found" for any value, including a deliberately invalid one, and
    `--list-models` reports the default as `auto`. So every review was written by whatever
    `auto` selected, while the ledger named a specific model. The ledger's own warning that
    one judge was wrong on 5 of 5 per-ply claims and another right on 2 of 2 rests on that
    distinction.

    The agent route is used instead because it FAILS rather than falls back: an agent naming
    an unavailable model exits 1 with "Error: Internal error". This function closes the
    remaining hole — that the agent file and the recorded label could drift apart — by
    reading the file and refusing when they disagree.
    """
    root = repo_root or Path(__file__).resolve().parents[3]
    path = root / ".kiro" / "agents" / f"{agent}.json"
    if not path.exists():
        raise SystemExit(
            f"judge agent {agent!r} not found at {path}. The agent file is what pins the model; "
            "kiro-cli's --model flag is a no-op and cannot be relied on."
        )
    try:
        declared = (json.loads(path.read_text(encoding="utf-8")) or {}).get("model")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"judge agent {path} is not valid JSON: {exc}") from exc
    if not declared:
        raise SystemExit(f"judge agent {path} declares no 'model', so the run would use the 'auto' default.")
    if declared != expected_model:
        raise SystemExit(
            f"judge provenance mismatch: agent {agent!r} pins {declared!r} but the run would record "
            f"{expected_model!r}. Fix one of them rather than recording a model that did not answer."
        )
    return str(declared)


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
    # Every text the model wrote for this turn, in order, including drafts the gate blocked.
    # `coach_feedback` is what shipped, which after a fallback is none of these. Kept because the
    # gate is graded against a reading of every draft (B-021), and until this existed a blocked
    # draft was lost: 9 of 81 at v61. Not shown to the judge.
    drafts: list[str] = field(default_factory=list)

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
            "drafts": list(self.drafts),
        }


@dataclass(frozen=True)
class ReviewStats:
    """Aggregate, objective facts about a coaching transcript.

    Every number here answers a question that can be checked. There used to be
    one that did not — a ``principle_connection_rate`` that looked for a word
    from a hardcoded list near a square, meaning to detect a principle stated
    abstractly instead of applied to the position. It was deleted rather than
    kept with a warning: all 44 responses in the v19 transcript contained one of
    its keywords ("material", "capture", "exchange", "threat", "center" are hard
    to avoid in chess prose), so it reported 91% against a ceiling of 95% and
    passed happily on "Nf3 is a good move. In general, development matters a lot
    in the opening." Whether the coaching actually teaches is what the frontier
    review's written critique is for; a keyword list cannot stand in for it.

    What is left reads our own prompt or is a plain count: ``prompt_uci_leaks`` and
    ``prompt_magnitude_leaks`` check the prompt we rendered, and ``empty_feedback``,
    latency and the phase and move-quality mixes are counts. ``fidelity_totals`` and
    ``fidelity_by_phase`` are the live checker's verdict on what shipped, kept as data and not
    shown to the reviewer. Since B-021 (2026-10-19) nothing here is computed by matching the
    coach's words: what the coach said is the reviewer's to read and the claim reading's to
    measure (`chess_coach.eval.claims`).
    """

    n_turns: int
    phase_counts: dict[str, int]
    classification_counts: dict[str, int]
    fidelity_totals: dict[str, int]
    empty_feedback: int
    latency_mean_s: float
    latency_p90_s: float
    latency_max_s: float
    # Removed, all computed by matching the coach's words: `composed_fact_rate` and
    # `unsourced_square_rate` (squares pulled out of the reply), `recycled_phrase_rate`
    # (five-word windows of the reply), `graded_or_priced` (grade and price phrases), and
    # before them `lesson_concentration_rate` (B-005). B-021, 2026-10-19. Old transcripts still
    # carry the keys; `from_dict` ignores them.
    # Fidelity violations broken down by phase: the live checker's verdict on what shipped, kept
    # as data and no longer shown to the reviewer.
    fidelity_by_phase: dict[str, dict[str, int]] = field(default_factory=dict)
    # Turns whose PROMPT still contained a raw UCI token (e.g. "f6g4"). SAN
    # conversion degrades to raw UCI silently when handed the wrong base
    # position; a log warning is not a guard, so this is surfaced in the stats
    # block of every run (and to the frontier reviewer). Should be 0.
    prompt_uci_leaks: int = 0
    # Turns whose PROMPT still carried an eval magnitude. The same guard one level up:
    # a rendered figure is one f-string from returning, and two of this project's
    # recorded drops turned out to be live on a second path. Should be 0.
    prompt_magnitude_leaks: int = 0

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
            "fidelity_by_phase": {k: dict(v) for k, v in self.fidelity_by_phase.items()},
            "prompt_uci_leaks": self.prompt_uci_leaks,
            "prompt_magnitude_leaks": self.prompt_magnitude_leaks,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ReviewStats:
        """Rebuild from :meth:`to_dict`, tolerating older transcripts.

        Exists because reconstructing this field-by-field at a call site
        silently dropped the newer metrics (specificity, principle-connection,
        per-phase fidelity, UCI leaks) — they defaulted to 0 and a frontier
        reviewer was then told specificity was 0%, which it (correctly) called
        alarming. Round-tripping through one place keeps the class and its
        serialization from drifting again.
        """
        return cls(
            n_turns=d["n_turns"],
            phase_counts=dict(d.get("phase_counts", {})),
            classification_counts=dict(d.get("classification_counts", {})),
            fidelity_totals=dict(d.get("fidelity_totals", {})),
            empty_feedback=d.get("empty_feedback", 0),
            latency_mean_s=d.get("latency_mean_s", 0.0),
            latency_p90_s=d.get("latency_p90_s", 0.0),
            latency_max_s=d.get("latency_max_s", 0.0),
            fidelity_by_phase={k: dict(v) for k, v in (d.get("fidelity_by_phase") or {}).items()},
            prompt_uci_leaks=d.get("prompt_uci_leaks", 0),
            prompt_magnitude_leaks=d.get("prompt_magnitude_leaks", 0),
        )


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Nearest-rank percentile of an already-sorted list (empty -> 0.0)."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = max(0, min(len(sorted_vals) - 1, round(pct / 100 * (len(sorted_vals) - 1))))
    return sorted_vals[rank]


# REMOVED 2026-10-19 (B-021, the owner's approval): every stat here computed by matching the
# coach's words — squares pulled out of the reply (composed-fact and unsourced-square rates),
# five-word windows of the reply (recycled phrasing), and grade or price phrases in the reply.
# The judge's stats block no longer shows any of them; what the coach SAID is the frontier
# reviewer's to read, and the claim reading's to measure (`chess_coach.eval.claims`). What is left
# reads our own prompt.
#
# A bare UCI move token ("f6g4"): should never appear in a rendered prompt, since
# every move is meant to be SAN. Detects silent SAN-conversion fallbacks.
_UCI_TOKEN_RE = re.compile(r"\b[a-h][1-8][a-h][1-8][qrbn]?\b")
# An eval magnitude or a relayed engine verdict in a rendered PROMPT. Anchored on the
# labels and units the prompt used to carry ("Evaluation drop: 90 centipawns",
# "Classification: inaccuracy", "(+40 cp, sound)") rather than on bare digits, which
# occur legitimately all over a prompt (square names, move numbers, word limits).
_PROMPT_MAGNITUDE_RE = re.compile(
    r"centipawns?\b|[-+]?\d+\s*cp\b|\bevaluation drop\b|\bclassification:|\bannotation:|\boverall evaluation\b",
    re.IGNORECASE,
)
# NB: a list of "principle keywords" used to live here, with a 120-character
# proximity rule, to detect whether the coach applied a principle to the position
# instead of just stating one. It is gone. Words like "material", "capture",
# "exchange" and "center" appear in essentially any chess sentence, so it passed
# on 44 of 44 real responses and on prose written specifically to fail it. See
# the ReviewStats docstring; that question belongs to the frontier review.


# No repeated-LESSON counter lives here any more, and none should be rebuilt over the
# model's wording. Counting distinct closing sentences saturated at 95-100% and was
# deleted; `lesson_concentration`, the three commonest content words of the last
# sentence, was deleted 2026-10-12 (B-005) after it missed the repetition on the very
# review that called it "the number to trust". What WE composed is counted exactly by
# `scripts/eval_hard_metrics.py` (`lesson_conc_pct`); what the student actually read is
# the reviewer's to count from the transcript.


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
        fidelity_by_phase={k: dict(v) for k, v in by_phase.items()},
        prompt_uci_leaks=sum(1 for t in turns if t.prompt and _UCI_TOKEN_RE.search(t.prompt)),
        prompt_magnitude_leaks=sum(1 for t in turns if t.prompt and _PROMPT_MAGNITUDE_RE.search(t.prompt)),
    )


# The teaching standard the reviewer grades against — a compact restatement of
# the VISION "bridge" so the review is anchored to the product's own north star,
# not the reviewer's ad-hoc taste.
#: Kept in step with VISION.md by hand. Amended 2026-09-22 when the owner settled a contradiction
#: that had been in the north star for months: end 2 used to read "the specific move or plan", while
#: the same document said we are not the thing that reports best moves. Every review before this
#: date graded against the old reading, so their scores are not comparable with later ones.
_BRIDGE_STANDARD = """\
The product is a TEACHER for a player trying to improve — not a position
analyst. Every piece of coaching should be a BRIDGE with two ends:
  1. WHAT TO FOCUS ON — a named principle/theme the student may know in the
     abstract (center control, development, king safety, a tactic, an endgame
     technique).
  2. THE CUE ON THIS BOARD — the specific square, piece or fact that the
     principle points at here, at the student's level. "Your pawn on f2 is
     attacked twice and defended once" is end 2. Naming the MOVE is not:
     the move belongs behind a hint the student can ask for, and a coach
     that announces the engine's best move every turn is the thing Lichess
     already does for free.
Pure analysis ("Nf3 is best, +0.4") is only end 2 and not even the right half
of it; a principle lecture is only end 1. Good coaching connects both,
grounded in the engine truth shown, at the student's level, warm but concise.

DO NOT mark the coach down for failing to name the better move, and DO NOT
recommend that it name one. That is a settled product decision, not an
oversight. DO mark it down for naming a move that is still playable, for
withholding the cue and leaving only a maxim, or for a cue the board
contradicts.\
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


# ---------------------------------------------------------------------------
# Rubric v2 — per-category scoring against an EXTERNALLY derived standard.
# ---------------------------------------------------------------------------
#
# Why replace the single 0-10: it sat at 3.5-4.5 across fifteen changes,
# including 4.5 for a lever we reverted as ineffective. Two causes, both fixed
# here. (1) The old task defined only the ENDPOINTS of the scale, so the judge
# re-anchored the middle every run — the same defect that made absolute scoring
# useless in the guidance A/Bs, where the fix was to stop asking for a bare
# number. (2) One number over a composite standard averages away a gain in any
# single part: lesson concentration fell 82% -> 45% with no score movement, and
# the judge once called a 14% factual-defect rate "the single most disqualifying
# fact" and then scored mid-band. Its words and its number did not agree.
#
# The categories are NOT ours. VISION forbids sourcing the standard from inside
# the project ("the standard for good coaching cannot be sourced from the product
# owner's chess judgment; it must come from outside"), and a rubric decomposed
# from VISION.md would be circular. They come from asking claude-opus-5 twice,
# blind to VISION and to any transcript, via two different framings; the
# categories came back stable and rank-consistent. Full derivation and sourcing:
# docs/coaching-standard-audit.md and docs/audit/blind-derivation-{a,b}.md.
_RUBRIC_V2 = """\
Score each category 0-10 against these anchors. The anchors matter more than your
overall impression: two graders reading the same transcript should land close.

1. FIDELITY — is every factual claim about the position true?
   4 = contains a plausible-sounding falsehood (wrong piece captured, a threat that
       does not exist, a move that is not legal).
   6 = all material claims true; one loose imprecision that does not mislead.
   8 = every claim checks out against the board and the engine output.

2. DIAGNOSIS — does it address the thing that actually decided this move, and name
   the CAUSE rather than only the existence of the error?
   4 = discusses a real but secondary feature while the game is being decided
       elsewhere; or "that was a mistake, X was better" with no account of what
       went wrong.
   6 = identifies the right board feature but stops at board level — describes the
       error without naming the thinking failure behind it.
   8 = names the specific process failure (e.g. "that rook was doing a job and you
       moved it anyway"), and it is genuinely the failure this move exhibits.

3. TRANSFER HANDLE — does it attach a recognizable CUE to a concrete check, so the
   lesson can fire again in a position that looks nothing like this one?
   4 = nothing reusable, or a slogan with no condition attached.
   6 = a correct principle, unconditionalized ("remember to count defenders") —
       true, already known to this student, no trigger for when to do it.
   8 = cue and action both present and both concrete, naming where the pattern
       bites.

4. EXECUTABILITY — could THIS student carry the advice out unaided, in-game?
   4 = requires strength they lack: assessing the resulting endgame, prophylaxis,
       or a refutation resting on a long tactic.
   6 = doable but expensive — a check they can perform but not sustain every move.
   8 = a single check a 1200 can complete in seconds from what is on the board.

5. LOAD DISCIPLINE — one takeaway, in what is visible, nothing to hold in the head.
   4 = two or more ideas of comparable weight, or a variation needing blind
       visualization past a couple of plies.
   6 = one main idea plus an aside. Survivable, diluted.
   8 = exactly one takeaway, everything it points at visible on the current board.

6. STANCE — about the move and the process, never about the student; honest about
   the size of the error without amplifying or softening it into a lie.
   4 = person-level attribution ("careless again"), catastrophizing, or false
       praise on a bad move.
   6 = mild compliment-sandwich framing; accurate content, padded.
   8 = move and process only, cost stated plainly and once, no padding either way.

7. STREAM BEHAVIOUR (judge across the whole game, not per move) — does it build a
   thread, revisit the student's actual recurring weakness with increasing
   specificity, stay quiet when there is nothing worth saying, and avoid repeating
   itself?
   4 = near-verbatim repetition, or a brand-new unrelated theme every move with no
       thread, or full-length commentary on every move.
   6 = a recognizable thread plus several unrelated one-offs.
   8 = two or three themes for the game; the dominant weakness revisited at
       increasing specificity; unremarkable moves get a clause or nothing; no
       message duplicates an earlier one.

GATES. These are not averaged — they cap the whole score, because a failure here
means the coaching would have been better unsent:
- FIDELITY at or below 4 caps the overall at 2/10. A confident falsehood is worse
  than silence: the student cannot detect it and will apply it for months.
- STANCE at or below 4, in the person-attribution or false-praise varieties, caps
  the overall at 3/10.
- DIAGNOSIS at or below 3 caps the overall at 4/10. Teaching an irrelevance
  elegantly trains the student to attend to the wrong feature.

Otherwise weight: Diagnosis 25, Transfer Handle 25, Executability 15, Load
Discipline 10, Stance 10, Stream Behaviour 10, Fidelity gate-only (there is no
credit for being true, only a penalty for being false).

ALSO TREAT AS DEFECTS, not neutral: engine evaluations or centipawns shown to the
student; variations beyond a couple of plies; recommending a best move the student
could not have found by a repeatable method; opening names and book moves;
listing everything wrong with a move rather than the one thing that matters;
praise as content rather than tone; commenting at full length on every move.\
"""

_REVIEW_TASK_V2 = """\
You are a strong chess teacher AND a hard-nosed product reviewer. Judge HONESTLY
against the rubric above. Low scores are welcome if deserved; do not flatter.
Ground every point in specific plies.

Return, in this order:

1. CATEGORY SCORES — one line per category, as "NAME: X/10", each followed by one
   sentence citing the plies that set it. Use the anchors, not your impression.
2. GATES — state explicitly whether any gate fired, and which.
3. OVERALL: X/10 — applying the weights and any gate cap. State the arithmetic in
   one line so it can be checked. Say "SCORE: X/10" as well, on its own line.
4. WHAT HOLDS THE LOWEST TWO CATEGORIES BACK — for each, the specific blocker, and
   what would have to become true to move it two points. Estimate the
   implementation cost of each as SMALL / MEDIUM / LARGE.
5. WHAT TO REMOVE — anything the coach is doing that it should stop doing. Answer
   even if the answer is "nothing"; deletions have been our highest-yield changes.
6. PHASE FIT — does the coaching suit each phase present (opening / middlegame /
   endgame)? Note any phase under-covered in this transcript.
7. HIGHEST-LEVERAGE CHANGE — one change, with its cost, and what you would expect
   to move if we made it.\
"""


def _fmt_stats(stats: ReviewStats) -> str:
    phases = ", ".join(f"{_PHASE_LABEL.get(k, k)}: {v}" for k, v in sorted(stats.phase_counts.items()))
    cls = ", ".join(f"{k}: {v}" for k, v in sorted(stats.classification_counts.items()))
    # No figure about what the coach SAID (B-021, the owner's approval 2026-10-19). Six lines
    # stood here, each computed by matching the coach's words: the checker's violation counts
    # (total and by phase), composed-fact and unsourced-square rates, recycled phrasing, and grading or pricing. On
    # v62 the first read "none" on every game while the claim reading found 5 false replies.
    # The reviewer reads the transcript itself, as it already does for repeated lessons (B-005).
    return (
        f"Coached moves: {stats.n_turns}\n"
        f"Phase coverage: {phases or 'none'}\n"
        f"Move quality (engine): {cls or 'none'}\n"
        f"Empty feedback turns: {stats.empty_feedback}\n"
        f"Prompts still containing raw UCI (should be 0): {stats.prompt_uci_leaks}\n"
        f"Prompts still containing an eval magnitude (should be 0): {stats.prompt_magnitude_leaks}\n"
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


#: Rubric versions the report card can be judged under. ``v1`` is the original
#: single holistic 0-10 against the bridge standard, kept so the progression table
#: has a comparable series and so a change of ASK can be A/B'd on one transcript.
#: ``v2`` is the externally-derived per-category rubric with gates.
RUBRIC_VERSIONS = ("v1", "v2")


def build_coach_review_prompt(turns: list[ReviewTurn], stats: ReviewStats, rubric: str = "v1") -> str:
    """Compose the single holistic-review prompt for a frontier reviewer.

    Bundles the teaching standard, the objective stats, and the full coached
    transcript, then asks for a score + honest critique + phase-fit assessment.
    Pure string assembly so it is unit-testable.

    ``rubric`` selects the ask: ``v1`` requests one holistic 0-10, ``v2`` requests
    per-category scores against externally derived anchors with gates. The two are
    deliberately runnable on the SAME transcript, because changing the ask has
    already been shown to change the answer materially — re-judging an identical
    v21 transcript with a corrected stats block turned its top weakness into its
    second strength.
    """
    if rubric not in RUBRIC_VERSIONS:
        raise ValueError(f"unknown rubric {rubric!r}; expected one of {RUBRIC_VERSIONS}")
    transcript = "\n\n".join(_fmt_turn(t) for t in turns)
    head = (
        "=== TEACHING STANDARD (the bar) ===\n"
        f"{_BRIDGE_STANDARD}\n\n"
        "=== OBJECTIVE STATS (deterministic, engine-derived) ===\n"
        f"{_fmt_stats(stats)}\n\n"
        "=== COACHING TRANSCRIPT (one real game, shipping config) ===\n"
        f"{transcript}\n\n"
    )
    if rubric == "v1":
        return head + "=== YOUR REVIEW ===\n" + _REVIEW_TASK
    return head + "=== RUBRIC ===\n" + f"{_RUBRIC_V2}\n\n" + "=== YOUR REVIEW ===\n" + _REVIEW_TASK_V2


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

MANDATORY FOR EVERY DEFECT AND EVERY CHANGE YOU PROPOSE IN 2, 3 AND 4: say how
to MEASURE it. Give, in one or two sentences each:

  (a) THE COUNT — what exactly to count, per turn, precisely enough that two
      people would compute the same number;
  (b) its EXPECTED CURRENT VALUE on the turns you can see, or "cannot tell" if
      you genuinely cannot;
  (c) WHAT WOULD COUNT AS FIXED — a threshold — and what value would mean the
      change made things WORSE;
  (d) what the measure would MISS.

Every measure must obey the anchoring constraint listed under CONSTRAINTS: the
board, our composed text, move tokens, squares, eval drop, phase, earlier turns.
Not phrase or wording matching in the coach's output.

If a defect you want to raise cannot be measured that way, SAY SO EXPLICITLY and
raise it anyway, flagged as unmeasurable. That is a useful answer, and far more
useful than a plausible-sounding measure we cannot compute. Do not weaken a real
criticism to make it measurable.

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
