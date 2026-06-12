#!/usr/bin/env python3
"""Layer 3 — judge calibration against human ratings (Task 7).

Workflow:

    # 1. Produce a judged run over the seed set (Layer 1 + Layer 2):
    python scripts/eval_run.py --models hermes3:8b \
        --judge-model fitt-smart --judge-base-url <gateway> \
        --out output/seed

    # 2. Emit a human-review file + a ratings template:
    python scripts/eval_calibrate.py generate --results output/seed/results.json

    # 3. Fill in data/eval/seed_ratings.yaml by hand (true/false per criterion).

    # 4. Compare the judge's verdicts against your ratings:
    python scripts/eval_calibrate.py agreement \
        --results output/seed/results.json --ratings data/eval/seed_ratings.yaml

`generate` and `agreement` are pure post-processing over the run's
results.json — no engine or LLM calls here. The judging already
happened in step 1.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chess_coach.eval.calibrate import (  # noqa: E402
    build_ratings_template,
    compute_agreement,
    load_seed_ratings,
    response_key,
)
from chess_coach.eval.judge import JudgeRubric, default_rubric_path, load_rubric  # noqa: E402


def _load_results(path: str) -> dict:  # type: ignore[type-arg]
    p = Path(path)
    if not p.exists():
        print(f"results file not found: {p}")
        sys.exit(1)
    return json.loads(p.read_text(encoding="utf-8"))


def _judge_pass_map(results: dict) -> dict[str, dict[str, bool]]:  # type: ignore[type-arg]
    """Extract {key: {criterion: pass}} from the judge verdicts in a
    results.json. Responses without a judge verdict are skipped."""
    out: dict[str, dict[str, bool]] = {}
    for r in results.get("responses", []):
        judge = r.get("judge")
        if not judge:
            continue
        key = response_key(r["position_id"], r["model"])
        # asdict serialised criteria as {k: [pass, reason]}.
        out[key] = {ck: bool(v[0]) for ck, v in judge.get("criteria", {}).items()}
    return out


def _build_review_markdown(results: dict, rubric: JudgeRubric) -> str:  # type: ignore[type-arg]
    lines = ["# Judge calibration — seed review", ""]
    lines.append(
        "For each response below, read the coaching text and the engine "
        "findings, then record true/false per criterion in the ratings "
        "YAML. The engine findings are the ground truth — judge "
        "'grounded' against them."
    )
    for r in results.get("responses", []):
        if r.get("error"):
            continue
        key = response_key(r["position_id"], r["model"])
        obj = r.get("objective", {})
        lines.append("\n---\n")
        lines.append(f"## {key}")
        lines.append("\n**Engine findings (ground truth):**")
        lines.append(f"- factual score: {obj.get('factual_score')}")
        lines.append(f"- hallucinations: {obj.get('hallucinations') or '(none)'}")
        lines.append(f"- illegal moves: {obj.get('illegal_moves') or '(none)'}")
        lines.append(f"- eval direction ok: {obj.get('eval_direction_ok')}")
        lines.append(f"- key-fact coverage: {obj.get('coverage_hits')} / {obj.get('coverage_total')}")
        lines.append("\n**Coaching response:**\n")
        lines.append(f"> {r.get('response', '').strip()}")
        lines.append("\n**Rate each criterion (true/false):**")
        for c in rubric.criteria:
            lines.append(f"- [ ] {c.key}: {c.description}")
    return "\n".join(lines) + "\n"


def _cmd_generate(args: argparse.Namespace, rubric: JudgeRubric) -> None:
    results = _load_results(args.results)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    review = _build_review_markdown(results, rubric)
    review_path = out_dir / "seed_review.md"
    review_path.write_text(review, encoding="utf-8")

    keys = [response_key(r["position_id"], r["model"]) for r in results.get("responses", []) if not r.get("error")]
    template = build_ratings_template(keys, rubric)
    template_path = out_dir / "seed_ratings_template.yaml"
    template_path.write_text(template, encoding="utf-8")

    print(f"Review file:      {review_path}")
    print(f"Ratings template: {template_path}")
    print("\nFill the template (true/false per criterion) and save it, then run:")
    print(f"  python scripts/eval_calibrate.py agreement --results {args.results} --ratings {template_path}")


def _cmd_agreement(args: argparse.Namespace, rubric: JudgeRubric) -> None:
    results = _load_results(args.results)
    judge = _judge_pass_map(results)
    if not judge:
        print("No judge verdicts in results.json — rerun eval_run with --judge-model.")
        sys.exit(1)
    human = load_seed_ratings(args.ratings)

    report = compute_agreement(human, judge, rubric, threshold=args.threshold)

    print(f"Judge-vs-human agreement ({report.n} responses, rubric {rubric.version})")
    print("-" * 56)
    for ck in rubric.keys():
        pct = report.per_criterion[ck]
        flag = "  <-- below threshold" if ck in report.below_threshold else ""
        print(f"  {ck:<16} {pct * 100:5.0f}%{flag}")
    print("-" * 56)
    print(f"  overall          {report.overall * 100:5.0f}%")
    if report.missing:
        print(f"\n  note: {len(report.missing)} response(s) rated by only one side (skipped)")

    if not report.ok:
        print(
            f"\nFLAG: agreement below {report.threshold * 100:.0f}% on "
            f"{report.below_threshold or ['(no overlap)']} — revise the "
            "rubric wording or pick a stronger judge before trusting "
            "automated quality scores."
        )
        sys.exit(1)
    print(f"\nOK: judge agrees with the human at or above {report.threshold * 100:.0f}% everywhere.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Judge calibration (Layer 3)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="emit review file + ratings template")
    g.add_argument("--results", required=True, help="results.json from a judged eval_run")
    g.add_argument("--out", default="output/eval_calibrate")

    a = sub.add_parser("agreement", help="compare judge verdicts vs human ratings")
    a.add_argument("--results", required=True, help="results.json from a judged eval_run")
    a.add_argument("--ratings", required=True, help="human ratings YAML")
    a.add_argument("--threshold", type=float, default=0.8)

    args = parser.parse_args()
    rubric = load_rubric(default_rubric_path())

    if args.cmd == "generate":
        _cmd_generate(args, rubric)
    elif args.cmd == "agreement":
        _cmd_agreement(args, rubric)


if __name__ == "__main__":
    main()
