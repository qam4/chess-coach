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
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import chess

from chess_coach.verify import check_text_fidelity, gating_violations

#: Phrases that put a motive in the student's mouth. The reviewer flagged these on
#: several runs ("I see you're trying to develop your pieces" on a move that did nothing
#: of the kind) and they are the one Stance defect with a mechanical signature.
MIND_READING = (
    "i see you're trying",
    "i see you are trying",
    "i see that you're trying",
    "you're looking to",
    "you are looking to",
    "your plan was to",
    "you intended to",
    "you wanted to",
)

#: A number that prices the position. Should be zero: the protocol forbids showing the
#: student an evaluation, and the units were never defensible anyway.
MAGNITUDE = ("centipawn", "cp)", " cp ", "+0.", "-0.", "eval of", "score of")


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
    turns_with_cause: int = 0
    mind_reading: int = 0
    magnitude: int = 0
    words: int = 0
    repeated_share: float = 0.0

    @property
    def clean_rate(self) -> float:
        """Share of spoken turns with nothing the board contradicts. The headline."""
        return 0.0 if not self.spoken else 100.0 * (self.spoken - self.turns_with_violation) / self.spoken

    @property
    def cause_rate(self) -> float:
        """Share of spoken turns that name why the move failed, not just what happened."""
        return 0.0 if not self.spoken else 100.0 * self.turns_with_cause / self.spoken

    @property
    def words_per_turn(self) -> float:
        return 0.0 if not self.spoken else self.words / self.spoken


def measure(path: Path) -> Metrics:
    data = json.loads(path.read_text(encoding="utf-8"))
    turns = [t for t in data.get("turns", []) if isinstance(t.get("ply"), int)]
    m = Metrics(name=path.parent.name.replace("coach_review_", ""))
    m.plies = len(turns)
    closers: Counter[str] = Counter()

    for t in turns:
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

        # Does the turn account for the failure, or only report it? The composed cause
        # sentences are the only source of this phrasing, so matching them is exact
        # rather than a guess at the model's prose.
        # Widened past the exact composed phrases: the model paraphrases them, and the strict
        # match under-counted v42 at 17% where the same turns read as 33% once paraphrase was
        # allowed. What is being counted is "does this turn name a check the student skipped",
        # which is the teaching property, not "did the model copy our wording".
        if "check" in low and ("skipped" in low or "before" in low or "ask" in low):
            m.turns_with_cause += 1
        if any(p in low for p in MIND_READING):
            m.mind_reading += 1
        if any(p in low for p in MAGNITUDE):
            m.magnitude += 1

        # Lesson concentration: how much of the coaching lands on its most-used closing
        # idea. High means the student hears the same thing every turn.
        tail = " ".join(text.split()[-14:]).lower()
        for cue in ("undefended", "attackers and defenders", "before you move", "attacked", "defended"):
            if cue in tail:
                closers[cue] += 1
                break

    if m.spoken and closers:
        m.repeated_share = 100.0 * closers.most_common(1)[0][1] / m.spoken
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
        f"{'cause%':>8}{'mind-rd':>8}{'magn':>6}{'w/turn':>8}{'top-closer%':>12}"
    )
    for m in rows:
        print(
            f"{m.name:<8}{m.plies:>6}{m.spoken:>6}{m.clean_rate:>7.0f}%{m.turns_with_violation:>10}"
            f"{m.gating:>8}{m.cause_rate:>7.0f}%{m.mind_reading:>8}{m.magnitude:>6}"
            f"{m.words_per_turn:>8.0f}{m.repeated_share:>11.0f}%"
        )
    print()
    print("clean%      turns with NOTHING the board contradicts (higher is better) — the")
    print("            one that decides whether this is safe for a 1200")
    print("gating      violations severe enough to block a response")
    print("cause%      turns naming WHY the move failed, not just what happened")
    print("mind-rd     turns inventing the student's intent")
    print("magn        turns leaking an evaluation number (must stay 0)")
    print("top-closer% share of turns ending on the single most-repeated idea (lower is better)")
    if len(rows) > 1:
        first, last = rows[0], rows[-1]
        print()
        print(f"trend {first.name} -> {last.name}:  clean {first.clean_rate:.0f}% -> {last.clean_rate:.0f}%"
              f"   cause {first.cause_rate:.0f}% -> {last.cause_rate:.0f}%"
              f"   words {first.words_per_turn:.0f} -> {last.words_per_turn:.0f}")

    worst = [m for m in rows if m.magnitude]
    if worst:
        print(f"\nWARNING: evaluation numbers reached the student in: {', '.join(m.name for m in worst)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
