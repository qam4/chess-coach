#!/usr/bin/env python3
"""Record what the clause pipeline says today, for every position we have.

Why this exists. What the coach says on a turn survives nine sequential filters — path
selection, the silence gates, tier selection, effect priority, the lesson ladder, the clause
ladder, the fact budget, guidance selection, the fidelity gate. Each was added on its own to
answer a specific review finding, none was designed against the others, and the consequence
is that the output is *whatever survived* rather than what we judged worth saying.

We intend to replace that chain with generate-then-select. The risk in doing so is not that
we do not know what to build — it is that those nine filters encode measured lessons ("do not
claim king activity outside an endgame", "do not say toward the centre without a count", "do
not call a developed piece developed") and a refactor could quietly drop one. A design
document does not protect against that. This does.

So: record ``(fen, move) -> (category, clause)`` for every position in every transcript we
have. That is the golden master. After the refactor it must reproduce this file exactly,
except where we have DECIDED to differ — and every difference shows up as a diff to approve
or reject, one at a time.

It is also the first time we will see the whole behaviour at once: which of the thirteen
categories actually win, how often a clause repeats, which positions yield nothing.

Deterministic and offline. No engine, no judge, no LLM — it replays stored positions through
board geometry, so it can be re-run any time and diffed.

    python scripts/snapshot_clauses.py --out docs/clause-snapshot.tsv
    python scripts/snapshot_clauses.py --check docs/clause-snapshot.tsv   # after a change
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import chess  # noqa: E402

from chess_coach.prompts import _move_effect  # noqa: E402

#: Columns, tab-separated so a clause containing a comma stays one field.
HEADER = "source\tply\tfen\tmove_uci\trival_uci\tcategory\tclause"


def _positions() -> list[tuple[str, str]]:
    """``(source, fen)`` for every distinct position we can lay hands on.

    Two sources, and neither needs an engine. The stored transcripts are all the SAME game
    (seed 7), which is worth knowing on its own — it means every measurement in the ledger
    rests on one game — so they contribute far fewer distinct positions than their count
    suggests. The curated eval sets add positions chosen for variety.
    """
    seen: set[str] = set()
    out: list[tuple[str, str]] = []

    def _add(src: str, fen: str) -> None:
        try:
            chess.Board(fen)
        except ValueError:
            return
        key = " ".join(fen.split()[:4])  # ignore clocks
        if key in seen:
            return
        seen.add(key)
        out.append((src, fen))

    for path in sorted(glob.glob("output/coach_review_*/transcript.json")):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            continue
        for turn in data.get("turns", []):
            if turn.get("fen_before"):
                _add("game", turn["fen_before"])

    for name in ("positions", "move_feedback", "move_feedback_material"):
        f = Path("data/eval") / f"{name}.yaml"
        if not f.exists():
            continue
        try:
            import yaml

            loaded = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        items = loaded if isinstance(loaded, list) else (loaded.get("positions") or loaded.get("scenarios") or [])
        for item in items:
            if isinstance(item, dict) and item.get("fen"):
                _add(name, item["fen"])
    return out


def _rows() -> list[tuple[str, ...]]:
    """One row per (position, legal move) pair.

    EVERY legal move, not just the ones played. The thing under snapshot is a function whose
    input is an arbitrary legal move — the engine's pick or the student's — so covering all of
    them is what actually exercises the thirteen branches. Restricting it to played moves gave
    88 rows and left most branches untouched, which is not a safety net.

    Each move is recorded twice: once described against a rival move (the real calling
    convention when explaining the engine's choice, where ``rival_uci`` suppresses claims that
    do not distinguish the two) and once on its own.
    """
    out: list[tuple[str, ...]] = []
    for src, fen in _positions():
        board = chess.Board(fen)
        legal = sorted(m.uci() for m in board.legal_moves)
        # A stable rival for the paired form: the first legal move that is not the subject.
        for move_uci in legal:
            rival = next((m for m in legal if m != move_uci), "")
            for rival_uci in (rival, ""):
                possessive = "their " if rival_uci else "your "
                try:
                    category, clause = _move_effect(board, move_uci, target_possessive=possessive, rival_uci=rival_uci)
                except Exception as exc:  # a crash is behaviour worth snapshotting too
                    category, clause = "ERROR", f"{type(exc).__name__}: {exc}"
                out.append(
                    (
                        src,
                        "",
                        fen,
                        move_uci,
                        rival_uci,
                        category or "-",
                        clause.strip().lstrip(",").strip() or "-",
                    )
                )
    return out


def _san_to_uci(board: chess.Board, san: str | None) -> str:
    if not san:
        return ""
    try:
        return board.parse_san(san).uci()
    except Exception:
        return ""


def _render(rows: list[tuple[str, ...]]) -> str:
    body = "\n".join("\t".join(r) for r in rows)
    return f"{HEADER}\n{body}\n"


def _summarise(rows: list[tuple[str, ...]]) -> str:
    cats = collections.Counter(r[5] for r in rows)
    clauses = collections.Counter(r[6] for r in rows if r[6] != "-")
    lines = [
        f"positions snapshotted: {len(rows)}",
        f"distinct clauses: {len(clauses)}",
        "",
        "which category wins, across every position we have:",
    ]
    for cat, count in cats.most_common():
        lines.append(f"  {cat:<16} {count:>5}  ({100 * count // max(1, len(rows))}%)")
    lines.append("")
    lines.append("most-repeated clauses (the variety problem, counted):")
    for clause, count in clauses.most_common(8):
        lines.append(f"  {count:>4}x  {clause[:88]}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Snapshot the clause pipeline's current behaviour")
    ap.add_argument("--out", default="docs/clause-snapshot.tsv", help="where to write the snapshot")
    ap.add_argument("--check", default=None, help="compare against an existing snapshot instead of writing")
    ap.add_argument("--summary-only", action="store_true")
    args = ap.parse_args()

    rows = _rows()
    if not rows:
        print("No transcripts found under output/coach_review_*/ — nothing to snapshot.")
        return 1
    rendered = _render(rows)

    if args.check:
        existing = Path(args.check)
        if not existing.exists():
            print(f"{existing} does not exist — run without --check first.")
            return 1
        old = existing.read_text(encoding="utf-8").splitlines()
        new = rendered.splitlines()
        old_map = {tuple(line.split("\t")[:5]): line for line in old[1:]}
        new_map = {tuple(line.split("\t")[:5]): line for line in new[1:]}
        changed = [k for k in new_map.keys() & old_map.keys() if new_map[k] != old_map[k]]
        added = new_map.keys() - old_map.keys()
        removed = old_map.keys() - new_map.keys()
        if not (changed or added or removed):
            print(f"No change. {len(rows)} positions produce identical clauses.")
            return 0
        print(f"CHANGED {len(changed)}   ADDED {len(added)}   REMOVED {len(removed)}\n")
        for k in sorted(changed)[:40]:
            was = old_map[k].split("\t")
            now = new_map[k].split("\t")
            print(f"  {k[0]} ply {k[1]} {k[3]}")
            print(f"    was: [{was[5]}] {was[6][:84]}")
            print(f"    now: [{now[5]}] {now[6][:84]}")
        if len(changed) > 40:
            print(f"  ... and {len(changed) - 40} more")
        print("\nEvery line above is a behaviour change. Approve each one deliberately, or fix it.")
        return 1

    if not args.summary_only:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")
        print(f"Wrote {out} ({len(rows)} positions)\n")
    print(_summarise(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
