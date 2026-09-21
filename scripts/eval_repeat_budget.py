"""How many runs per arm does it take to believe a change? Answered from repeated runs.

Every number in `docs/coach-metrics-history.tsv` up to 2026-09-21 came from ONE run per version,
and on 2026-09-21 the v53-to-v54 comparison showed why that is not enough: the two sweeps sent
byte-identical prompts and 60% of the coach's prose came back different. A one-turn change in
`clean_pct` was nearly credited to a code fix when the prompt for that turn had not changed at
all.

So this script measures the spread of each metric when NOTHING changes, and converts it into the
only number that decides a run budget: how many runs per arm are needed to detect a difference of
a given size.

    python scripts/eval_repeat_budget.py output/repeat          # the table
    python scripts/eval_repeat_budget.py output/repeat --detect 5

TWO KINDS OF METRIC, and the distinction is the most useful output here:

- **Prompt-side** (`cause_given_pct`, `lesson_conc_pct`, `lesson_open_pct`, `spoke`, `plies`) are
  computed from the instruction WE composed, which is deterministic given the seed. Their spread
  is zero by construction, so one run per arm is enough and any movement at all is real. Measured
  rather than assumed: if one of these shows spread, either the pipeline is not deterministic or
  the metric is not reading what it claims to.
- **Model-side** (`clean_pct`, `cause_voiced_pct`, `words_per_turn`) are read off the model's
  prose and carry its churn.

The arithmetic is the standard two-sample normal approximation, and its assumptions are stated
because they are shaky on this data: independence (fine — separate processes), normality (a
percentage over ~18 turns is lumpy, so treat the answer as an order of magnitude), and a common
variance across arms (unknown, since we only have repeats of an unchanged build).

    n per arm = 2 * (z_alpha/2 + z_beta)^2 * sigma^2 / delta^2

at 95% confidence and 80% power, so (1.96 + 0.8416)^2 * 2 = 15.7.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import eval_hard_metrics as ehm  # noqa: E402

from chess_coach.eval.run_compare import compare, partition_repeats  # noqa: E402

#: 95% confidence, 80% power. 2 * (1.959964 + 0.841621)^2.
Z_FACTOR = 2 * (1.959964 + 0.841621) ** 2

#: Metrics computed from our own composed prompt, so deterministic given the seed. Listed rather
#: than inferred, so that a metric moving from one column to the other is a finding and not a
#: silent reclassification.
PROMPT_SIDE = {"spoke", "plies", "cause_given_pct", "lesson_conc_pct", "lesson_open_pct"}


def metrics_for(path: Path) -> dict[str, float | None]:
    """The metrics this script compares, from one transcript.

    `ehm.Metrics` already returns these *_rate fields as PERCENTAGES, not fractions. A first
    version multiplied by 100 and printed a mean `clean_pct` of 9473.7, which is the kind of
    number that should stop a reader — and the sd it reports would have been 100x too large had
    any of them moved.
    """
    m = ehm.measure(path)
    return {
        "spoke": float(m.spoken),
        "plies": float(m.plies),
        "clean_pct": m.clean_rate,
        "cause_given_pct": m.cause_given_rate,
        "cause_voiced_pct": m.cause_voiced_rate,
        "lesson_conc_pct": m.lesson_concentration,
        "lesson_open_pct": None if not m.spoken else 100.0 * m.lesson_open / m.spoken,
        "words_per_turn": float(m.words_per_turn),
    }


def cell_of(path: Path) -> str:
    """Group repeats of the same configuration. `seed7_r3` -> `seed7`."""
    name = path.parent.name
    return name.rsplit("_r", 1)[0] if "_r" in name else name


def runs_needed(sigma: float, delta: float) -> int | str:
    if sigma == 0:
        return 1
    if delta <= 0:
        return "n/a"
    return max(1, int(-(-Z_FACTOR * sigma * sigma // (delta * delta))))


def _transcript(arg: Path) -> Path:
    """Accept either a run directory or the transcript inside it."""
    return arg if arg.is_file() else arg / "transcript.json"


def run_compare(left: Path, right: Path) -> int:
    """Attribute a difference between two runs. Exit 1 when they are not a genuine repeat."""
    a, b = _transcript(left), _transcript(right)
    for p in (a, b):
        if not p.exists():
            print(f"no such transcript: {p}")
            return 1
    c = compare(a, b)
    print(c.summary())
    print()
    print(c.verdict())
    if c.model:
        print(f"\n  plies differing with an identical prompt: {c.model}")
    if c.input_changed:
        shown = c.input_changed[:20]
        tail = "" if len(c.input_changed) == len(shown) else f" ... and {len(c.input_changed) - len(shown)} more"
        print(f"\n  plies whose prompt changed: {shown}{tail}")
    return 0 if c.is_repeat else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", nargs="?", help="directory of repeat runs, e.g. output/repeat")
    ap.add_argument(
        "--detect",
        type=float,
        action="append",
        help="difference to detect, in points; repeatable (default 3, 5, 10)",
    )
    ap.add_argument(
        "--compare",
        nargs=2,
        metavar=("A", "B"),
        help="attribute the difference between two runs to the INPUT or to the model, and stop. "
        "Run this before calling any difference noise.",
    )
    args = ap.parse_args()
    deltas = args.detect or [3.0, 5.0, 10.0]

    if args.compare:
        return run_compare(Path(args.compare[0]), Path(args.compare[1]))
    if not args.root:
        ap.error("give a directory of repeat runs, or --compare A B")

    root = Path(args.root)
    paths = sorted(root.glob("*/transcript.json"))
    if not paths:
        print(f"no transcripts under {root}")
        return 1

    by_cell: dict[str, list[Path]] = defaultdict(list)
    for p in paths:
        by_cell[cell_of(p)].append(p)

    summary = ", ".join(f"{c} x{len(v)}" for c, v in sorted(by_cell.items()))
    print(f"{len(paths)} runs in {len(by_cell)} cell(s): {summary}")

    # THE GUARD. A run whose prompts differ is a different experiment, and pooling it as a repeat
    # is precisely the 2026-09-21 error: two sweeps spanning an encoding fix were compared and the
    # resulting text differences were reported as the coach being 60% irreproducible. Rejecting
    # loudly rather than averaging silently.
    dropped = 0
    for cell in sorted(by_cell):
        keep, rejected = partition_repeats(by_cell[cell])
        if rejected:
            print(f"\n  {cell}: DROPPED {len(rejected)} run(s) — not a repeat of {by_cell[cell][0].parent.name}:")
            for path, cmp_ in rejected:
                print(f"    {path.parent.name}: {len(cmp_.input_changed)} turn(s) have a different PROMPT")
            print("    Their prompts differ, so any spread they add measures the code change, not noise.")
            dropped += len(rejected)
        by_cell[cell] = keep

    usable = {c: v for c, v in by_cell.items() if len(v) >= 2}
    if not usable:
        print("\nno cell has 2+ genuine repeats — a single run cannot show spread")
        return 1
    if dropped:
        print(f"\n  continuing with {sum(len(v) for v in usable.values())} run(s) after dropping {dropped}")
    print()

    # Per cell, then pooled. Pooling is what the budget should rest on: a sigma from one game is
    # one game, which is the mistake this whole exercise exists to stop repeating.
    per_metric_values: dict[str, list[list[float]]] = defaultdict(list)
    for cell, cell_paths in sorted(usable.items()):
        rows = [metrics_for(p) for p in cell_paths]
        print(f"--- {cell} ({len(rows)} runs)")
        print(f"{'metric':20} {'mean':>8} {'sd':>7} {'min':>7} {'max':>7} {'range':>7}")
        for key in metrics_for(cell_paths[0]):
            vals = [r[key] for r in rows if r[key] is not None]
            if len(vals) < 2:
                print(f"{key:20} {'n/a':>8}")
                continue
            vv = [float(v) for v in vals]
            per_metric_values[key].append(vv)
            sd = statistics.stdev(vv)
            print(
                f"{key:20} {statistics.mean(vv):8.1f} {sd:7.2f} {min(vv):7.1f} {max(vv):7.1f} {max(vv) - min(vv):7.1f}"
            )
        print()

    print("=" * 78)
    print("POOLED within-cell spread, and the run budget it implies")
    print("=" * 78)
    head = f"{'metric':20} {'side':13} {'sd':>7}" + "".join(f"{f'n@{d:g}pp':>9}" for d in deltas)
    print(head)
    print("-" * len(head))
    for key, groups in per_metric_values.items():
        # Pool the within-cell variances: each cell contributes (n-1) degrees of freedom.
        num = sum((len(g) - 1) * statistics.variance(g) for g in groups if len(g) >= 2)
        den = sum(len(g) - 1 for g in groups if len(g) >= 2)
        sigma = (num / den) ** 0.5 if den else 0.0
        side = "prompt-side" if key in PROMPT_SIDE else "model-side"
        cells = "".join(f"{str(runs_needed(sigma, d)):>9}" for d in deltas)
        print(f"{key:20} {side:13} {sigma:7.2f}{cells}")

    print()
    print("Reading this: a prompt-side metric with sd 0 needs ONE run per arm and any movement is")
    print("real. A model-side metric needs the stated number of runs before a difference of that")
    print("size means anything. n is per ARM, so a v-to-v comparison costs twice it.")
    zero_spread = [
        key
        for key, groups in per_metric_values.items()
        if key in PROMPT_SIDE and any(statistics.variance(g) > 0 for g in groups if len(g) >= 2)
    ]
    if zero_spread:
        print()
        print("WARNING: these are supposed to be deterministic and moved anyway: " + ", ".join(zero_spread))
        print("Either the pipeline is not deterministic or the metric does not measure what it claims.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
