"""Does our composed clause name the biggest thing the recommended move does?

The architecture review's lead finding, turned into a count. At v54 seed 23 ply 19 the engine's
move `Nxc7+` is a royal fork: it captures a pawn, gives check, and attacks an undefended ROOK on
a8, which falls next move. Our clause said "capturing their pawn on c7", and the prompt then
forbids the model from naming any square that line does not name - so the coach told a student the
point of a 583cp move was a pawn, and was structurally prevented from mentioning the rook.

Cause, read off the code rather than inferred: `prompts._move_effect` tests `board.is_capture`
FIRST and returns immediately, so the fork and check branches below it are unreachable for any
capture. A capture that is also a fork is described only as a capture.

WHAT THIS COUNTS, per turn carrying a recommendation:
  - NAMED   = the piece type our clause actually names (0 when the clause names no material)
  - BIGGEST = the largest piece type the move wins on the board: the piece it captures, or any
              UNDEFENDED enemy piece it attacks from its destination square
  - understated when BIGGEST > NAMED

ON PIECE VALUES, because this project's division of labour reserves them for the engine: this uses
only python-chess's PIECE TYPE ORDERING (pawn < knight < bishop < rook < queen), which is part of
the rules vocabulary, not a valuation. It does not add centipawns, does not decide whether a
capture is good, and does not go anywhere near the coach's mouth - it is a measurement. The proper
long-term home for "how much material does this move win" is a field from Blunder, and that is
recorded as an engine ask. Flagged here rather than left implicit.

    python scripts/eval_clause_understates.py                 # every stored run
    python scripts/eval_clause_understates.py --detail        # per-turn lines
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import chess

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chess_coach.prompts import _move_effect  # noqa: E402

#: Ordinal only. python-chess already defines PAWN=1 < KNIGHT=2 < BISHOP=3 < ROOK=4 < QUEEN=5.
_NAMES = {
    chess.PAWN: "pawn",
    chess.KNIGHT: "knight",
    chess.BISHOP: "bishop",
    chess.ROOK: "rook",
    chess.QUEEN: "queen",
}


def named_piece_type(board: chess.Board, clause: str) -> int:
    """The piece type our clause names, by reading the clause we composed ourselves.

    Reading our OWN text is safe in a way that reading the model's is not: this string is
    produced by `_move_effect`, so its vocabulary is fixed and cannot be paraphrased.
    """
    lowered = clause.lower()
    best = 0
    for piece_type, name in _NAMES.items():
        if name in lowered:
            best = max(best, piece_type)
    return best


def biggest_win(board: chess.Board, move: chess.Move) -> int:
    """The largest piece type this move wins: what it captures, or an undefended piece it hits."""
    mover = board.turn
    best = 0
    if board.is_capture(move):
        if board.is_en_passant(move):
            best = chess.PAWN
        else:
            victim = board.piece_at(move.to_square)
            if victim is not None:
                best = victim.piece_type
    after = board.copy(stack=False)
    after.push(move)
    for sq in after.attacks(move.to_square):
        piece = after.piece_at(sq)
        if piece is None or piece.color == mover or piece.piece_type == chess.KING:
            continue
        if not after.attackers(not mover, sq):
            best = max(best, piece.piece_type)
    return best


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="output")
    ap.add_argument("--detail", action="store_true", help="print every understated turn")
    args = ap.parse_args()

    per_run: dict[str, tuple[int, int]] = {}
    per_model: Counter[str] = Counter()
    per_model_total: Counter[str] = Counter()
    rows: list[str] = []
    total = understated = 0

    for path in sorted(Path(args.root).rglob("transcript.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        model = ((data.get("environment") or {}).get("llm") or {}).get("model") or "unrecorded"
        run = path.parent.name
        n = bad = 0
        for t in data.get("turns", []):
            fen, san = t.get("fen_before"), t.get("best_move_san")
            if not fen or not san:
                continue
            try:
                board = chess.Board(fen)
                move = board.parse_san(san)
            except ValueError:
                continue
            _cat, clause = _move_effect(board, move.uci(), target_possessive="their ")
            if not clause:
                continue
            n += 1
            named = named_piece_type(board, clause)
            biggest = biggest_win(board, move)
            # Only count a clause that NAMES material and names too little of it. A first version
            # counted non-material clauses too ("giving check", "adding an attacker to e5") whenever
            # some undefended pawn happened to be attacked, and flagged 3 turns where naming the
            # pawn instead of the check would have been the worse sentence. A check is not smaller
            # than a pawn; the two are not on one scale, and pretending they are inflated the count.
            if named and biggest > named:
                bad += 1
                rows.append(
                    f"  {run:26} ply {t['ply']:5} {san:8} named={_NAMES.get(named, 'none'):7} "
                    f"biggest={_NAMES.get(biggest, 'none'):7} | {clause.strip()[:70]}"
                )
        if n:
            per_run[run] = (bad, n)
            per_model[model] += bad
            per_model_total[model] += n
            total += n
            understated += bad

    print(f"turns with a composed clause : {total}")
    print(f"clause understates the win   : {understated}  ({100 * understated / total:.1f}%)")
    print()
    print("by model (overfitting check - a measure that only fires on one model is model-shaped):")
    for model in sorted(per_model_total):
        bad, n = per_model[model], per_model_total[model]
        print(f"  {model:22} {bad:4}/{n:4}  {100 * bad / n:5.1f}%")
    print()
    worst = sorted(per_run.items(), key=lambda kv: -kv[1][0] / max(kv[1][1], 1))[:12]
    print("worst runs:")
    for run, (bad, n) in worst:
        print(f"  {run:30} {bad:3}/{n:3}  {100 * bad / n:5.1f}%")
    runs_firing = sum(1 for bad, _ in per_run.values() if bad)
    print()
    print(f"runs where it fires at least once: {runs_firing}/{len(per_run)}")
    if args.detail:
        print()
        print("every understated turn:")
        for r in rows:
            print(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
