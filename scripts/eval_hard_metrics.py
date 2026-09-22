"""Deterministic quality counters over one or more report-card transcripts.

Why this exists. The frontier judge's per-category scores turned out not to be a
measurement. Feeding it the SAME v42 transcript three times produced overalls of 5.5,
5.0 and 2.0, and its fidelity gate fired on one of the three — so the entire v37-v42
score sequence is indistinguishable from re-rolling dice, and several ledger rows that
attributed a movement to a change have had to be retracted.

What survived that discovery is everything checked against the board. So this script
counts only things that cannot drift: either the rules of chess say them or they are
arithmetic over the transcript. Run it twice on the same input and it returns the same
numbers, which is the property the judge lacked.

It is not a replacement for the judge's prose. Reading the critique is still how defects
get found — the missing hanging-piece data and the fact-budget insight both came from it.
This is for answering "did that change help, and is the coach safe to put in front of a
1200", which is the question the score was failing to answer.

Usage::

    python scripts/eval_hard_metrics.py output/coach_review_v*/transcript.json
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import chess

from chess_coach.verify import check_text_fidelity, gating_violations

#: Phrases that put a motive in the student's mouth. The reviewer flagged these on
#: several runs ("I see you're trying to develop your pieces" on a move that did nothing
#: of the kind) and they are the one Stance defect with a mechanical signature.
#: A LIST of exact phrases was the first version and it undercounted by roughly nine times: it
#: held only "I see you're trying" and its variants, so the ledger recorded 1-2 turns per game
#: while the actual rate was 5-7 — which `_check_intent_attribution`'s docstring had already
#: measured and written down. Surveying every stored transcript found 148 instances and the
#: dominant forms were all absent from the list: "your move aimed to ..." 55, "you were looking
#: to ..." 26, "you were aiming to ..." 23, "you were trying to ..." 11, against 26 for the one
#: phrase we were counting.
#:
#: So: a pattern over the SHAPE — an intent verb applied to the student — rather than a list of
#: remembered sentences. The lesson generalises past this counter: a detector built from the
#: examples someone happened to quote will measure those examples and nothing else.
#: Cues that make the following clause ADVICE rather than a claim about what the student
#: thought. "Next time you are looking for a way to improve, ask yourself..." is the takeaway
#: hook doing its job; counting it as mind-reading would penalise the thing we want. Found by
#: reading the two turns the counter still flagged after the prompt fix — both were this.
_HYPOTHETICAL = ("next time", "whenever", "when ", "if ", "should ", "always ", "before you")
_HYPOTHETICAL_LOOKBACK = 24

MIND_READING_RE = re.compile(
    r"\b(?:"
    r"i (?:can )?see (?:that )?you"
    r"|i notice (?:that )?you"
    r"|(?:it )?(?:looks|sounds|seems) like you"
    r"|(?:it )?seems (?:that )?you"
    r"|you(?:'re| are| were) (?:trying|looking|hoping|aiming|planning|going for)"
    r"|you (?:tried|wanted|intended|hoped|aimed|meant|planned)"
    r"|your (?:move|plan|idea|intention|goal|aim)s? (?:was|were|is|aimed|tried|intended|wanted|sought|hoped)"
    r")\b",
    re.IGNORECASE,
)


def _mind_reads(low: str) -> bool:
    """Does the text claim to know what the student was thinking?

    A claim about the past, not advice about the future. The pattern alone cannot tell the two
    apart — "you are looking for a way to improve" is mind-reading after "I see" and a habit
    prompt after "next time" — so each match is checked against what precedes it.
    """
    for m in MIND_READING_RE.finditer(low):
        before = low[max(0, m.start() - _HYPOTHETICAL_LOOKBACK) : m.start()]
        if any(cue in before for cue in _HYPOTHETICAL):
            continue
        return True
    return False


#: A number that prices the position. Should be zero: the protocol forbids showing the
#: student an evaluation, and the units were never defensible anyway.
MAGNITUDE = ("centipawn", "cp)", " cp ", "+0.", "-0.", "eval of", "score of")


#: The habit-phrasings the diagnosis emits, matched on their distinctive middles so a
#: paraphrase still counts. Keying on the literal word "check" was wrong twice over: it
#: under-counted paraphrase, and it missed the composed fallback entirely, which renders the
#: same habit as "Worth remembering: before I commit, ..." with no "check" in it. That error
#: made a working fix read as 0 of 4 — the counter, not the coaching.
#:
#: RETIRED 2026-09-16 (ledger row 137). These phrases were lifted from our own composed
#: clauses, so the metric scored whether the model ECHOED our wording, not whether the turn
#: explained anything. First multi-model run exposed it: 50%/50% for qwen3:14b against
#: 17%/12% for gemma4:12b-it-qat, and all 29 gemma turns it scored zero on do explain why the
#: move failed. One missed on a single word — the list holds "check that was skipped" and
#: gemma wrote "check was skipped". Kept only to document what not to do again; broadening the
#: list is the approach ledger rows 27 and 95 record failing twice.
_RETIRED_CAUSE_PHRASES = (
    "attacked on the square",
    "only thing guarding",
    "check that was skipped",
    "thinking that went wrong",
)

#: The closing-takeaway instruction, in the four shapes the lesson ladder produces. Matching our
#: OWN prompt text, which is deterministic and exact — unlike matching the model's prose.
#:
#: Replaces a cue-word counter that read the last 14 words of the response for one of five
#: hardcoded phrases. That version was not merely noisy, it was directionally WRONG: it put v52
#: (22%) worse than v33 (17%), when v33 is the documented monoculture peak — the ledger names
#: the five plies where one lesson closed five of eighteen turns. Measured from composition the
#: same run reads 33% at v33 falling to 14% by v43, which matches the record.
_LESSON_TEACH = re.compile(r"CLOSE with one transferable takeaway on THIS lesson and no other:\s*(.+?)\.\s")
_LESSON_SUBST = re.compile(r"CLOSE with one transferable takeaway, and use THIS one[^:]*:\s*(.+?)\.\s")
_LESSON_REFRAME = re.compile(r"CLOSE by pointing out that this is the SAME idea as earlier[^\u2014]*\u2014\s*(.+?)\.\s")
#: An open-ended ask: we wanted a takeaway and named no lesson, so the MODEL chose the topic.
#: Distinct from silence, and the reason concentration cannot be measured before v30 — every
#: turn in that era was open, which is exactly what composing the subject was built to stop.
_LESSON_OPEN = re.compile(r"CLOSE with one transferable takeaway, not a generic maxim")


def _composed_lesson(prompt: str) -> tuple[str, str]:
    """``(state, lesson)`` for this turn's closing instruction.

    State is one of ``teach`` / ``subst`` / ``reframe`` (we named the lesson), ``open`` (we
    asked and let the model choose) or ``silent`` (the ladder retired it and we asked for
    nothing). Only the first three carry a lesson to count.
    """
    for state, rx in (("teach", _LESSON_TEACH), ("subst", _LESSON_SUBST), ("reframe", _LESSON_REFRAME)):
        m = rx.search(prompt)
        if m:
            return state, " ".join(m.group(1).split()).lower()
    return ("open" if _LESSON_OPEN.search(prompt) else "silent"), ""


#: The composed cause section, as `prompts._came_about` emits it. Deterministic: it is our own
#: text in our own prompt, so finding it is exact rather than a guess about prose.
_CAUSE_SECTION = re.compile(r"--- How this came about ---\s*\n(.+?)(?=\n---|\n\n|\Z)", re.DOTALL)

#: Square extraction is deliberately ASYMMETRIC, because the two sides want opposite things.
#:
#: STRICT, for the composed cause: a bare square only. "Before Bd2 your pawn on b2 was
#: defended" is about b2 — d2 is merely where the bishop went, and anchoring on a move's
#: destination would point the metric at the wrong square.
#:
#: LOOSE, for the coach's text: a square even inside a SAN token, because that is still naming
#: it. Measured — at ply 8 of seed 13 the cause was "their bishop on c3 was attacked and
#: undefended, and bxc3 does not take it", and the coach answered "the stronger move was Bxc3,
#: capturing their bishop". Strict matching scored that a miss, which it plainly is not.
_SQUARE_STRICT = re.compile(r"\b([a-h][1-8])\b")
_SQUARE_LOOSE = re.compile(r"(?<![a-h0-9])([a-h][1-8])(?![0-9])", re.IGNORECASE)


def _cause_squares(prompt: str) -> set[str] | None:
    """Squares the composed cause is ABOUT, or None when no cause was composed.

    The anchor is a set of squares rather than any wording, which is the whole point: a board
    fact ports across models where our phrasing does not. Returns an empty set when a cause
    was composed but names no square — the repeat-clause-only case, "This same piece already
    came up on move 6" — which is given but not scorable, and must not be counted either way.
    """
    m = _CAUSE_SECTION.search(prompt)
    if not m:
        return None
    return set(_SQUARE_STRICT.findall(" ".join(m.group(1).split())))


#: The one cause class this measure applies to: OUR piece lost a defender. Matched on the
#: composed frame, which is our own deterministic text, not the model's prose — the frame is
#: emitted verbatim by `error_diagnosis` so its shape is fixed.
#:
#: Deliberately NOT applied to "their piece on X was attacked and undefended, and <move> does not
#: take it". That is a missed capture, about the OPPONENT's piece, where "can the opponent attack
#: this square" is a meaningless question. Asking it anyway was the first version of this check and
#: it flagged five turns that were not defects.
_CAUSE_OWN_PIECE = re.compile(
    r"Before \S+ your (?:\w+) on ([a-h][1-8]) was defended; after it, it is not",
    re.IGNORECASE,
)


def _cause_own_piece_square(prompt: str) -> str:
    """The square of OUR piece that the composed cause says lost its defender; "" if none."""
    m = _CAUSE_OWN_PIECE.search(prompt)
    return m.group(1).lower() if m else ""


def _square_is_contested(fen: str, student_san: str, square: str) -> bool:
    """After the student's move, can the opponent attack ``square`` now or in one move?

    Rules geometry only — `board.attackers` and legal move generation. No piece values, no
    assessment of whether the capture would be good, so it stays on our side of the line with the
    engine. Returns True on anything it cannot determine, so an unparseable position can never
    manufacture a defect.
    """
    try:
        board = chess.Board(fen)
        move = board.parse_san(student_san)
    except Exception:
        return True
    after = board.copy(stack=False)
    after.push(move)
    sq = chess.parse_square(square)
    them = not board.turn
    if after.attackers(them, sq):
        return True
    probe = after.copy(stack=False)
    if probe.turn != them:
        if probe.is_check():
            return True  # cannot null-move out of check; do not claim the square is safe
        probe.push(chess.Move.null())
    for cand in probe.legal_moves:
        nxt = probe.copy(stack=False)
        nxt.push(cand)
        if nxt.attackers(them, sq):
            return True
    return False


def _threat_materialises(turns: list[dict[str, object]], turn: dict[str, object], square: str) -> bool:
    """Did the opponent ever attack ``square`` later in the game as it was actually played?

    Deliberately NOT the detector's own test. `_square_is_contested` asks what the opponent could do
    next move, which is the predicate the detector applies, so a measure built on it cannot
    contradict the detector. This reads the continuation instead: the positions that really followed.

    Returns False when there is no continuation, which is why curated puzzle positions are filtered
    out by the caller rather than scored here.
    """
    try:
        us = chess.Board(turn["fen_before"]).turn
        sq = chess.parse_square(square)
    except Exception:
        return False
    for later in sorted(turns, key=lambda x: x.get("ply") or 0):
        ply = later.get("ply")
        if not isinstance(ply, int) or ply <= turn["ply"] or ply >= 1000:
            continue
        try:
            board = chess.Board(later.get("fen_before") or "")
        except Exception:
            continue
        # Stop once our piece is no longer there. `attackers` is about the SQUARE, so without this
        # a pawn that got traded off and a square attacked twenty plies later would score as the
        # warning coming true. A first version did exactly that and read 75% where a scan that
        # stopped at the capture read 69%.
        piece = board.piece_at(sq)
        if piece is None or piece.color != us:
            return False
        if board.attackers(not us, sq):
            return True
    return False


def _voices_the_cause(text: str, cause_sq: set[str]) -> bool:
    """Does the turn name a square the composed cause is about?

    Deliberately not "does it use a causal construction": that is phrasing, and phrasing is
    what the retired metric got wrong. Validated across two models — 100%/90% for qwen and
    92%/100% for gemma, a spread of ±8 points running in BOTH directions, against the retired
    metric's consistent 35-point gap.

    Known false-positive class, measured at ZERO occurrences over four runs: if the cause
    square is also the square the opponent captures on, a turn could name it just by reporting
    the capture. It has not happened, but it is the thing to re-check if this metric ever
    saturates suspiciously.

    Known FALSE NEGATIVE, and it is a limit of the design rather than a bug: a turn can convey
    the cause without coordinates. At ply 56 of seed 7 the cause was about e1 and the coach
    said "moving the rook left it undefended" — correct, and unscoreable here. So this metric
    UNDERCOUNTS, and the honest reading of a figure below 100% is "at least this many", not
    "exactly this many". Closing that gap means going back to matching phrasing, which is what
    the retired metric did wrong.
    """
    said = {s.lower() for s in _SQUARE_LOOSE.findall(text)}
    return bool(cause_sq & said)


@dataclass
class Metrics:
    """One transcript's counters. Every field is either a rule of chess or arithmetic."""

    name: str
    plies: int = 0
    spoken: int = 0
    violations: int = 0
    gating: int = 0
    turns_with_violation: int = 0
    kinds: Counter[str] = field(default_factory=Counter)
    cause_given: int = 0
    cause_anchorable: int = 0
    cause_voiced: int = 0
    cause_own_piece: int = 0
    cause_irrelevant: int = 0
    cause_materialised: int = 0
    repeat_rec: int = 0
    repeat_rec_words: int = 0
    repeat_rec_names_move: int = 0
    repeat_rec_has_lesson: int = 0
    mind_reading: int = 0
    magnitude: int = 0
    words: int = 0
    lesson_composed: int = 0
    lesson_open: int = 0
    lesson_silent: int = 0
    lessons: Counter[str] = field(default_factory=Counter)

    @property
    def clean_rate(self) -> float:
        """Share of spoken turns with nothing the board contradicts. The headline."""
        return 0.0 if not self.spoken else 100.0 * (self.spoken - self.turns_with_violation) / self.spoken

    @property
    def cause_given_rate(self) -> float:
        """Share of spoken turns we HANDED a composed cause. Ours, not the model's.

        Split from voicing because one number conflated them and reported neither. Measured at
        68-72%, so roughly three in ten spoken turns are given no cause at all — and that is a
        composition gap, fixable here, not something to push the model harder about.
        """
        return 0.0 if not self.spoken else 100.0 * self.cause_given / self.spoken

    @property
    def cause_voiced_rate(self) -> float:
        """Of the causes we composed AND could anchor, how many reached the student.

        Near ceiling (90-100% across two models), which is itself the finding: when a cause is
        composed it almost always gets voiced. Little headroom, so watch it for regressions
        rather than expecting gains.
        """
        return 0.0 if not self.cause_anchorable else 100.0 * self.cause_voiced / self.cause_anchorable

    @property
    def cause_irrelevant_rate(self) -> float | None:
        """Of the causes about OUR OWN piece losing a defender, how many name a square the
        opponent cannot attack. Lower is better; ``None`` when no such cause was composed.

        A cause of the form "before Kd1 your pawn on f2 was defended; after it, it is not" passes
        every fidelity check, because it is TRUE. `error_diagnosis` diffs DEFENDER sets and never
        asks whether anything attacks the square. Measured on v54: 16 such causes, and NONE of the
        16 named a square that was actually attacked after the move — four named one the opponent
        could not reach in a single move, including on the move that delivered checkmate.

        So this counts the thing no other instrument here can see: coaching that is true and
        useless. A student who follows it defends squares nothing attacks.

        Relevance is judged generously on purpose — attacked now, OR attackable after any one
        enemy move. A stricter test would flag a piece the opponent is a tempo away from winning,
        which is worth warning about. The aim is to catch the cases with no threat at all.
        """
        if not self.cause_own_piece:
            return None
        return 100.0 * self.cause_irrelevant / self.cause_own_piece

    @property
    def cause_materialised_rate(self) -> float | None:
        """Of the "you stopped defending X" warnings, how many named a square the opponent went on
        to attack IN THIS GAME. Higher is better; ``None`` when no such cause was composed.

        This is the only counter here that does not share a predicate with the thing it judges.
        `cause_irrelevant_rate` asks "can the opponent attack this square now or in one move",
        which is exactly the test the detector applies — so when the detector was fixed, that rate
        went to zero by construction and demonstrated nothing. This one reads the CONTINUATION,
        which the detector never sees, so it can come out against us.

        Measured when the relevance gate went in: 11 of 16 (69%) before, 10 of 12 (83%) after. The
        concrete fact behind those percentages, which is worth more than they are on 12 samples:
        the gate dropped four warnings, three about threats that never arrived and one that arrived
        28 plies later.

        Curated puzzle positions are excluded — they have no continuation, so a cause on one can
        never materialise, and counting them would push the rate down for a reason that has nothing
        to do with the detector.

        Known limit: the continuation is the line the opponent actually chose, not the best one.
        A square nobody attacked may still have been a real weakness they failed to exploit. So a
        low rate is a reason to look, not proof the warning was wrong.
        """
        if not self.cause_own_piece:
            return None
        return 100.0 * self.cause_materialised / self.cause_own_piece

    @property
    def repeat_rec_rate(self) -> float:
        """Share of spoken turns re-recommending a move already recommended in this game.

        The POPULATION, not an outcome: the coach has no memory across turns, so when the student
        misses the same move four times it gets four full-length explanations. Measured on v55 at 17
        of 81 spoken turns. `Nxc7+` was recommended on plies 17, 19, 21 and 23, then played on 25.

        This number does NOT move when the repetition is fixed — the student still misses the move
        the same number of times, because the simulated student's move is chosen before the coach
        speaks and cannot respond to it. What should move is `repeat_rec_words_per_turn`, and what
        must NOT move are the two guardrails below.
        """
        return 0.0 if not self.spoken else 100.0 * self.repeat_rec / self.spoken

    @property
    def repeat_rec_words_per_turn(self) -> float:
        """Mean length of a re-recommending turn. Measured at 64.5 words against 65.2 overall.

        A teacher shortens on the fourth telling. Treat a fall here as the mechanism firing rather
        than as a benefit: an instruction that says "be brief" makes this fall by construction, and
        shorter is not automatically better.
        """
        return 0.0 if not self.repeat_rec else self.repeat_rec_words / self.repeat_rec

    @property
    def repeat_rec_names_move_rate(self) -> float | None:
        """GUARDRAIL. Of the re-recommending turns, how many still name the move. Must stay at 100%.

        The whole point of the turn is that the student has not yet played the move we want. A
        shortening instruction that drops the move name would leave the student with a nudge and no
        subject, which is worse than the repetition it replaced.
        """
        if not self.repeat_rec:
            return None
        return 100.0 * self.repeat_rec_names_move / self.repeat_rec

    @property
    def repeat_rec_has_lesson_rate(self) -> float | None:
        """GUARDRAIL. Of the re-recommending turns, how many still close on a composed lesson.

        Separate from the move name because they can fail independently: an escalation that becomes
        "Still there. Nxc7+." keeps the move and loses the teaching. Recorded so a fall shows up as
        a cost rather than as brevity.
        """
        if not self.repeat_rec:
            return None
        return 100.0 * self.repeat_rec_has_lesson / self.repeat_rec

    @property
    def words_per_turn(self) -> float:
        return 0.0 if not self.spoken else self.words / self.spoken

    @property
    def lesson_concentration(self) -> float | None:
        """Share of COMPOSED lessons that are the single most-composed one. Lower is better.

        ``None``, not zero, when nothing was composed. Reporting 0% for the pre-v30 era would
        claim perfect variety where the truth is that the question does not apply — every turn
        then was an open ask and the model chose its own topic. A metric that reads "excellent"
        when it cannot see anything is the instrument error this file keeps recording.

        Denominator is composed turns rather than spoken ones, because that is the population
        the measurement can actually see. ``lesson_open`` is the blind spot and is reported
        alongside so it cannot be forgotten.
        """
        if not self.lesson_composed or not self.lessons:
            return None
        return 100.0 * self.lessons.most_common(1)[0][1] / self.lesson_composed


