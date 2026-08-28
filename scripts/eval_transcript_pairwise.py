#!/usr/bin/env python3
"""Blind A/B of two report-card transcripts, turn by turn.

BACKLOG item 2. Why it exists: the judge's absolute category scores turned out not to be a
measurement at all. The SAME v42 transcript, judged three times, returned overall 5.5, 5.0
and 2.0, and its fidelity gate fired on one of the three — so the v37-v42 score sequence is
indistinguishable from re-rolling dice, and nine runs went into chasing it (ledger rows
88-93).

Pairwise judging is the standard answer: asking "which of these two is better" removes the
absolute-anchoring that makes small deltas invisible, and the repo already has the
machinery for it — order randomisation to cancel position bias, majority voting over
repeats to denoise a single comparison, and an exact sign test so a win count comes with a
p-value instead of a vibe. What was missing is a way to point it at two transcripts we have
already produced, rather than generating both sides live for one specific A/B.

**Validate before trusting.** Being better than a broken instrument is not the same as being
a good one, and the whole lesson of rows 88-93 is that we adopted a metric without checking
it. So run this twice on the same pair and compare the verdicts first. Identical inputs
should give the same answer; if they do not, the disagreement rate is the noise floor and no
result smaller than that means anything.

    python scripts/eval_transcript_pairwise.py \
        --a output/coach_review_v39/transcript.json \
        --b output/coach_review_v42/transcript.json \
        --judge-repeats 3 --out output/pairwise_v39_v42

Only plies where BOTH transcripts spoke are compared: a turn one version stayed silent on
has nothing to compare, and silence discipline is measured separately by
``eval_hard_metrics.py``.
"""

from __future__ import annotations

import argparse
import json
import random
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import chess  # noqa: E402

from chess_coach.eval.aggregate import render_pairwise, summarize_pairwise  # noqa: E402
from chess_coach.eval.judge import majority_winner, pairwise_compare_move  # noqa: E402
from chess_coach.llm import create_provider  # noqa: E402
from chess_coach.models import ComparisonReport  # noqa: E402


