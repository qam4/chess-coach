#!/usr/bin/env python3
"""Aggregate repeated eval runs into mean +/- std, with an off-vs-on band.

A single ``eval_run.py`` result is a point estimate within judge noise.
Run the benchmark several times (into separate ``--out`` dirs) and feed
the result dirs here to see the spread, and -- for the pedagogy A/B --
whether an off->on delta actually clears the combined noise of the two
groups.

Usage:
    # Aggregate N repeated runs of the same condition (mean +/- std):
    python scripts/eval_aggregate.py output/run1 output/run2 output/run3

    # Off-vs-on comparison with a noise band (>=2 runs per side to assess):
    python scripts/eval_aggregate.py \
        --off output/off1 output/off2 output/off3 \
        --on  output/on1  output/on2  output/on3

Each DIR must contain a results.json written by eval_run.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chess_coach.eval import (  # noqa: E402
    ModelSummary,
    aggregate_runs,
    compare_off_on,
    render_aggregate,
    render_comparison,
)


def _load_summaries(dirs: list[str]) -> list[ModelSummary]:
    """Load every per-model summary from the result dirs' results.json."""
    summaries: list[ModelSummary] = []
    for d in dirs:
        path = Path(d) / "results.json"
        if not path.exists():
            print(f"FATAL: no results.json in {d}")
            sys.exit(1)
        data = json.loads(path.read_text(encoding="utf-8"))
        for s in data.get("scoreboard", {}).get("summaries", []):
            summaries.append(ModelSummary(**s))
    if not summaries:
        print("FATAL: no model summaries found in the given dirs")
        sys.exit(1)
    return summaries


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate repeated eval runs (mean +/- std)")
    parser.add_argument("dirs", nargs="*", help="Result dirs to aggregate (single-condition mode)")
    parser.add_argument("--off", nargs="*", default=[], help="Result dirs for the OFF (baseline) condition")
    parser.add_argument("--on", nargs="*", default=[], help="Result dirs for the ON (guidance) condition")
    args = parser.parse_args()

    comparison_mode = bool(args.off or args.on)
    if comparison_mode:
        if not (args.off and args.on):
            print("FATAL: comparison mode needs both --off and --on dirs")
            sys.exit(1)
        off_models = aggregate_runs(_load_summaries(args.off))
        on_models = aggregate_runs(_load_summaries(args.on))
        off_by_model = {m.model: m for m in off_models}
        on_by_model = {m.model: m for m in on_models}
        shared = sorted(set(off_by_model) & set(on_by_model))
        if not shared:
            print("FATAL: no model appears in both --off and --on runs")
            sys.exit(1)
        for model in shared:
            comparisons = compare_off_on(off_by_model[model], on_by_model[model])
            print(render_comparison(model, comparisons))
            print()
        return

    if not args.dirs:
        parser.error("provide result dirs to aggregate, or use --off/--on for a comparison")
    print(render_aggregate(aggregate_runs(_load_summaries(args.dirs))))


if __name__ == "__main__":
    main()