def measure(path: Path) -> Metrics:
    data = json.loads(path.read_text(encoding="utf-8"))
    turns = [t for t in data.get("turns", []) if isinstance(t.get("ply"), int)]
    m = Metrics(name=path.parent.name.replace("coach_review_", ""))
    m.plies = len(turns)
    # Moves already recommended on an earlier SPOKEN turn of this game. Walked in ply order, not
    # file order, so a transcript storing curated positions after the game still keys correctly.
    already_recommended: set[str] = set()

    for t in sorted(turns, key=lambda x: x["ply"]):
        text = (t.get("coach_feedback") or "").strip()
        if not text:
            continue
        m.spoken += 1
        m.words += len(text.split())
        low = text.lower()

        fen = t.get("fen_before") or ""
        played = ""
        if fen:
            try:
                played = chess.Board(fen).parse_san(t.get("student_move_san") or "").uci()
            except Exception:
                played = ""
        if fen:
            try:
                vs = check_text_fidelity(text, fen, played_uci=played)
            except Exception:
                vs = []
            if vs:
                m.turns_with_violation += 1
            m.violations += len(vs)
            m.gating += len(gating_violations(vs))
            m.kinds.update(v.kind for v in vs)

        # Does the turn account for the failure, or only report it? Two questions, not one:
        # did WE compose a cause, and did it reach the student. Anchored on the squares the
        # composed cause names, so a model that paraphrases scores the same as one that echoes.
        cause_sq = _cause_squares(t.get("prompt") or "")
        if cause_sq is not None:
            m.cause_given += 1
            if cause_sq:  # a cause with no square is given but not scorable
                m.cause_anchorable += 1
                if _voices_the_cause(text, cause_sq):
                    m.cause_voiced += 1
        # Is the cause about something the opponent can actually do anything about? See
        # `cause_irrelevant_rate`. Separate from voicing: a cause can be composed, faithfully
        # voiced, and still be about a piece nobody is attacking.
        own = _cause_own_piece_square(t.get("prompt") or "")
        if own and fen and t["ply"] < 1000:
            m.cause_own_piece += 1
            if not _square_is_contested(fen, t.get("student_move_san") or "", own):
                m.cause_irrelevant += 1
            # And the check that can disagree with the detector: did the threat arrive?
            if _threat_materialises(turns, t, own):
                m.cause_materialised += 1
        if _mind_reads(low):
            m.mind_reading += 1
        if any(p in low for p in MAGNITUDE):
            m.magnitude += 1

        # Lesson concentration, measured from what we COMPOSED rather than from cue words in
        # the response. High means one idea is being taught over and over.
        state, lesson = _composed_lesson(t.get("prompt") or "")
        if lesson:
            m.lesson_composed += 1
            m.lessons[lesson] += 1
        elif state == "open":
            m.lesson_open += 1
        else:
            m.lesson_silent += 1

        # Cross-turn repetition: are we recommending a move we already recommended? Counted on
        # curated positions too — they are standalone so a move can never repeat there, but
        # excluding them would make this denominator disagree with `spoken`.
        best = (t.get("best_move_san") or "").strip()
        if best:
            if best in already_recommended:
                m.repeat_rec += 1
                m.repeat_rec_words += len(text.split())
                if best in text:
                    m.repeat_rec_names_move += 1
                if lesson:
                    m.repeat_rec_has_lesson += 1
            already_recommended.add(best)

    return m


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv[1:]]
    if not paths:
        print(__doc__)
        return 2
    rows = [measure(p) for p in paths if p.exists()]
    if not rows:
        print("no transcripts found")
        return 1

    print(
        f"{'run':<8}{'plies':>6}{'spoke':>6}{'clean%':>8}{'bad turns':>10}{'gating':>8}"
        f"{'cause-giv%':>11}{'cause-voi%':>11}{'mind-rd':>8}{'magn':>6}{'w/turn':>8}"
        f"{'lesson-conc%':>13}{'open':>6}"
    )
    for m in rows:
        conc = m.lesson_concentration
        conc_s = "n/a" if conc is None else f"{conc:.0f}%"
        print(
            f"{m.name:<8}{m.plies:>6}{m.spoken:>6}{m.clean_rate:>7.0f}%{m.turns_with_violation:>10}"
            f"{m.gating:>8}{m.cause_given_rate:>10.0f}%{m.cause_voiced_rate:>10.0f}%"
            f"{m.mind_reading:>8}{m.magnitude:>6}"
            f"{m.words_per_turn:>8.0f}{conc_s:>13}{m.lesson_open:>6}"
        )
    print()
    print("clean%      turns with NOTHING the board contradicts (higher is better) — the")
    print("            one that decides whether this is safe for a 1200")
    print("gating      violations severe enough to block a response")
    print("cause-giv%  spoken turns WE handed a composed cause — ours to fix, not the model's")
    print("cause-voi%  of those, how many reached the student. Anchored on the squares the")
    print("            composed cause names, so it survives a change of model; the phrase-")
    print("            matched version it replaces was really a compliance score (row 137)")
    print("mind-rd     turns inventing the student's intent")
    print("magn        turns leaking an evaluation number (must stay 0)")
    print("lesson-conc% share of the lessons WE composed that are the same single lesson (lower")
    print("             is better). n/a means nothing was composed, which is not the same as")
    print("             perfect variety — see `open`")
    print("open        turns where we asked for a takeaway and named no lesson, so the MODEL")
    print("            chose the topic. The blind spot in lesson-conc%")
    if len(rows) > 1:
        first, last = rows[0], rows[-1]
        print()
        print(
            f"trend {first.name} -> {last.name}:  clean {first.clean_rate:.0f}% -> {last.clean_rate:.0f}%"
            f"   cause given {first.cause_given_rate:.0f}% -> {last.cause_given_rate:.0f}%"
            f"   words {first.words_per_turn:.0f} -> {last.words_per_turn:.0f}"
        )

    worst = [m for m in rows if m.magnitude]
    if worst:
        print(f"\nWARNING: evaluation numbers reached the student in: {', '.join(m.name for m in worst)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
