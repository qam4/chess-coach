#!/usr/bin/env python3
"""Evaluate LLM coaching quality across models and positions.

Usage:
    python scripts/eval_models.py [model1 model2 ...]

Defaults to qwen3:1.7b, qwen3:4b, qwen3:8b if no models specified.

Runs each model against a set of test positions and saves structured
results to output/eval_models/ for comparison. Each position tests
different coaching scenarios (opening, middlegame, tactics, endgame).
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from chess_coach.coaching_templates import generate_position_coaching
from chess_coach.engine import CoachingEngine
from chess_coach.llm.ollama import OllamaProvider
from chess_coach.openings import lookup_fen
from chess_coach.prompts import build_rich_coaching_prompt

# --- Test positions ---
# Each tests a different coaching scenario.

TEST_POSITIONS = [
    {
        "name": "Opening: after 1.e4",
        "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        "level": "beginner",
        "expect_keywords": ["center", "develop", "e5", "d5"],
        "expect_not": ["complex", "unbalanced", "poor coordination"],
    },
    {
        "name": "Italian Game (Bc4, Nf3, Nc6, e5)",
        "fen": "r1bqkb1r/pppppppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
        "level": "intermediate",
        "expect_keywords": ["bishop", "f7", "castle", "center"],
        "expect_not": ["doubled e-pawn"],  # Black doesn't have doubled e-pawns here
    },
    {
        "name": "Middlegame: tactical position",
        "fen": "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/3P1N2/PPP2PPP/RNBQK2R w KQkq - 0 5",
        "level": "intermediate",
        "expect_keywords": ["bishop", "pin", "castle"],
        "expect_not": [],
    },
    {
        "name": "Endgame: K+R vs K+R+P",
        "fen": "8/8/4k3/8/4Pp2/8/5K2/4R3 w - - 0 1",
        "level": "beginner",
        "expect_keywords": ["pawn", "king", "rook"],
        "expect_not": ["opening", "develop", "castle"],
    },
]


@dataclass
class EvalResult:
    model: str
    position_name: str
    fen: str
    level: str
    response: str
    response_len: int
    latency_s: float
    has_expected: list[str]  # which expected keywords were found
    missing_expected: list[str]  # which expected keywords were missing
    has_bad: list[str]  # which "expect_not" keywords were found (bad)
    word_count: int
    opening_name: str | None


def check_keywords(text: str, keywords: list[str]) -> tuple[list[str], list[str]]:
    """Check which keywords appear in text (case-insensitive)."""
    lower = text.lower()
    found = [k for k in keywords if k.lower() in lower]
    missing = [k for k in keywords if k.lower() not in lower]
    return found, missing


def run_template_eval(
    engine: CoachingEngine,
    positions: list[dict],
) -> list[EvalResult]:
    """Evaluate the template engine (no LLM) on the test positions."""
    results = []
    for pos in positions:
        fen = pos["fen"]
        level = pos["level"]
        name = pos["name"]

        print(f"    {name}...", end=" ", flush=True)

        try:
            report = engine.get_position_report(fen, multipv=3)
        except Exception as e:
            print(f"ENGINE ERROR: {e}")
            continue

        opening = lookup_fen(fen)
        t0 = time.perf_counter()
        response = generate_position_coaching(report, level=level, opening=opening)
        latency = time.perf_counter() - t0

        has_expected, missing_expected = check_keywords(response, pos["expect_keywords"])
        has_bad, _ = check_keywords(response, pos["expect_not"])
        word_count = len(response.split())

        result = EvalResult(
            model="template (no LLM)",
            position_name=name,
            fen=fen,
            level=level,
            response=response,
            response_len=len(response),
            latency_s=round(latency, 4),
            has_expected=has_expected,
            missing_expected=missing_expected,
            has_bad=has_bad,
            word_count=word_count,
            opening_name=f"{opening.eco} {opening.name}" if opening else None,
        )
        results.append(result)

        score = len(has_expected)
        total = len(pos["expect_keywords"])
        bad = len(has_bad)
        print(f"{latency:.4f}s | {word_count}w | keywords {score}/{total} | bad {bad}")

    return results


def run_eval(
    engine: CoachingEngine,
    llm: OllamaProvider,
    model_name: str,
    positions: list[dict],
) -> list[EvalResult]:
    results = []
    for pos in positions:
        fen = pos["fen"]
        level = pos["level"]
        name = pos["name"]

        print(f"    {name}...", end=" ", flush=True)

        # Get position report from engine
        try:
            report = engine.get_position_report(fen, multipv=3)
        except Exception as e:
            print(f"ENGINE ERROR: {e}")
            continue

        # Build prompt with opening name
        opening = lookup_fen(fen)
        opening_label = f"{opening.eco} {opening.name}" if opening else None
        prompt = build_rich_coaching_prompt(report, level=level, opening_name=opening_label)

        # Generate coaching text
        t0 = time.perf_counter()
        try:
            response = llm.generate(prompt, max_tokens=512, temperature=0.7)
        except Exception as e:
            print(f"LLM ERROR: {e}")
            continue
        latency = time.perf_counter() - t0

        # Score the response
        has_expected, missing_expected = check_keywords(response, pos["expect_keywords"])
        has_bad, _ = check_keywords(response, pos["expect_not"])
        word_count = len(response.split())

        result = EvalResult(
            model=model_name,
            position_name=name,
            fen=fen,
            level=level,
            response=response,
            response_len=len(response),
            latency_s=round(latency, 1),
            has_expected=has_expected,
            missing_expected=missing_expected,
            has_bad=has_bad,
            word_count=word_count,
            opening_name=opening_label,
        )
        results.append(result)

        score = len(has_expected)
        total = len(pos["expect_keywords"])
        bad = len(has_bad)
        print(f"{latency:.1f}s | {word_count}w | keywords {score}/{total} | bad {bad}")

    return results


def print_summary(all_results: dict[str, list[EvalResult]]) -> None:
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    for model, results in all_results.items():
        total_expected = sum(len(r.has_expected) + len(r.missing_expected) for r in results)
        total_found = sum(len(r.has_expected) for r in results)
        total_bad = sum(len(r.has_bad) for r in results)
        avg_latency = sum(r.latency_s for r in results) / len(results) if results else 0
        avg_words = sum(r.word_count for r in results) / len(results) if results else 0

        print(f"\n  {model}:")
        print(f"    Keywords hit: {total_found}/{total_expected}")
        print(f"    Bad keywords: {total_bad}")
        print(f"    Avg latency:  {avg_latency:.1f}s")
        print(f"    Avg words:    {avg_words:.0f}")


def main() -> None:
    models = sys.argv[1:] if len(sys.argv) > 1 else ["qwen3:1.7b", "qwen3:4b", "qwen3:8b"]

    out_dir = Path("output/eval_models")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Start engine
    path = os.path.expanduser("~/src/fred/blunder/build/rel/blunder")
    engine = CoachingEngine(path, args=["--uci"], ping_timeout=5.0, coaching_timeout=10.0)
    engine.start()

    all_results: dict[str, list[EvalResult]] = {}

    # --- Template engine (no LLM) ---
    print(f"\n{'=' * 50}")
    print("  Model: template (no LLM)")
    print(f"{'=' * 50}")
    template_results = run_template_eval(engine, TEST_POSITIONS)
    all_results["template (no LLM)"] = template_results

    # --- LLM models ---
    for model in models:
        print(f"\n{'=' * 50}")
        print(f"  Model: {model}")
        print(f"{'=' * 50}")

        llm = OllamaProvider(model=model, base_url="http://localhost:11434", timeout=300)

        # Warm up
        print("  Warming up...", end=" ", flush=True)
        t0 = time.perf_counter()
        try:
            llm.generate("Say hi", max_tokens=10, temperature=0.0)
            print(f"{time.perf_counter() - t0:.1f}s")
        except Exception as e:
            print(f"FAILED: {e} — skipping model")
            continue

        results = run_eval(engine, llm, model, TEST_POSITIONS)
        all_results[model] = results

    engine.stop()

    # Print summary
    print_summary(all_results)

    # Save detailed results
    output_file = out_dir / "results.json"
    serializable = {model: [asdict(r) for r in results] for model, results in all_results.items()}
    with open(output_file, "w") as f:
        json.dump(serializable, f, indent=2)
    print(f"\nDetailed results saved to {output_file}")


if __name__ == "__main__":
    main()
