#!/usr/bin/env python3
"""Run the coaching-eval benchmark and produce a factual scoreboard.

Layer 1 path (no judge, no frontier tokens): for each model, generate
coaching for every benchmark position, run the objective checks, and
roll up a per-model scoreboard.

Usage:
    # Default model from config, local Ollama:
    python scripts/eval_run.py

    # Specific models:
    python scripts/eval_run.py --models qwen3:8b gpt-oss:20b

    # Against the EC2 tunnel (see ~/.fitt/ec2-runbook.md):
    python scripts/eval_run.py --models qwen3:14b --base-url http://localhost:11435

    # A subset of positions:
    python scripts/eval_run.py --positions kr_vs_k hanging_knight_e4

Results: output/eval_run/results.json + summary.txt

Layer 2 (the frontier judge) is added in a later task; this script is
the fast, free regression path.
"""

from __future__ import annotations

import argparse
import os
import shlex
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chess_coach.cli import _resolve_engine_path, load_config  # noqa: E402
from chess_coach.engine import CoachingEngine  # noqa: E402
from chess_coach.eval import (  # noqa: E402
    BenchmarkPosition,
    ResponseEval,
    RunConfig,
    Scoreboard,
    evaluate_objective,
    load_benchmark,
    persist_results,
)
from chess_coach.eval.benchmark import default_benchmark_path  # noqa: E402
from chess_coach.eval.judge import (  # noqa: E402
    JudgeRubric,
    default_rubric_path,
    judge_response,
    load_rubric,
)
from chess_coach.eval.objective import ObjectiveResult  # noqa: E402
from chess_coach.llm import create_provider  # noqa: E402
from chess_coach.llm.ollama import OllamaProvider  # noqa: E402
from chess_coach.models import PositionReport  # noqa: E402
from chess_coach.openings import lookup_fen  # noqa: E402
from chess_coach.pedagogy.guard import guard_entries  # noqa: E402
from chess_coach.pedagogy.resource import (  # noqa: E402
    GuidanceEntry,
    KnowledgeResource,
    PedagogyError,
    default_resource_path,
    load_resource,
)
from chess_coach.pedagogy.selector import guidance_for_position  # noqa: E402
from chess_coach.prompts import build_rich_coaching_prompt  # noqa: E402


def _zero_objective(position: BenchmarkPosition) -> ObjectiveResult:
    """Objective result for a failed generation — scores 0 so the
    model isn't silently credited for a position it couldn't answer."""
    required_referenceable = sum(
        1 for p in position.required_points() if p.kind in {"hanging_piece", "tactic", "free", "eval_direction"}
    )
    return ObjectiveResult(
        hallucinations=[],
        illegal_moves=[],
        eval_direction_ok=None,
        coverage_hits=[],
        coverage_total=required_referenceable,
        factual_score=0.0,
    )


def _build_engine(engine_cfg: dict, coaching_timeout: float) -> CoachingEngine:  # type: ignore[type-arg]
    """Build a UCI CoachingEngine from config with a configurable
    coaching timeout (eval runs on a dev build can exceed the 30s
    default, and we'd rather wait than skip the position)."""
    path = _resolve_engine_path(engine_cfg["path"])
    args = [a for a in engine_cfg.get("args", []) if a != "--xboard"]
    if "--uci" not in args:
        args = ["--uci", *args]
    return CoachingEngine(path=path, args=args, coaching_timeout=coaching_timeout, ping_timeout=5.0)


def _analyze_positions(
    engine: CoachingEngine,
    positions: list[BenchmarkPosition],
    multipv: int,
    depth: int | None,
) -> dict[str, PositionReport]:
    """Compute the engine report for each position once, up front.
    The engine analysis is the slow part — reuse across all models."""
    reports: dict[str, PositionReport] = {}
    for pos in positions:
        print(f"  engine: {pos.id}...", end=" ", flush=True)
        t0 = time.perf_counter()
        try:
            reports[pos.id] = engine.get_position_report(pos.fen, multipv=multipv, depth=depth)
            print(f"{time.perf_counter() - t0:.1f}s")
        except Exception as e:
            print(f"SKIP (engine error: {e})")
    return reports