def _spoken(path: Path) -> dict[int, dict]:
    """Plies this transcript actually coached, keyed by ply."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        t["ply"]: t
        for t in data.get("turns", [])
        if isinstance(t.get("ply"), int) and (t.get("coach_feedback") or "").strip()
    }


def _report_for(turn: dict) -> ComparisonReport | None:
    """A minimal ComparisonReport for the judge's context.

    The judge prompt uses it to show the position and the move under discussion. Only the
    fields it renders need to be right; anything we cannot recover from a transcript is left
    at a neutral value rather than guessed at.
    """
    fen = turn.get("fen_before") or ""
    if not fen:
        return None
    try:
        board = chess.Board(fen)
        played = board.parse_san(turn.get("student_move_san") or "").uci()
    except Exception:
        return None
    best = played
    if turn.get("best_move_san"):
        try:
            best = board.parse_san(turn["best_move_san"]).uci()
        except Exception:
            best = played
    return ComparisonReport(
        fen=fen,
        user_move=played,
        user_eval_cp=0,
        best_move=best,
        best_eval_cp=0,
        eval_drop_cp=int(turn.get("eval_drop_cp") or 0),
        classification=str(turn.get("classification") or "unknown"),
        nag="",
        best_move_idea="",
        refutation_line=None,
        missed_tactics=[],
        top_lines=[],
        critical_moment=False,
        critical_reason=None,
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Blind pairwise A/B of two report-card transcripts")
    p.add_argument("--a", required=True, help="transcript.json for side A (the baseline)")
    p.add_argument("--b", required=True, help="transcript.json for side B (the candidate)")
    p.add_argument("--label-a", default=None)
    p.add_argument("--label-b", default=None)
    p.add_argument("--level", default="intermediate")
    p.add_argument(
        "--judge-repeats",
        type=int,
        default=3,
        help="Judge each pair this many times and take the majority. The transcripts are "
        "fixed, so repeats sample the JUDGE's variance rather than new responses — which "
        "is exactly the variance that made the absolute scores useless.",
    )
    p.add_argument("--seed", type=int, default=0, help="order-randomisation seed")
    p.add_argument("--judge-model", default="claude-opus-5")
    p.add_argument("--judge-provider", default="cli")
    p.add_argument("--judge-command", default=None)
    p.add_argument("--judge-base-url", default="http://localhost:11434")
    p.add_argument("--out", default="output/transcript_pairwise")
    args = p.parse_args()

    path_a, path_b = Path(args.a), Path(args.b)
    label_a = args.label_a or path_a.parent.name.replace("coach_review_", "")
    label_b = args.label_b or path_b.parent.name.replace("coach_review_", "")
    if label_a == label_b:
        label_a, label_b = f"{label_a}-A", f"{label_b}-B"

    turns_a, turns_b = _spoken(path_a), _spoken(path_b)
    shared = sorted(set(turns_a) & set(turns_b))
    if not shared:
        print("No ply was coached by both transcripts — nothing to compare.")
        return 1
    print(f"{label_a}: {len(turns_a)} spoken | {label_b}: {len(turns_b)} spoken | comparable: {len(shared)}")
    print(f"judge={args.judge_model} repeats={args.judge_repeats} seed={args.seed}\n")

    command = args.judge_command or f"kiro-cli chat --no-interactive --model {args.judge_model}"
    judge = create_provider(
        args.judge_provider,
        model=args.judge_model,
        base_url=args.judge_base_url,
        command=shlex.split(command),
    )

    rng = random.Random(args.seed)
    winners: list[str] = []
    records: list[dict] = []
    for ply in shared:
        report = _report_for(turns_b[ply]) or _report_for(turns_a[ply])
        if report is None:
            print(f"  ply {ply}: SKIP (no usable position)")
            continue
        votes: list[str] = []
        reason = ""
        try:
            for _ in range(max(1, args.judge_repeats)):
                res = pairwise_compare_move(
                    judge,
                    label_a,
                    turns_a[ply]["coach_feedback"],
                    label_b,
                    turns_b[ply]["coach_feedback"],
                    report,
                    args.level,
                    rng=rng,
                )
                votes.append(res.winner)
                reason = res.reason or reason
        except Exception as e:
            print(f"  ply {ply}: JUDGE ERROR {e}")
            continue
        winner, tally = majority_winner(votes, label_a, label_b)
        winners.append(winner)
        unanimous = "" if len(set(votes)) == 1 else "  (split)"
        print(f"  ply {ply}: {winner}{unanimous}  votes={tally}")
        records.append({"ply": ply, "winner": winner, "votes": tally, "reason": reason})

    if not winners:
        print("\nNo decisive comparisons.")
        return 1
    summary = summarize_pairwise(winners, label_a, label_b)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "pairwise.json").write_text(
        json.dumps(
            {
                "a": str(path_a),
                "b": str(path_b),
                "judge_model": args.judge_model,
                "judge_repeats": args.judge_repeats,
                "seed": args.seed,
                "summary": {
                    "n": summary.n,
                    f"wins_{label_a}": summary.wins_a,
                    f"wins_{label_b}": summary.wins_b,
                    "ties": summary.ties,
                    "win_rate_b": summary.win_rate_b,
                    "p_value": summary.p_value,
                    "significant": summary.significant,
                    "verdict": summary.verdict,
                },
                "comparisons": records,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    split = sum(
        1 for r in records if len(set(r["votes"].values())) > 1 or max(r["votes"].values()) < args.judge_repeats
    )
    print("\n" + render_pairwise(summary))
    print(f"\nper-pair judge disagreement: {split}/{len(records)} pairs were not unanimous")
    print(f"Results: {out / 'pairwise.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
