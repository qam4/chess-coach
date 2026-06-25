#!/usr/bin/env python3
"""Model-capability profiler — producer (thin layer over the eval harness).

Point it at a model; it runs cheapest-first coaching dimension checks
(reachability → factual grounding → guidance uptake → latency), reusing the
existing eval components, then prints a per-dimension facts report and an
advisory config block, and writes the profile to JSON. It NEVER modifies any
config file — the recommendation is advisory (operator-in-the-loop).

The pure layer (data model, recommend mapping, render) lives in
``chess_coach.eval.profile``; this script is the live producer.

Usage:
    python scripts/profile_model.py \
        --model qwen3:14b --base-url http://localhost:11435 \
        --judge-provider cli --judge-model claude-sonnet-4.6 \
        --judge-command "kiro-cli chat --no-interactive --model claude-sonnet-4.6 {prompt}"
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shlex
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chess_coach.cli import _resolve_engine_path, load_config  # noqa: E402
from chess_coach.engine import CoachingEngine  # noqa: E402
from chess_coach.eval import (  # noqa: E402
    CapabilityProfile,
    DimensionResult,
    ProfileThresholds,
    default_move_feedback_path,
    load_move_feedback_scenarios,
    recommend,
    render_profile,
    render_recommendation,
    run_move_feedback_pairwise,
    summarize_skips,
)
from chess_coach.eval.benchmark import default_benchmark_path, load_benchmark  # noqa: E402
from chess_coach.eval.objective import evaluate_objective  # noqa: E402
from chess_coach.llm import create_provider  # noqa: E402
from chess_coach.llm.ollama import OllamaProvider  # noqa: E402
from chess_coach.openings import lookup_fen  # noqa: E402
from chess_coach.pedagogy.guard import guard_entries  # noqa: E402
from chess_coach.pedagogy.resource import (  # noqa: E402
    KnowledgeResource,
    PedagogyError,
    default_resource_path,
    load_resource,
)
from chess_coach.prompts import build_rich_coaching_prompt  # noqa: E402


def _build_engine(engine_cfg: dict, coaching_timeout: float) -> CoachingEngine:  # type: ignore[type-arg]
    path = _resolve_engine_path(engine_cfg["path"])
    args = [a for a in engine_cfg.get("args", []) if a != "--xboard"]
    if "--uci" not in args:
        args = ["--uci", *args]
    return CoachingEngine(path=path, args=args, coaching_timeout=coaching_timeout, ping_timeout=5.0)


# --------------------------------------------------------------- dimensions


def _dim_reachability(model: OllamaProvider) -> DimensionResult:
    """Cheapest gate: endpoint reachable + model loaded + can generate."""
    reachable, model_found = model.check_status()
    if not reachable:
        return DimensionResult("reachability", "fail", notes=f"endpoint unreachable at {model.base_url}")
    if not model_found:
        return DimensionResult("reachability", "fail", notes=f"model {model.model} not loaded at {model.base_url}")
    try:
        txt = model.generate("Say hello in one short sentence.", max_tokens=32, temperature=0.0)
    except Exception as e:
        return DimensionResult("reachability", "fail", notes=f"generation failed: {e}")
    if not txt.strip():
        return DimensionResult("reachability", "fail", notes="model returned an empty generation")
    return DimensionResult("reachability", "pass", samples=1, notes="endpoint + model + generation OK")


def _dim_factual(
    engine: CoachingEngine,
    model: OllamaProvider,
    positions: list,  # type: ignore[type-arg]
    *,
    multipv: int,
    depth: int | None,
    temperature: float,
    factual_min: float,
) -> tuple[DimensionResult, list[float]]:
    """Factual grounding over the benchmark positions; also returns per-call
    latencies (warm coaching-prompt timings) so the latency dimension is free."""
    scores: list[float] = []
    latencies: list[float] = []
    halluc = 0
    illegal = 0
    for pos in positions:
        try:
            report = engine.get_position_report(pos.fen, multipv=multipv, depth=depth)
        except Exception as e:
            print(f"  factual: {pos.id} engine skip: {e}")
            continue
        opening = lookup_fen(pos.fen)
        opening_label = f"{opening.eco} {opening.name}" if opening else None
        prompt = build_rich_coaching_prompt(report, level=pos.level, opening_name=opening_label)
        t0 = time.perf_counter()
        try:
            resp = model.generate(prompt, max_tokens=512, temperature=temperature)
        except Exception as e:
            print(f"  factual: {pos.id} gen error: {e}")
            continue
        latencies.append(time.perf_counter() - t0)
        obj = evaluate_objective(resp, report, pos)
        scores.append(obj.factual_score)
        halluc += len(obj.hallucinations)
        illegal += len(obj.illegal_moves)
        print(f"  factual: {pos.id} = {obj.factual_score:.2f}")
    if not scores:
        return DimensionResult("factual", "fail", notes="no positions scored"), latencies
    mean = round(sum(scores) / len(scores), 4)
    ok = mean >= factual_min and halluc == 0 and illegal == 0
    return (
        DimensionResult(
            "factual",
            "pass" if ok else "fail",
            metrics={"factual": mean, "hallucinations": float(halluc), "illegal_moves": float(illegal)},
            samples=len(scores),
        ),
        latencies,
    )


def _dim_guidance(
    engine: CoachingEngine,
    model: OllamaProvider,
    judge: object,
    resource: KnowledgeResource,
    *,
    depth: int | None,
    multipv: int,
    guidance_max: int,
    temperature: float,
    judge_repeats: int,
    win_rate_min: float,
    rng: random.Random,
) -> DimensionResult:
    """Guidance uptake via the move-feedback pairwise A/B (off vs on)."""
    scenarios = load_move_feedback_scenarios(default_move_feedback_path())
    summary, _records, skips = run_move_feedback_pairwise(
        scenarios,
        engine,
        model,
        judge,
        resource,
        depth=depth,
        multipv=multipv,
        guidance_max=guidance_max,
        temperature=temperature,
        judge_repeats=judge_repeats,
        rng=rng,
        on_progress=lambda m: print(f"  guidance: {m}"),
    )
    decisive = summary.n if summary else 0
    total = len(scenarios)
    # Don't trust a win-rate built on a handful of survivors: if too few
    # comparisons completed, surface WHY (dead tunnel, unauthenticated judge,
    # engine errors) instead of reporting a confident-looking result. A near-
    # total infrastructure failure must not masquerade as a model verdict.
    min_decisive = max(5, total // 2)
    if decisive < min_decisive:
        reason = summarize_skips(skips) or "no decisive comparisons produced"
        return DimensionResult(
            "guidance",
            "fail",
            metrics={"decisive": float(decisive), "scenarios": float(total)},
            samples=decisive,
            notes=f"insufficient comparisons ({decisive}/{total}) — {reason}",
        )
    assert summary is not None
    wr = summary.win_rate_b
    status = "pass" if wr >= win_rate_min else "info"
    note = summary.verdict
    if skips:
        note += f"  ({summarize_skips(skips)})"
    return DimensionResult(
        "guidance",
        status,
        metrics={
            "on_win_rate": round(wr, 4),
            "on_wins": float(summary.wins_b),
            "off_wins": float(summary.wins_a),
            "decisive": float(summary.n),
            "p_value": round(summary.p_value, 4),
        },
        samples=summary.n,
        notes=note,
    )


def _dim_latency(latencies: list[float]) -> DimensionResult:
    """Warm per-call latency (p50), reported as a fact only — never graded."""
    if not latencies:
        return DimensionResult("latency", "info", notes="no timed calls")
    p50 = round(statistics.median(latencies), 2)
    return DimensionResult("latency", "info", latency_s=p50, samples=len(latencies), notes="warm coaching-prompt p50")


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile a model's coaching capabilities → recommended config")
    parser.add_argument("--model", required=True, help="Model under test")
    parser.add_argument("--base-url", default="http://localhost:11435")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--engine-timeout", type=float, default=120.0)
    parser.add_argument("--depth", type=int, default=None)
    parser.add_argument("--multipv", type=int, default=3)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--guidance-max", type=int, default=3)
    parser.add_argument("--judge-repeats", type=int, default=5)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--factual-min", type=float, default=0.50)
    parser.add_argument("--guidance-win-rate-min", type=float, default=0.60)
    parser.add_argument("--out", default=None, help="Output JSON path (default output/profile_<model>.json)")
    # Judge config (mirrors eval_move_feedback_pairwise.py)
    parser.add_argument("--judge-model", required=True)
    parser.add_argument("--judge-provider", default="cli")
    parser.add_argument("--judge-base-url", default="http://localhost:11434")
    parser.add_argument("--judge-command", default=None)
    parser.add_argument("--judge-api-key", default=os.environ.get("CHESS_COACH_JUDGE_KEY", ""))
    args = parser.parse_args()

    config = load_config(args.config)
    depth = args.depth if args.depth is not None else config.get("engine", {}).get("depth")
    thresholds = ProfileThresholds(factual_min=args.factual_min, guidance_win_rate_min=args.guidance_win_rate_min)
    rng = random.Random(args.seed)

    model = OllamaProvider(model=args.model, base_url=args.base_url, timeout=300.0)
    dimensions: list[DimensionResult] = []

    # ---- 1. reachability (cheapest; short-circuits) ----
    print("Profiling reachability...")
    reach = _dim_reachability(model)
    dimensions.append(reach)
    print(f"  {reach.status}: {reach.notes}")

    if reach.status != "fail":
        # Judge + guarded resource needed for the guidance dimension.
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

        try:
            resource = load_resource(default_resource_path())
        except PedagogyError as e:
            print(f"FATAL: Knowledge_Resource unavailable: {e}")
            sys.exit(1)
        admitted, _ = guard_entries(resource.entries, engine=None)
        resource = KnowledgeResource(
            entries=tuple(admitted),
            feature_vocab=resource.feature_vocab,
            eco_vocab=resource.eco_vocab,
            levels=resource.levels,
        )

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

        try:
            print("Profiling factual grounding...")
            positions = load_benchmark(default_benchmark_path())
            factual_dim, latencies = _dim_factual(
                engine,
                model,
                positions,
                multipv=args.multipv,
                depth=depth,
                temperature=args.temperature,
                factual_min=args.factual_min,
            )
            dimensions.append(factual_dim)

            print("Profiling guidance uptake (move-feedback A/B)...")
            dimensions.append(
                _dim_guidance(
                    engine,
                    model,
                    judge,
                    resource,
                    depth=depth,
                    multipv=args.multipv,
                    guidance_max=args.guidance_max,
                    temperature=args.temperature,
                    judge_repeats=args.judge_repeats,
                    win_rate_min=args.guidance_win_rate_min,
                    rng=rng,
                )
            )

            dimensions.append(_dim_latency(latencies))
        finally:
            engine.stop()

    profile = CapabilityProfile(model=args.model, captured_at=datetime.now(timezone.utc), dimensions=dimensions)
    rec = recommend(profile, thresholds)

    print("\n" + render_profile(profile))
    print("\n" + render_recommendation(rec))

    safe_model = args.model.replace(":", "_").replace("/", "_")
    out_path = Path(args.out) if args.out else Path("output") / f"profile_{safe_model}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"profile": profile.to_dict(), "recommendation": rec.to_dict()}, indent=2),
        encoding="utf-8",
    )
    print(f"\nProfile written: {out_path}")


if __name__ == "__main__":
    main()