def _run_model(
    provider: object,
    model: str,
    positions: list[BenchmarkPosition],
    reports: dict[str, PositionReport],
    temperature: float = 0.0,
    guidance_by_id: dict[str, list[GuidanceEntry]] | None = None,
) -> list[ResponseEval]:
    if not provider.is_available():  # type: ignore[attr-defined]
        print(f"  WARNING: model {model} not available — skipping")
        return []

    evals: list[ResponseEval] = []
    for pos in positions:
        report = reports.get(pos.id)
        if report is None:
            continue  # engine skipped this position
        opening = lookup_fen(pos.fen)
        opening_label = f"{opening.eco} {opening.name}" if opening else None
        guidance = guidance_by_id.get(pos.id) if guidance_by_id is not None else None
        prompt = build_rich_coaching_prompt(report, level=pos.level, opening_name=opening_label, guidance=guidance)

        print(f"  {model}: {pos.id}...", end=" ", flush=True)
        t0 = time.perf_counter()
        try:
            response = provider.generate(prompt, max_tokens=512, temperature=temperature)  # type: ignore[attr-defined]
            latency = time.perf_counter() - t0
        except Exception as e:
            print(f"GEN ERROR: {e}")
            evals.append(
                ResponseEval(
                    position_id=pos.id,
                    model=model,
                    response="",
                    word_count=0,
                    latency_s=round(time.perf_counter() - t0, 2),
                    objective=_zero_objective(pos),
                    error=str(e),
                )
            )
            continue

        objective = evaluate_objective(response, report, pos)
        evals.append(
            ResponseEval(
                position_id=pos.id,
                model=model,
                response=response,
                word_count=len(response.split()),
                latency_s=round(latency, 2),
                objective=objective,
            )
        )
        flag = "" if objective.passed else "  <-- below pass"
        print(f"{latency:.1f}s factual={objective.factual_score:.2f}{flag}")
    return evals


def _make_provider(model: str, base_url: str) -> OllamaProvider:
    return OllamaProvider(model=model, base_url=base_url, timeout=300.0)


