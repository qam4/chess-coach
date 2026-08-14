"""Re-judge a SAVED report-card transcript — no coach, no engine, no tunnel.

Why this exists: the coach's output and the judge's ASK are two independent
variables, and we kept changing them together. Re-judging a byte-identical
transcript isolates the ask. That experiment has already paid for itself once —
re-judging v21 with a corrected stats block turned its headline weakness into its
second strength, proving the complaint was about our labelling and not the coach.

Use it to compare rubric versions on the same game:

    python scripts/eval_coach_rejudge.py \
        --transcript output/coach_review_v26/transcript.json \
        --rubric v2 --out output/coach_review_v26_rubric_v2

Or both asks back to back:

    python scripts/eval_coach_rejudge.py \
        --transcript output/coach_review_v26/transcript.json --rubric v1,v2 \
        --out output/rejudge_v26

The judge defaults to claude-opus-5 and the command is derived from the model, so
the two cannot silently disagree.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chess_coach.eval.coach_review import (  # noqa: E402
    RUBRIC_VERSIONS,
    ReviewStats,
    ReviewTurn,
    build_coach_review_prompt,
)
from chess_coach.llm import create_provider  # noqa: E402


def _load(path: Path) -> tuple[list[ReviewTurn], ReviewStats]:
    data = json.loads(path.read_text(encoding="utf-8"))
    turns = [
        ReviewTurn(
            ply=t["ply"],
            phase=t["phase"],
            fen_before=t["fen_before"],
            student_move_san=t["student_move_san"],
            best_move_san=t["best_move_san"],
            classification=t["classification"],
            eval_drop_cp=t["eval_drop_cp"],
            coach_feedback=t["coach_feedback"],
            latency_s=t.get("latency_s", 0.0),
            fidelity_kinds=t.get("fidelity_kinds", {}) or {},
            prompt=t.get("prompt", "") or "",
        )
        for t in data["turns"]
    ]
    return turns, ReviewStats.from_dict(data["stats"])


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    p = argparse.ArgumentParser(description="Re-judge a saved report-card transcript")
    p.add_argument("--transcript", required=True, help="report-card transcript.json")
    p.add_argument("--rubric", default="v2", help=f"comma-separated, from {RUBRIC_VERSIONS}")
    p.add_argument("--out", default="output/coach_rejudge")
    p.add_argument("--judge-model", default="claude-opus-5")
    p.add_argument("--judge-command", default=None, help="defaults to kiro-cli with --judge-model")
    p.add_argument("--judge-base-url", default="http://localhost:11434")
    args = p.parse_args()

    rubrics = [r.strip() for r in args.rubric.split(",") if r.strip()]
    unknown = [r for r in rubrics if r not in RUBRIC_VERSIONS]
    if unknown:
        print(f"FATAL: unknown rubric(s) {unknown}; expected from {RUBRIC_VERSIONS}")
        sys.exit(2)

    turns, stats = _load(Path(args.transcript))
    print(f"Loaded {len(turns)} coached turns from {args.transcript}")

    command = args.judge_command or f"kiro-cli chat --no-interactive --model {args.judge_model}"
    judge = create_provider(
        "cli",
        model=args.judge_model,
        base_url=args.judge_base_url,
        api_key="",
        command=shlex.split(command),
        timeout=1800.0,
    )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, rubric in enumerate(rubrics, start=1):
        prompt = build_coach_review_prompt(turns, stats, rubric=rubric)
        (out_dir / f"prompt_{rubric}.txt").write_text(prompt, encoding="utf-8")
        print(f"progress={i}/{len(rubrics)} judging with rubric {rubric} ({len(prompt)} chars)")
        t0 = time.perf_counter()
        try:
            review = judge.generate(prompt)
        except Exception as e:  # noqa: BLE001
            review = f"FAILED: {type(e).__name__}: {e}"
        dt = time.perf_counter() - t0
        dest = out_dir / f"review_{rubric}.md"
        dest.write_text(review, encoding="utf-8")
        print(f"  rubric {rubric} done in {dt:.0f}s -> {dest} ({len(review)} chars)")
    print(f"progress={len(rubrics)}/{len(rubrics)} complete")


if __name__ == "__main__":
    main()
