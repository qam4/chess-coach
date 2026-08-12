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

    What is left is of two kinds:

    * **Checked against the position.** ``fidelity_totals`` and
      ``fidelity_by_phase`` come from :mod:`chess_coach.verify`, which pulls move
      tokens out of the text and parses them against the real board, so it can
      say the coach was *wrong*. ``prompt_uci_leaks`` checks our own rendered
      prompt.
    * **Checked against our own prompt.** ``composed_fact_rate`` and
      ``unsourced_square_rate``: did the coach name a square we gave it, or one
      we did not. Both are facts about our data, not guesses about meaning — but
      neither says whether the sentence around the square is true or worth
      reading.

    Plus plain counts: ``empty_feedback``, latency, and the phase and move-quality
    mixes.

    None of these is a target. Every one can be moved by padding the output with
    square names, which would make the coaching worse while the numbers improved.
    They anchor the frontier review in facts and catch regressions; a rate that
    moves is a reason to go and read the output, not a result.
    """

    n_turns: int
    phase_counts: dict[str, int]
    classification_counts: dict[str, int]
    fidelity_totals: dict[str, int]
    empty_feedback: int
    latency_mean_s: float
    latency_p90_s: float
    latency_max_s: float
    # Squares the coach names beyond the played and best moves, split by where
    # they came from. These replaced a single `specificity_rate`, which lumped
    # them together and so could rise for either a good reason or a bad one.
    # `composed_fact_rate`: it voiced a square we gave it — the architecture
    # working as designed (compose the fact, let the model say it).
    # `unsourced_square_rate`: it named a square that was nowhere in its prompt.
    # Not automatically wrong, but this is where fabrication would show up.
    # Both are 0.0 when the transcript did not capture prompts.
    composed_fact_rate: float = 0.0
    unsourced_square_rate: float = 0.0
    # Repetition, the one thing a frontier reviewer has now complained about
    # twice and counted by hand while we had no measurement for it at all.
    # `recycled_phrase_rate`: mean share of each turn's five-word windows that
    # already appeared in an earlier turn (0 = always fresh wording). Measures
    # repeated WORDING.
    # `lesson_concentration_rate`: share of turns whose closing lesson is one of
    # the three most common. Measures repeated MEANING, which is the thing that
    # was actually complained about — the model rewords freely while teaching the
    # same lesson, so the two numbers move independently.
    recycled_phrase_rate: float = 0.0
    lesson_concentration_rate: float = 0.0
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
            "composed_fact_rate": round(self.composed_fact_rate, 4),
            "unsourced_square_rate": round(self.unsourced_square_rate, 4),
            "recycled_phrase_rate": round(self.recycled_phrase_rate, 4),
            "lesson_concentration_rate": round(self.lesson_concentration_rate, 4),
            "fidelity_by_phase": {k: dict(v) for k, v in self.fidelity_by_phase.items()},
            "prompt_uci_leaks": self.prompt_uci_leaks,
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
            composed_fact_rate=d.get("composed_fact_rate", 0.0),
            unsourced_square_rate=d.get("unsourced_square_rate", 0.0),
            recycled_phrase_rate=d.get("recycled_phrase_rate", 0.0),
            lesson_concentration_rate=d.get("lesson_concentration_rate", 0.0),
            fidelity_by_phase={k: dict(v) for k, v in (d.get("fidelity_by_phase") or {}).items()},
            prompt_uci_leaks=d.get("prompt_uci_leaks", 0),
        )


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Nearest-rank percentile of an already-sorted list (empty -> 0.0)."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = max(0, min(len(sorted_vals) - 1, round(pct / 100 * (len(sorted_vals) - 1))))
    return sorted_vals[rank]


# A square reference (a1..h8) anywhere in the text, INCLUDING inside a SAN token.
# The single rule is "not the second half of a coordinate pair", so a UCI token
# like "f6g4" reads as one square rather than two, and everything else matches.
#
# Validated rather than eyeballed: over 128,411 legal-move SANs generated with
# python-chess across 60 random games, this finds the destination square of every
# single one. Two earlier attempts did not, which is why the rule is this plain:
#   `\b[a-h][1-8]\b`                        missed 76.1% — a leading piece or
#       file letter kills the word boundary, so "Nf3", "Ra8#" and "cxd5" matched
#       NOTHING. That silently broke both metrics below: coaching that named a
#       square only in SAN scored as naming none, and `is_specific`'s discount
#       set (built from the move SANs) was empty for every piece move, so it
#       discounted nothing and over-credited.
#   `(?<![a-h])(?<![0-9])[a-h][1-8](?![0-9])`  missed 1.1% — the lookbehinds also
#       reject disambiguated SAN, where a file or rank precedes the destination:
#       "Nbd7", "Rae1+", "Rgg1", "R1e2".
# Known, deliberate gap: castling ("O-O") names no square and so contributes
# none, in the text or in the discount set.
_SQUARE_RE = re.compile(r"(?<![a-h][1-8])[a-h][1-8]")
# A bare UCI move token ("f6g4"): should never appear in a rendered prompt, since
# every move is meant to be SAN. Detects silent SAN-conversion fallbacks.
_UCI_TOKEN_RE = re.compile(r"\b[a-h][1-8][a-h][1-8][qrbn]?\b")
# NB: a list of "principle keywords" used to live here, with a 120-character
# proximity rule, to detect whether the coach applied a principle to the position
# instead of just stating one. It is gone. Words like "material", "capture",
# "exchange" and "center" appear in essentially any chess sentence, so it passed
# on 44 of 44 real responses and on prose written specifically to fail it. See
# the ReviewStats docstring; that question belongs to the frontier review.


#: Length of the word window used to detect recycled phrasing. Five words is long
#: enough that ordinary chess vocabulary ("your knight on") does not match by
#: accident, and short enough to catch a reworded template.
_SHINGLE_N = 5

#: Sentence terminators, for pulling the closing sentence off a response.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _normalise_words(text: str) -> list[str]:
    """Lowercased word list with markdown and punctuation stripped."""
    return re.findall(r"[a-z0-9]+", text.lower())


def _shingles(text: str, n: int = _SHINGLE_N) -> set[str]:
    """The set of n-word windows in ``text``."""
    words = _normalise_words(text)
    if len(words) < n:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def recycled_phrase_rates(turns: list[ReviewTurn]) -> list[float]:
    """Per turn: the fraction of its phrasing that already appeared earlier.

    Answers the complaint a frontier reviewer raised twice and counted by hand —
    that the coaching is "wallpaper", the same few sentences regardless of the
    position. For each turn, what share of its five-word windows occurred in any
    PREVIOUS turn: 0.0 is all fresh wording, 1.0 is a verbatim rehash. The first
    turn has nothing to repeat and is always 0.0.

    Deterministic, needs no model, and unlike the square-based screens it cannot
    be improved by padding the output with board references. It IS gameable by
    padding with *novel* words, so read it next to the word-count limits rather
    than alone.
    """
    seen: set[str] = set()
    rates: list[float] = []
    for turn in turns:
        current = _shingles(turn.coach_feedback)
        if not current:
            rates.append(0.0)
            continue
        rates.append(len(current & seen) / len(current) if seen else 0.0)
        seen |= current
    return rates


def closing_sentence(turn: ReviewTurn) -> str:
    """The response's last sentence, normalised for comparison.

    The closing "next time you see X, ask yourself Y" hook is where the reviewer
    found the worst repetition, so it is worth measuring separately from the body:
    a response can be specific about the position and still end with the same
    lesson every time.
    """
    text = turn.coach_feedback.strip()
    if not text:
        return ""
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    return " ".join(_normalise_words(sentences[-1])) if sentences else ""


#: Template scaffolding and generic English, removed before looking at what a
#: closing sentence is actually about.
#:
#: This is a word list, and this file deleted a metric for being built on a word
#: list, so the difference matters: that one used keywords to decide whether prose
#: was GOOD, which a keyword cannot know. These words are removed to count how
#: often the same lesson recurs — a frequency measure over what is left. Adding a
#: word here cannot make the coaching look better, only make the measurement
#: blunter, and the result was checked against an independent count (below).
_TEMPLATE_WORDS = frozenset(
    """next time you see a an the your my is are was were do does did can could i it
    its this that these those and or but if when whether ask yourself asking to of on
    in at for with without be been being have has had will would should shall may
    might must there their they them then than so as by from up down out off over
    under again more most less least very just also too not no yes what which who
    whom how why where takeaway transferable move moves moved making make makes made
    piece pieces play plays played player position positions board game games one two
    first next last other another same different good better best strong stronger
    weak weaker safe safer keep keeps kept get gets got put puts placing place""".split()
)

#: How many of the most common closing terms count as "the coach's usual lessons".
#: Three, because that is the claim being measured: a reviewer counting by hand
#: said the closing question was "almost always one of three templates".
_CONCENTRATION_TOP_N = 3


def _lesson_terms(text: str) -> set[str]:
    """Content words of a closing sentence — what the lesson is *about*."""
    return {w for w in _normalise_words(text) if w not in _TEMPLATE_WORDS and len(w) > 2}


def lesson_concentration(turns: list[ReviewTurn]) -> float:
    """Share of turns whose closing lesson is one of the three most common.

    Measures "the coach teaches the same few lessons regardless of the position",
    which is the complaint a frontier reviewer raised twice and quantified by hand.
    Lower is better; 1.0 means three ideas cover the whole game.

    Two earlier designs for this failed and are worth recording, because both
    looked reasonable:

    * ``recycled_phrase_rate`` (kept, below) measures repeated *wording*. It reads
      21-23% flat across three runs and its worst turns overlapped the reviewer's
      cited plies only 3 of 12 — because the model rewords freely while keeping the
      lesson identical.
    * counting *distinct closing sentences* scored 95-100%, i.e. saturated and
      useless, for the same reason: "next time you see a fork..." and "next time
      you see your knight on the back rank..." are different strings and the same
      template. It was deleted rather than kept with a warning.

    This one agrees with the hand count: three terms cover 57-68% of turns in the
    runs measured, matching "almost always one of three templates".
    """
    per_turn = [_lesson_terms(closing_sentence(t)) for t in turns]
    frequency: Counter[str] = Counter()
    for terms in per_turn:
        frequency.update(terms)
    if not frequency or not turns:
        return 0.0
    common = {term for term, _ in frequency.most_common(_CONCENTRATION_TOP_N)}
    return sum(1 for terms in per_turn if terms & common) / len(turns)


def _extra_squares(turn: ReviewTurn) -> set[str]:
    """Squares the response names beyond the played and best moves.

    Discounting the two moves is the point: repeating the move you were handed is
    not saying anything about the position.
    """
    text = turn.coach_feedback
    if not text.strip():
        return set()
    own = {s.lower() for s in _SQUARE_RE.findall(turn.student_move_san + " " + turn.best_move_san)}
    return {s.lower() for s in _SQUARE_RE.findall(text)} - own


def voices_composed_fact(turn: ReviewTurn) -> bool:
    """True if the coach voiced a square we put in its prompt.

    This is the architecture working as intended — compose the fact, let the
    model say it — so this is the rate worth watching. Needs a captured prompt;
    without one it cannot be judged and returns False.
    """
    if not turn.prompt:
        return False
    prompt = turn.prompt.lower()
    return any(sq in prompt for sq in _extra_squares(turn))


def names_unsourced_square(turn: ReviewTurn) -> bool:
    """True if the coach named a square that was NOT anywhere in its prompt.

    Not automatically wrong — the model can legitimately read the board
    description — but this is where fabrication would surface, so it belongs
    beside the fidelity counts rather than among the prose metrics. Measured at
    1 turn in 44 on v19.
    """
    if not turn.prompt:
        return False
    prompt = turn.prompt.lower()
    return any(sq not in prompt for sq in _extra_squares(turn))


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
        composed_fact_rate=(sum(1 for t in turns if voices_composed_fact(t)) / n) if n else 0.0,
        unsourced_square_rate=(sum(1 for t in turns if names_unsourced_square(t)) / n) if n else 0.0,
        recycled_phrase_rate=(sum(recycled_phrase_rates(turns)) / n) if n else 0.0,
        lesson_concentration_rate=lesson_concentration(turns),
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
        # Spell out which direction is good. Labelled neutrally, a reviewer read
        # "names a square we did not supply: 0%" as the coach being blind to the
        # position and made it the headline recommendation — when 0% is the design
        # working as intended. A number handed to a reader without its sign is an
        # invitation to misread it.
        f"Turns voicing a board fact we composed for it: {stats.composed_fact_rate:.0%} "
        f"(HIGHER IS BETTER — by design the engine/composer derives the facts and the "
        f"coach's job is to voice them, so this is the architecture working)\n"
        f"Turns naming a square we never supplied: {stats.unsourced_square_rate:.0%} "
        f"(LOWER IS BETTER — the model has no way to verify a square we did not give "
        f"it, so this is where fabrication appears; 0% is the target, not a weakness)\n"
        f"Recycled phrasing: {stats.recycled_phrase_rate:.0%} of an average turn's "
        f"five-word phrases already appeared in an earlier turn "
        f"(LOWER IS BETTER — repeated wording)\n"
        f"Lesson concentration: {stats.lesson_concentration_rate:.0%} of turns close on "
        f"one of only three recurring lessons "
        f"(LOWER IS BETTER — repeated meaning, i.e. the same advice regardless of the "
        f"position; this is measured, so you do not need to count it by hand)\n"
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
