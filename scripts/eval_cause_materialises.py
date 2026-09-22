"""Did the threat a cause warned about ever actually arrive?

This is the check that can come out AGAINST the cause detector, and it exists because the first
measure of that detector could not. That one asked "can the opponent attack this square now or in
one move" — the same predicate the fix applies — so its before/after was arithmetic, not evidence.

This asks a different question, of the game as it was actually played: after the turn where we told
the student a piece had lost its defender, did the opponent EVER attack that square, and how many
plies later? It shares nothing with the detector's logic. It uses the continuation.

Two directions, and the second is the one that matters:

- The causes the detector DROPS should mostly be squares nobody ever attacks. Easy to satisfy.
- The causes it KEEPS should mostly be squares the opponent really does attack, and soon. If most
  kept causes describe threats that never arrive, the detector is too generous and the warning is
  noise — which no amount of board-anchored checking at the moment of the turn could reveal.

    python scripts/eval_cause_materialises.py output/coach_review_v55_seed*/transcript.json
    python scripts/eval_cause_materialises.py --glob "coach_review_v55_seed*"

LIMITS, stated because the sample is small and the resolution is coarse:

- One game gives a handful of these causes, so five games is a dozen.
- The continuation is the line the opponent actually chose, not the best one available. A square
  nobody attacked may still have been a real weakness they failed to exploit.
- A transcript records a position only for the STUDENT's turns, so the opponent's replies fall
  between snapshots. A piece that is attacked and captured inside one gap never appears attacked in
  any recorded position, and this UNDERCOUNTS it. The alternative — treating a piece that vanishes
  as proof the threat arrived — would count our own voluntary retreats as threats, which is worse.

So a low rate is a reason to look, not proof the cause was wrong.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

import chess

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_hard_metrics import _cause_own_piece_square, _threat_materialises  # noqa: E402


@dataclass(frozen=True)
class CauseOutcome:
    run: str
    ply: int
    square: str
    plies_remaining: int
    attacked_at: int | None
    emptied: bool

    @property
    def materialised(self) -> bool:
        return self.attacked_at is not None

    @property
    def delay(self) -> int | None:
        return None if self.attacked_at is None else self.attacked_at - self.ply


def outcomes(transcript: Path) -> list[CauseOutcome]:
    """One entry per turn whose composed cause says OUR piece lost its defender."""
    data = json.loads(transcript.read_text(encoding="utf-8"))
    # Curated positions (ply >= 1000) are standalone puzzles with no continuation, so a cause on
    # one of them can never materialise. Excluded rather than counted as a failure.
    turns = sorted(
        (t for t in data.get("turns", []) if isinstance(t.get("ply"), int) and t["ply"] < 1000),
        key=lambda t: t["ply"],
    )
    out: list[CauseOutcome] = []
    for t in turns:
        square = _cause_own_piece_square(t.get("prompt") or "")
        if not square:
            continue
        try:
            board = chess.Board(t["fen_before"])
        except (ValueError, TypeError):
            continue
        us = board.turn
        sq = chess.parse_square(square)
        later = [x for x in turns if x["ply"] > t["ply"]]
        # The verdict comes from the SHARED helper, so this report and the tracked
        # `cause_materialised_rate` cannot disagree. They did, briefly, by 6 points: one stopped
        # scanning when the square emptied and the other did not, which is the two-callers-one-check
        # trap this repo keeps falling into. The ply and delay below are for reading; the boolean is
        # the helper's.
        materialised = _threat_materialises(turns, t, square)
        attacked_at: int | None = None
        emptied = False
        for x in later:
            try:
                b = chess.Board(x["fen_before"])
            except (ValueError, TypeError):
                continue
            piece = b.piece_at(sq)
            if piece is None or piece.color != us:
                emptied = True
                break
            if attacked_at is None and b.attackers(not us, sq):
                attacked_at = x["ply"]
                break
        if not materialised:
            attacked_at = None
        out.append(
            CauseOutcome(
                run=transcript.parent.name.replace("coach_review_", ""),
                ply=t["ply"],
                square=square,
                plies_remaining=len(later),
                attacked_at=attacked_at,
                emptied=emptied,
            )
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("transcripts", nargs="*", help="transcript.json paths")
    ap.add_argument("--glob", default="", help="directory pattern under output/, e.g. 'coach_review_v55_seed*'")
    args = ap.parse_args()

    paths = [Path(p) for p in args.transcripts]
    if args.glob:
        paths += sorted(Path("output").glob(f"{args.glob}/transcript.json"))
    paths = [p for p in paths if p.exists()]
    if not paths:
        print("no transcripts given")
        return 1

    rows: list[CauseOutcome] = []
    for p in paths:
        rows.extend(outcomes(p))
    if not rows:
        print(f"no own-piece causes found in {len(paths)} transcript(s)")
        return 1

    print(f"{'run':22} {'ply':>5} {'sq':3} {'plies left':>10} {'attacked at':>12} {'delay':>6} {'emptied':>8}")
    for r in rows:
        at = "never" if r.attacked_at is None else str(r.attacked_at)
        delay = "" if r.delay is None else str(r.delay)
        print(f"{r.run:22} {r.ply:5} {r.square:3} {r.plies_remaining:10} {at:>12} {delay:>6} {str(r.emptied):>8}")

    hit = [r for r in rows if r.materialised]
    delays = [r.delay for r in hit if r.delay is not None]
    print()
    print(f"causes examined                 : {len(rows)}")
    print(f"  threat ever arrived           : {len(hit)}  ({100 * len(hit) / len(rows):.0f}%)")
    print(f"  never                         : {len(rows) - len(hit)}")
    if delays:
        print(
            f"  plies until it arrived        : median {statistics.median(delays):.0f}, "
            f"min {min(delays)}, max {max(delays)}"
        )
    print(f"  square eventually emptied     : {sum(1 for r in rows if r.emptied)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
