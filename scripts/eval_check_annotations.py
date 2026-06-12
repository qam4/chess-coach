#!/usr/bin/env python3
"""Check benchmark annotations against the engine oracle (Task 9).

For every benchmark position, fetch the engine report and verify the
structured annotations (eval_direction, hanging_piece, tactic) match
what the engine actually says. Exits non-zero if any position
disagrees — run it after editing positions.yaml, or in CI on a box
with a coaching-capable engine.

Usage:
    python scripts/eval_check_annotations.py
    python scripts/eval_check_annotations.py --engine-timeout 60
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chess_coach.cli import _resolve_engine_path, load_config  # noqa: E402
from chess_coach.engine import CoachingEngine  # noqa: E402
from chess_coach.eval.annotations import check_position_annotations  # noqa: E402
from chess_coach.eval.benchmark import default_benchmark_path, load_benchmark  # noqa: E402


def _build_engine(engine_cfg: dict, coaching_timeout: float) -> CoachingEngine:  # type: ignore[type-arg]
    path = _resolve_engine_path(engine_cfg["path"])
    args = [a for a in engine_cfg.get("args", []) if a != "--xboard"]
    if "--uci" not in args:
        args = ["--uci", *args]
    return CoachingEngine(path=path, args=args, coaching_timeout=coaching_timeout, ping_timeout=5.0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check benchmark annotations vs the engine")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--benchmark", default=None)
    parser.add_argument("--multipv", type=int, default=3)
    parser.add_argument("--engine-timeout", type=float, default=120.0)
    args = parser.parse_args()

    bench_path = Path(args.benchmark) if args.benchmark else default_benchmark_path()
    positions = load_benchmark(bench_path)
    config = load_config(args.config)
    depth = config.get("engine", {}).get("depth")

    engine = _build_engine(config["engine"], args.engine_timeout)
    engine.start()
    if not engine.coaching_available:
        engine.stop()
        print("FATAL: engine lacks coaching protocol — need a coaching-capable build.")
        sys.exit(2)

    total_mismatches = 0
    try:
        for pos in positions:
            try:
                report = engine.get_position_report(pos.fen, multipv=args.multipv, depth=depth)
            except Exception as e:
                print(f"?? {pos.id}: engine error: {e}")
                total_mismatches += 1
                continue
            issues = check_position_annotations(pos, report)
            if not issues:
                print(f"OK  {pos.id}")
            else:
                total_mismatches += len(issues)
                print(f"!!  {pos.id}:")
                for msg in issues:
                    print(f"      {msg}")
    finally:
        engine.stop()

    print()
    if total_mismatches:
        print(f"FAIL: {total_mismatches} annotation mismatch(es) vs the engine oracle.")
        sys.exit(1)
    print(f"PASS: all {len(positions)} positions agree with the engine.")


if __name__ == "__main__":
    main()
