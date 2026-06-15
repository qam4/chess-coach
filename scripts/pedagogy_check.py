#!/usr/bin/env python3
"""Validate the curated pedagogy knowledge resource (Task 6.3).

Mirrors ``scripts/eval_check_annotations.py``: load
``data/pedagogy/knowledge.yaml``, run the schema / referential-integrity
/ example-legality guard on every entry, optionally start the coaching
engine and run the engine-soundness check on entries that carry an
example, print a per-entry PASS / REJECT report with reasons, and exit
non-zero if any entry is rejected.

The schema/ref/legality checks need no engine and no network (Req 6.7,
7.2, 7.4), so the default run works on any dev box. Pass ``--with-engine``
to additionally verify example moves are engine-sound (Req 6.4); the
script aborts clearly if the engine is requested but unavailable.

Usage:
    python scripts/pedagogy_check.py
    python scripts/pedagogy_check.py --with-engine
    python scripts/pedagogy_check.py --with-engine --engine-timeout 60
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chess_coach.cli import _resolve_engine_path, load_config  # noqa: E402
from chess_coach.engine import CoachingEngine  # noqa: E402
from chess_coach.pedagogy.guard import guard_entries  # noqa: E402
from chess_coach.pedagogy.resource import (  # noqa: E402
    default_resource_path,
    load_resource,
)


def _build_engine(engine_cfg: dict, coaching_timeout: float) -> CoachingEngine:  # type: ignore[type-arg]
    path = _resolve_engine_path(engine_cfg["path"])
    args = [a for a in engine_cfg.get("args", []) if a != "--xboard"]
    if "--uci" not in args:
        args = ["--uci", *args]
    return CoachingEngine(path=path, args=args, coaching_timeout=coaching_timeout, ping_timeout=5.0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the pedagogy knowledge resource vs schema + engine")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--resource", default=None, help="path to knowledge.yaml (defaults to the shipped seed)")
    parser.add_argument(
        "--with-engine",
        action="store_true",
        help="also run the engine-soundness check on example moves (Req 6.4)",
    )
    parser.add_argument("--engine-timeout", type=float, default=120.0)
    args = parser.parse_args()

    resource_path = Path(args.resource) if args.resource else default_resource_path()
    resource = load_resource(resource_path)
    print(f"Loaded {len(resource.entries)} entries from {resource_path}")

    engine: CoachingEngine | None = None
    depth: int | None = None
    if args.with_engine:
        config = load_config(args.config)
        depth = config.get("engine", {}).get("depth")
        engine = _build_engine(config["engine"], args.engine_timeout)
        engine.start()
        if not engine.coaching_available:
            engine.stop()
            print("FATAL: engine lacks coaching protocol — need a coaching-capable build for --with-engine.")
            sys.exit(2)
        print("Engine soundness check ENABLED (coaching protocol available).")
    else:
        print("Engine soundness check DISABLED (schema/ref/legality only). Use --with-engine for Req 6.4.")

    try:
        _admitted, results = guard_entries(resource.entries, engine=engine, depth=depth)
    finally:
        if engine is not None:
            engine.stop()

    rejected = 0
    for result in results:
        if result.admitted:
            print(f"PASS    {result.entry_id}")
        else:
            rejected += 1
            print(f"REJECT  {result.entry_id}:")
            for reason in result.reasons:
                print(f"          {reason}")

    print()
    if rejected:
        print(f"FAIL: {rejected} of {len(results)} entr(ies) rejected by the annotation guard.")
        sys.exit(1)
    print(f"PASS: all {len(results)} entries admitted by the annotation guard.")


if __name__ == "__main__":
    main()