def _judge_evals(
    evals: list[ResponseEval],
    positions_by_id: dict[str, BenchmarkPosition],
    reports: dict[str, PositionReport],
    rubric: JudgeRubric,
    judge_provider: object,
    guidance_by_id: dict[str, list[GuidanceEntry]] | None = None,
) -> None:
    """Run the Layer 2 judge over successful responses, setting
    ``e.judge`` in place. A judge failure on one response leaves its
    Layer 1 score intact (judge stays None) and never aborts the run."""
    for e in evals:
        if e.error:
            continue  # nothing to judge — generation failed
        report = reports.get(e.position_id)
        pos = positions_by_id.get(e.position_id)
        if report is None or pos is None:
            continue
        guidance = guidance_by_id.get(e.position_id) if guidance_by_id is not None else None
        print(f"  judge: {e.model} / {e.position_id}...", end=" ", flush=True)
        try:
            e.judge = judge_response(judge_provider, e.response, report, pos, rubric, guidance=guidance)
            print(f"quality={e.judge.quality_score:.2f}")
        except Exception as ex:
            print(f"JUDGE ERROR (Layer 1 stands): {ex}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the coaching-eval benchmark (Layer 1)")
    parser.add_argument("--config", default="config.yaml", help="chess-coach config.yaml")
    parser.add_argument("--models", nargs="*", default=[], help="Ollama model(s) to evaluate")
    parser.add_argument("--base-url", default="http://localhost:11434", help="Ollama base URL")
    parser.add_argument("--positions", nargs="*", default=[], help="Only these position ids")
    parser.add_argument("--benchmark", default=None, help="Path to positions.yaml")
    parser.add_argument("--out", default="output/eval_run", help="Output directory")
    parser.add_argument("--multipv", type=int, default=3)
    parser.add_argument(
        "--engine-timeout",
        type=float,
        default=120.0,
        help="Per-analysis coaching timeout in seconds (default 120)",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=None,
        help="Override engine analysis depth (default: config engine.depth)",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="Model-under-test sampling temperature. Default 0.0 for "
        "reproducible benchmark scores; use 0.7 to match production coaching.",
    )
    parser.add_argument(
        "--guidance",
        choices=["on", "off"],
        default="off",
        help="Inject pedagogy-layer guidance into the coach AND judge prompts (Req 5). Default off (baseline).",
    )
    parser.add_argument(
        "--guidance-max",
        type=int,
        default=3,
        help="Max guidance entries selected per position when --guidance on (default 3).",
    )
    parser.add_argument(
        "--judge-model",
        default=None,
        help="Enable Layer 2 judging with this model id (e.g. fitt-smart, claude-...). Omit to run Layer 1 only.",
    )
    parser.add_argument(
        "--rubric",
        default=None,
        help="Path to the judge rubric YAML (default: data/eval/rubric.v1.yaml).",
    )
    parser.add_argument(
        "--judge-provider",
        default="openai_compat",
        help="Provider for the judge endpoint (openai_compat | ollama).",
    )
    parser.add_argument(
        "--judge-base-url",
        default="http://localhost:11434",
        help="Judge endpoint base URL (e.g. the FITT gateway).",
    )
    parser.add_argument(
        "--judge-command",
        default=None,
        help="For --judge-provider cli: the command to run as the judge "
        "(prompt piped on stdin, or substituted for a {prompt} token). "
        'Example: --judge-command "kiro-cli chat --no-interactive".',
    )
    parser.add_argument(
        "--judge-api-key",
        default=os.environ.get("CHESS_COACH_JUDGE_KEY", ""),
        help="Bearer key for the judge endpoint (or set CHESS_COACH_JUDGE_KEY).",
    )
    args = parser.parse_args()

    bench_path = Path(args.benchmark) if args.benchmark else default_benchmark_path()
    positions = load_benchmark(bench_path)
    if args.positions:
        wanted = set(args.positions)
        positions = [p for p in positions if p.id in wanted]
        if not positions:
            print(f"No benchmark positions match {sorted(wanted)}")
            sys.exit(1)

    config = load_config(args.config)
    models = args.models or [config.get("llm", {}).get("model", "qwen3:8b")]
    depth = args.depth if args.depth is not None else config.get("engine", {}).get("depth")

    print(f"Benchmark: {bench_path} ({len(positions)} positions)")
    print(f"Models: {', '.join(models)}")
    print(f"Ollama: {args.base_url}\n")

    engine = _build_engine(config["engine"], args.engine_timeout)
    try:
        engine.start()
    except Exception as e:
        print(f"FATAL: could not start engine: {e}")
        sys.exit(1)

    if not engine.coaching_available:
        engine.stop()
        print(
            "FATAL: the configured engine does not support the coaching "
            "protocol (coach ping failed). The eval harness needs a "
            "coaching-capable Blunder build — see the linux path in "
            "config.yaml / the EC2 box. The local dev build may predate "
            "coaching support."
        )
        sys.exit(1)

    all_evals: list[ResponseEval] = []
    try:
        print("Analyzing positions (once, shared across models):")
        reports = _analyze_positions(engine, positions, args.multipv, depth)
        if not reports:
            print("FATAL: engine produced no reports — nothing to evaluate")
            sys.exit(1)

        # Pedagogy-layer guidance (Req 5): build ONE selection per position
        # and hand the identical list to both the coach prompt and the judge
        # (single-source parity, Req 4.5). Default off = today's baseline.
        guidance_by_id: dict[str, list[GuidanceEntry]] | None = None
        if args.guidance == "on":
            try:
                ped_resource = load_resource(default_resource_path())
            except PedagogyError as e:
                print(f"FATAL: Knowledge_Resource unavailable: {e}")
                sys.exit(1)
            admitted, _guard_results = guard_entries(ped_resource.entries, engine=None)
            admitted_resource = KnowledgeResource(
                entries=tuple(admitted),
                feature_vocab=ped_resource.feature_vocab,
                eco_vocab=ped_resource.eco_vocab,
                levels=ped_resource.levels,
            )
            pos_by_id = {p.id: p for p in positions}
            guidance_by_id = {
                pid: guidance_for_position(admitted_resource, rep, pos_by_id[pid].level, args.guidance_max)
                for pid, rep in reports.items()
            }
            n_entries = sum(len(v) for v in guidance_by_id.values())
            print(
                f"Guidance: ON — {len(admitted)}/{len(ped_resource.entries)} entries admitted; "
                f"{n_entries} selected across {len(guidance_by_id)} positions (max {args.guidance_max})."
            )

        for model in models:
            print(f"\n--- {model} ---")
            provider = _make_provider(model, args.base_url)
            all_evals.extend(
                _run_model(
                    provider,
                    model,
                    positions,
                    reports,
                    temperature=args.temperature,
                    guidance_by_id=guidance_by_id,
                )
            )

        # Layer 2: judge (optional).
        rubric: JudgeRubric | None = None
        if args.judge_model:
            rubric = load_rubric(Path(args.rubric) if args.rubric else default_rubric_path())
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
            judge_provider = create_provider(args.judge_provider, **judge_kwargs)
            positions_by_id = {p.id: p for p in positions}
            print(f"\n--- judging with {args.judge_model} (rubric {rubric.version}) ---")
            _judge_evals(all_evals, positions_by_id, reports, rubric, judge_provider, guidance_by_id=guidance_by_id)
    finally:
        engine.stop()

    scoreboard = Scoreboard.from_response_evals(all_evals)
    run_config = RunConfig.create(
        models=models,
        benchmark_path=str(bench_path),
        temperature=args.temperature,
        judge_model=args.judge_model,
        rubric_version=rubric.version if rubric else None,
        guidance=args.guidance,
        guidance_max=args.guidance_max if args.guidance == "on" else 0,
    )
    results_path, summary_path = persist_results(args.out, run_config, all_evals, scoreboard)

    print("\n" + scoreboard.render())
    print(f"\nResults: {results_path}")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
