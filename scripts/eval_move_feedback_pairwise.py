#!/usr/bin/env python3
"""Pairwise A/B of pedagogy guidance on the MOVE-FEEDBACK path.

This is the coaching moment the position-explanation benchmark never tested:
feedback on the move a student just played. For each (position, student-move)
scenario it asks the engine for the comparison ground truth, builds the
move-feedback coaching prompt with guidance OFF and ON, generates both with the
model under test, and has the judge pick which is the better teaching feedback.
Reports a win-rate + two-sided sign test (low-noise change detection).

Needs the model-under-test endpoint (for generation) AND a judge (kiro-cli or
an OpenAI-compatible endpoint). The engine runs locally.

Usage:
    python scripts/eval_move_feedback_pairwise.py \
        --model gemma4:12b-it-qat --base-url http://localhost:11435 \
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
from chess_coach.eval import (  # noqa: E402
    default_move_feedback_path,
    load_move_feedback_scenarios,
    render_pairwise,
    summarize_pairwise,
)
from chess_coach.eval.judge import pairwise_compare_move  # noqa: E402
from chess_coach.llm import create_provider  # noqa: E402
from chess_coach.llm.ollama import OllamaProvider  # noqa: E402
from chess_coach.pedagogy.guard import guard_entries  # noqa: E402
from chess_coach.pedagogy.resource import (  # noqa: E402
    KnowledgeResource,
    PedagogyError,
    default_resource_path,
    load_resource,
)
from chess_coach.pedagogy.selector import guidance_for_position  # noqa: E402
from chess_coach.prompts import build_rich_move_evaluation_prompt  # noqa: E402


def _build_engine(engine_cfg: dict, coaching_timeout: float) -> CoachingEngine:  # type: ignore[type-arg]
    path = _resolve_engine_path(engine_cfg["path"])
    args = [a for a in engine_cfg.get("args", []) if a != "--xboard"]
    if "--uci" not in args:
        args = ["--uci", *args]
    return CoachingEngine(path=path, args=args, coaching_timeout=coaching_timeout, ping_timeout=5.0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pairwise A/B of guidance on the move-feedback path")
    parser.add_argument("--model", required=True, help="Model under test (generates the coaching)")
    parser.add_argument("--base-url", default="http://localhost:11435")
    parser.add_argument("--benchmark", default=None, help="Path to move_feedback.yaml")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--engine-timeout", type=float, default=120.0)
    parser.add_argument("--depth", type=int, default=None)
    parser.add_argument("--multipv", type=int, default=3)
    parser.add_argument("--guidance-max", type=int, default=3)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", default="output/eval_move_feedback_pairwise")
    parser.add_argument("--judge-model", required=True)
    parser.add_argument("--judge-provider", default="cli")
    parser.add_argument("--judge-base-url", default="http://localhost:11434")
    parser.add_argument("--judge-command", default=None)
    parser.add_argument("--judge-api-key", default=os.environ.get("CHESS_COACH_JUDGE_KEY", ""))
    args = parser.parse_args()

    bench_path = Path(args.benchmark) if args.benchmark else default_move_feedback_path()
    scenarios = load_move_feedback_scenarios(bench_path)
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

    model = OllamaProvider(model=args.model, base_url=args.base_url, timeout=300.0)

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

    # Guarded pedagogy resource for guidance selection (ON condition).
    try:
        resource = load_resource(default_resource_path())
    except PedagogyError as e:
        engine.stop()
        print(f"FATAL: Knowledge_Resource unavailable: {e}")
        sys.exit(1)
    admitted, _ = guard_entries(resource.entries, engine=None)
    resource = KnowledgeResource(
        entries=tuple(admitted),
        feature_vocab=resource.feature_vocab,
        eco_vocab=resource.eco_vocab,
        levels=resource.levels,
    )

    reachable, model_found = model.check_status()
    if not reachable:
        engine.stop()
        print(f"FATAL: endpoint unreachable at {args.base_url} — is the SSH tunnel up?")
        sys.exit(1)
    if not model_found:
        engine.stop()
        print(f"FATAL: tunnel up but model {args.model} is not loaded at {args.base_url}")
        sys.exit(1)

    rng = random.Random(args.seed)
    winners: list[str] = []
    records: list[dict[str, object]] = []
    print(f"Move-feedback pairwise: {args.model}, guidance off vs on (max {args.guidance_max})\n")
    try:
        for sc in scenarios:
            print(f"  {sc.id} ({sc.move})...", end=" ", flush=True)
            try:
                comparison = engine.get_comparison_report(sc.fen, sc.move, depth=depth)
                pos_report = engine.get_position_report(sc.fen, multipv=args.multipv, depth=depth)
            except Exception as e:
                print(f"ENGINE SKIP: {e}")
                continue
            guidance = guidance_for_position(resource, pos_report, sc.level, args.guidance_max)
            prompt_off = build_rich_move_evaluation_prompt(comparison, level=sc.level)
            prompt_on = build_rich_move_evaluation_prompt(comparison, level=sc.level, guidance=guidance)
            try:
                resp_off = model.generate(prompt_off, max_tokens=512, temperature=args.temperature)
                resp_on = model.generate(prompt_on, max_tokens=512, temperature=args.temperature)
            except Exception as e:
                print(f"GEN ERROR: {e}")
                continue
            try:
                res = pairwise_compare_move(judge, "off", resp_off, "on", resp_on, comparison, sc.level, rng=rng)
            except Exception as e:
                print(f"JUDGE ERROR (skipped): {e}")
                continue
            winners.append(res.winner)
            records.append(
                {
                    "id": sc.id,
                    "move": sc.move,
                    "classification": comparison.classification,
                    "winner": res.winner,
                    "first_shown": res.first_shown,
                    "reason": res.reason,
                }
            )
            print(f"{res.winner} ({comparison.classification})")
    finally:
        engine.stop()

    if not winners:
        print("\nNo comparisons produced — nothing to summarize.")
        sys.exit(1)

    summary = summarize_pairwise(winners, "off", "on")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "pairwise.json").write_text(
        json.dumps(
            {
                "model": args.model,
                "judge_model": args.judge_model,
                "guidance_max": args.guidance_max,
                "seed": args.seed,
                "path": "move_feedback",
                "summary": {
                    "n": summary.n,
                    "wins_off": summary.wins_a,
                    "wins_on": summary.wins_b,
                    "ties": summary.ties,
                    "on_win_rate": summary.win_rate_b,
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
