#!/usr/bin/env python3
"""Pairwise A/B over two sets of saved eval runs (judge-only, no regeneration).

Absolute rubric scores wobble ~+/-0.14 when the judge re-scores the same text,
which swamps small teaching deltas (see BACKLOG "Eval sensitivity"). Pairwise
judging asks "which of these two is better coaching?" for the SAME position --
removing the absolute-anchoring noise -- and reports a win-rate + a two-sided
sign test. That directly answers "did this change (guidance/prompt/model) help?"

It compares the *responses already saved* in two sets of result dirs (e.g. the
gemma guidance-off runs vs the guidance-on runs), so it needs only the engine
(local, for the grounding section) and the judge -- NOT the model-under-test
endpoint/tunnel. Dirs are zipped (a[k] vs b[k]); each shared position yields one
randomized-order pairwise verdict.

Usage:
    python scripts/eval_pairwise.py \
        --a output/eval_rpt_gemma_off_1 output/eval_rpt_gemma_off_2 output/eval_rpt_gemma_off_3 \
        --b output/eval_rpt_gemma_on_1  output/eval_rpt_gemma_on_2  output/eval_rpt_gemma_on_3 \
        --label-a off --label-b on \
        --judge-provider cli --judge-model claude-sonnet-4.6 \
        --judge-command "kiro-cli chat --no-interactive --model claude-sonnet-4.6 {prompt}"
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chess_coach.cli import _resolve_engine_path, load_config  # noqa: E402
from chess_coach.engine import CoachingEngine  # noqa: E402
from chess_coach.eval import render_pairwise, summarize_pairwise  # noqa: E402
from chess_coach.eval.benchmark import default_benchmark_path, load_benchmark  # noqa: E402
from chess_coach.eval.judge import pairwise_compare  # noqa: E402
from chess_coach.llm import create_provider  # noqa: E402


def _build_engine(engine_cfg: dict, coaching_timeout: float) -> CoachingEngine:  # type: ignore[type-arg]
    path = _resolve_engine_path(engine_cfg["path"])
    args = [a for a in engine_cfg.get("args", []) if a != "--xboard"]
    if "--uci" not in args:
        args = ["--uci", *args]
    return CoachingEngine(path=path, args=args, coaching_timeout=coaching_timeout, ping_timeout=5.0)


def _responses(result_dir: str) -> dict[str, str]:
    """Map position_id -> coaching response from a run's results.json
    (skipping failed/empty generations)."""
    data = json.loads((Path(result_dir) / "results.json").read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for r in data.get("responses", []):
        if r.get("error") or not r.get("response"):
            continue
        out[r["position_id"]] = r["response"]
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Pairwise A/B over saved eval runs")
    parser.add_argument("--a", nargs="+", required=True, help="Result dirs for condition A")
    parser.add_argument("--b", nargs="+", required=True, help="Result dirs for condition B")
    parser.add_argument("--label-a", default="A")
    parser.add_argument("--label-b", default="B")
    parser.add_argument("--benchmark", default=None)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--engine-timeout", type=float, default=120.0)
    parser.add_argument("--depth", type=int, default=None)
    parser.add_argument("--multipv", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0, help="RNG seed for slot-order randomization")
    parser.add_argument("--out", default="output/eval_pairwise")
    parser.add_argument("--judge-model", required=True)
    parser.add_argument("--judge-provider", default="cli")
    parser.add_argument("--judge-base-url", default="http://localhost:11434")
    parser.add_argument("--judge-command", default=None)
    parser.add_argument("--judge-api-key", default=os.environ.get("CHESS_COACH_JUDGE_KEY", ""))
    args = parser.parse_args()

    bench_path = Path(args.benchmark) if args.benchmark else default_benchmark_path()
    positions = load_benchmark(bench_path)
    positions_by_id = {p.id: p for p in positions}

    config = load_config(args.config)
    depth = args.depth if args.depth is not None else config.get("engine", {}).get("depth")

    # Judge provider.
    judge_kwargs: dict[str, object] = {
        "model": args.judge_model,
        "base_url": args.judge_base_url,
        "api_key": args.judge_api_key,
    }
    if args.judge_provider == "cli":
        if not args.judge_command:
            print("FATAL: --judge-provider cli requires --judge-command")
            sys.exit(1)
        judge_kwargs["command"] = shlex.split(args.judge_command)
    judge = create_provider(args.judge_provider, **judge_kwargs)

    # Engine (local) for the grounding section of the pairwise prompt.
    engine = _build_engine(config["engine"], args.engine_timeout)
    try:
        engine.start()
    except Exception as e:
        print(f"FATAL: could not start engine: {e}")
        sys.exit(1)
    if not engine.coaching_available:
        engine.stop()
        print("FATAL: engine is not coaching-capable (coach ping failed).")
        sys.exit(1)

    rng = random.Random(args.seed)
    winners: list[str] = []
    records: list[dict[str, object]] = []
    try:
        reports = {}
        for pid in positions_by_id:
            try:
                reports[pid] = engine.get_position_report(positions_by_id[pid].fen, multipv=args.multipv, depth=depth)
            except Exception as e:
                print(f"  engine SKIP {pid}: {e}")

        pairs = list(zip(args.a, args.b))
        print(f"Pairwise: {args.label_a} vs {args.label_b} over {len(pairs)} dir-pair(s)\n")
        for a_dir, b_dir in pairs:
            a_resp, b_resp = _responses(a_dir), _responses(b_dir)
            shared = [pid for pid in a_resp if pid in b_resp and pid in reports]
            for pid in shared:
                pos = positions_by_id[pid]
                print(f"  judge: {pid} ({a_dir} vs {b_dir})...", end=" ", flush=True)
                try:
                    res = pairwise_compare(
                        judge,
                        args.label_a,
                        a_resp[pid],
                        args.label_b,
                        b_resp[pid],
                        reports[pid],
                        pos,
                        rng=rng,
                    )
                except Exception as e:
                    print(f"JUDGE ERROR (skipped): {e}")
                    continue
                winners.append(res.winner)
                records.append(
                    {
                        "position_id": pid,
                        "a_dir": a_dir,
                        "b_dir": b_dir,
                        "winner": res.winner,
                        "first_shown": res.first_shown,
                        "reason": res.reason,
                    }
                )
                print(res.winner)
    finally:
        engine.stop()

    if not winners:
        print("\nNo comparisons produced — nothing to summarize.")
        sys.exit(1)

    summary = summarize_pairwise(winners, args.label_a, args.label_b)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "pairwise.json").write_text(
        json.dumps(
            {
                "label_a": args.label_a,
                "label_b": args.label_b,
                "judge_model": args.judge_model,
                "seed": args.seed,
                "summary": {
                    "n": summary.n,
                    "wins_a": summary.wins_a,
                    "wins_b": summary.wins_b,
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
    print("\n" + render_pairwise(summary))
    print(f"\nResults: {out_dir / 'pairwise.json'}")


if __name__ == "__main__":
    main()
