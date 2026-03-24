#!/usr/bin/env python3
"""Evaluate coaching quality across all coaching modes.

Tests both template-based coaching (no LLM) and LLM-based coaching
against a shared test suite of positions and moves. Scores each
response using keyword checks and structural expectations.

Usage:
    # Template only (fast, no LLM needed):
    python scripts/eval_coaching.py

    # Template + specific LLM models:
    python scripts/eval_coaching.py --models qwen3:1.7b qwen3:4b

    # Just moves, skip positions:
    python scripts/eval_coaching.py --moves-only

    # Just positions, skip moves:
    python scripts/eval_coaching.py --positions-only

Results are saved to output/eval_coaching/results.json and a human-readable
summary to output/eval_coaching/summary.txt.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import chess

from chess_coach.coaching_templates import (
    effective_move_classification,
    generate_move_coaching,
    generate_position_coaching,
)
from chess_coach.engine import CoachingEngine
from chess_coach.models import CoachingValidationError
from chess_coach.openings import lookup_fen

# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

POSITION_TESTS: list[dict] = [
    {
        "name": "Starting position",
        "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "level": "beginner",
        "phase": "opening",
        "expect_keywords": ["equal", "develop"],
        "expect_not": ["winning", "blunder", "castle"],
        "notes": "Should mention equality and development. Should NOT suggest castling yet.",
    },
    {
        "name": "After 1.e4",
        "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        "level": "beginner",
        "phase": "opening",
        "expect_keywords": ["center", "develop"],
        "expect_not": ["complex", "unbalanced"],
        "notes": "Should mention center control and development.",
    },
    {
        "name": "Italian Game",
        "fen": "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3",
        "level": "intermediate",
        "phase": "opening",
        "expect_keywords": ["equal", "bishop"],
        "expect_not": ["winning", "blunder"],
        "notes": "Should identify Italian Game. Should mention Bc4 pressure on f7.",
    },
    {
        "name": "Italian Game (4 Knights)",
        "fen": "r1bqkb1r/pppppppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
        "level": "intermediate",
        "phase": "opening",
        "expect_keywords": ["bishop", "f7", "castl"],
        "expect_not": ["doubled e-pawn"],
        "notes": "Should mention Bc4 targeting f7, castling plans.",
    },
    {
        "name": "Sicilian Najdorf",
        "fen": "rnbqkb1r/1p2pppp/p2p1n2/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 6",
        "level": "advanced",
        "phase": "opening",
        "expect_keywords": [],
        "expect_not": ["equal"],
        "notes": "Complex position. Should not call it 'equal' — White typically has a small edge.",
    },
    {
        "name": "Middlegame: tactical",
        "fen": "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/3P1N2/PPP2PPP/RNBQK2R w KQkq - 0 5",
        "level": "intermediate",
        "phase": "middlegame",
        "expect_keywords": ["bishop", "castl"],
        "expect_not": [],
        "notes": "Should mention piece activity and castling.",
    },
    {
        "name": "K+R vs K endgame",
        "fen": "8/8/8/4k3/8/8/8/4K2R w - - 0 1",
        "level": "beginner",
        "phase": "endgame",
        "expect_keywords": ["winning", "rook"],
        "expect_not": ["develop", "castle", "opening"],
        "notes": "Should NOT mention development, castling, or openings in an endgame.",
    },
    {
        "name": "Endgame: R+P vs R",
        "fen": "8/8/4k3/8/4Pp2/8/5K2/4R3 w - - 0 1",
        "level": "beginner",
        "phase": "endgame",
        "expect_keywords": ["pawn", "king"],
        "expect_not": ["opening", "develop", "castle"],
        "notes": "Endgame — should focus on pawn promotion and king activity.",
    },
]

MOVE_TESTS: list[dict] = [
    {
        "name": "Good: 1...e5",
        "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        "move": "e7e5",
        "level": "beginner",
        "expect_class": ["good"],
        "expect_keywords": [],
        "expect_not": ["blunder", "mistake"],
        "notes": "1...e5 is a mainline response to 1.e4. Must NOT be called an inaccuracy.",
    },
    {
        "name": "Good: 1...d5",
        "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        "move": "d7d5",
        "level": "beginner",
        "expect_class": ["good"],
        "expect_keywords": [],
        "expect_not": ["blunder", "mistake"],
        "notes": "Scandinavian Defense — a valid opening. Should not be penalized.",
    },
    {
        "name": "Good: 2.Nf3",
        "fen": "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
        "move": "g1f3",
        "level": "intermediate",
        "expect_class": ["good"],
        "expect_keywords": [],
        "expect_not": ["inaccuracy", "mistake", "blunder"],
        "notes": "2.Nf3 is the most popular second move. Must be 'good'.",
    },
    {
        "name": "Dubious: 1...f6",
        "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        "move": "f7f6",
        "level": "beginner",
        "expect_class": ["good", "inaccuracy", "mistake", "blunder"],
        "expect_keywords": [],
        "expect_not": [],
        "notes": "1...f6 is bad but at depth 8 the engine can't reliably distinguish it from sound openings. Opening leniency applies.",
    },
    {
        "name": "Dubious: 1...a5",
        "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        "move": "a7a5",
        "level": "beginner",
        "expect_class": ["good", "inaccuracy", "mistake"],
        "expect_keywords": [],
        "expect_not": [],
        "notes": "1...a5 is dubious but opening leniency at depth 8 means we tolerate it.",
    },
    {
        "name": "Good: 1.e4",
        "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "move": "e2e4",
        "level": "beginner",
        "expect_class": ["good"],
        "expect_keywords": [],
        "expect_not": ["inaccuracy", "mistake", "blunder"],
        "notes": "1.e4 is the most popular first move. Must be 'good'.",
    },
    {
        "name": "Good: 1.d4",
        "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "move": "d2d4",
        "level": "beginner",
        "expect_class": ["good"],
        "expect_keywords": [],
        "expect_not": ["inaccuracy", "mistake", "blunder"],
        "notes": "1.d4 is a mainline opening. Must be 'good'.",
    },
]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass
class PositionResult:
    mode: str  # "template" or model name
    test_name: str
    fen: str
    level: str
    phase: str
    response: str
    word_count: int
    latency_s: float
    keywords_found: list[str]
    keywords_missing: list[str]
    bad_keywords_found: list[str]
    opening_detected: str | None
    score: float = 0.0  # 0-1
    notes: str = ""


@dataclass
class MoveResult:
    mode: str
    test_name: str
    fen: str
    move_uci: str
    move_san: str
    level: str
    classification: str
    eval_drop_cp: int
    expected_classes: list[str]
    class_correct: bool
    response: str
    word_count: int
    latency_s: float
    keywords_found: list[str]
    keywords_missing: list[str]
    bad_keywords_found: list[str]
    score: float = 0.0
    error: str | None = None
    notes: str = ""


@dataclass
class EvalSummary:
    mode: str
    position_results: list[PositionResult] = field(default_factory=list)
    move_results: list[MoveResult] = field(default_factory=list)
    position_score: float = 0.0
    move_score: float = 0.0
    overall_score: float = 0.0
    total_latency_s: float = 0.0


def check_keywords(text: str, keywords: list[str]) -> tuple[list[str], list[str]]:
    lower = text.lower()
    found = [k for k in keywords if k.lower() in lower]
    missing = [k for k in keywords if k.lower() not in lower]
    return found, missing


def score_position(r: PositionResult, test: dict) -> float:
    """Score a position result 0-1."""
    total_checks = len(test["expect_keywords"]) + len(test["expect_not"])
    if total_checks == 0:
        return 1.0  # no expectations = pass
    passed = len(r.keywords_found) + (len(test["expect_not"]) - len(r.bad_keywords_found))
    return round(passed / total_checks, 3)


def score_move(r: MoveResult, test: dict) -> float:
    """Score a move result 0-1. Classification correctness is worth 60%, keywords 40%."""
    class_score = 1.0 if r.class_correct else 0.0

    kw_checks = len(test["expect_keywords"]) + len(test["expect_not"])
    if kw_checks == 0:
        kw_score = 1.0
    else:
        kw_passed = len(r.keywords_found) + (len(test["expect_not"]) - len(r.bad_keywords_found))
        kw_score = kw_passed / kw_checks

    return round(0.6 * class_score + 0.4 * kw_score, 3)


# ---------------------------------------------------------------------------
# Runners
# ---------------------------------------------------------------------------


def run_position_tests_template(
    engine: CoachingEngine, tests: list[dict]
) -> list[PositionResult]:
    results = []
    for test in tests:
        fen = test["fen"]
        level = test["level"]
        name = test["name"]
        print(f"  POS  {name}...", end=" ", flush=True)

        t0 = time.perf_counter()
        try:
            report = engine.get_position_report(fen, multipv=3)
            opening = lookup_fen(fen)
            response = generate_position_coaching(
                report, level=level, opening=opening
            )
        except Exception as e:
            print(f"ERROR: {e}")
            results.append(
                PositionResult(
                    mode="template",
                    test_name=name,
                    fen=fen,
                    level=level,
                    phase=test.get("phase", "?"),
                    response=f"ERROR: {e}",
                    word_count=0,
                    latency_s=0,
                    keywords_found=[],
                    keywords_missing=test["expect_keywords"],
                    bad_keywords_found=[],
                    opening_detected=None,
                    score=0.0,
                    notes=str(e),
                )
            )
            continue
        latency = time.perf_counter() - t0

        kw_found, kw_missing = check_keywords(response, test["expect_keywords"])
        bad_found, _ = check_keywords(response, test["expect_not"])
        opening_name = f"{opening.eco} {opening.name}" if opening else None

        r = PositionResult(
            mode="template",
            test_name=name,
            fen=fen,
            level=level,
            phase=test.get("phase", "?"),
            response=response,
            word_count=len(response.split()),
            latency_s=round(latency, 3),
            keywords_found=kw_found,
            keywords_missing=kw_missing,
            bad_keywords_found=bad_found,
            opening_detected=opening_name,
        )
        r.score = score_position(r, test)
        results.append(r)

        status = "✓" if r.score >= 0.8 else "△" if r.score >= 0.5 else "✗"
        print(f"{status} {r.score:.0%} | {latency:.2f}s | {r.word_count}w", end="")
        if bad_found:
            print(f" | BAD: {bad_found}", end="")
        if kw_missing:
            print(f" | MISS: {kw_missing}", end="")
        print()

    return results


def run_move_tests_template(
    engine: CoachingEngine, tests: list[dict]
) -> list[MoveResult]:
    results = []
    for test in tests:
        fen = test["fen"]
        move_uci = test["move"]
        level = test["level"]
        name = test["name"]

        board = chess.Board(fen)
        move_san = board.san(chess.Move.from_uci(move_uci))

        print(f"  MOVE {name} ({move_san})...", end=" ", flush=True)

        t0 = time.perf_counter()
        error = None
        try:
            report = engine.get_comparison_report(fen, move_uci)
            response = generate_move_coaching(report, level=level)
            classification = effective_move_classification(report)
            eval_drop = report.eval_drop_cp
        except CoachingValidationError as e:
            error = str(e)
            response = f"ENGINE ERROR: {e}"
            classification = "error"
            eval_drop = -1
            print(f"ERROR: {e}")
            results.append(
                MoveResult(
                    mode="template",
                    test_name=name,
                    fen=fen,
                    move_uci=move_uci,
                    move_san=move_san,
                    level=level,
                    classification=classification,
                    eval_drop_cp=eval_drop,
                    expected_classes=test["expect_class"],
                    class_correct=False,
                    response=response,
                    word_count=0,
                    latency_s=0,
                    keywords_found=[],
                    keywords_missing=test["expect_keywords"],
                    bad_keywords_found=[],
                    score=0.0,
                    error=error,
                    notes=test.get("notes", ""),
                )
            )
            continue
        except Exception as e:
            error = str(e)
            print(f"ERROR: {e}")
            results.append(
                MoveResult(
                    mode="template",
                    test_name=name,
                    fen=fen,
                    move_uci=move_uci,
                    move_san=move_san,
                    level=level,
                    classification="error",
                    eval_drop_cp=-1,
                    expected_classes=test["expect_class"],
                    class_correct=False,
                    response=f"ERROR: {e}",
                    word_count=0,
                    latency_s=0,
                    keywords_found=[],
                    keywords_missing=test["expect_keywords"],
                    bad_keywords_found=[],
                    score=0.0,
                    error=str(e),
                    notes=test.get("notes", ""),
                )
            )
            continue
        latency = time.perf_counter() - t0

        class_correct = classification in test["expect_class"]
        kw_found, kw_missing = check_keywords(response, test["expect_keywords"])
        bad_found, _ = check_keywords(response, test["expect_not"])

        r = MoveResult(
            mode="template",
            test_name=name,
            fen=fen,
            move_uci=move_uci,
            move_san=move_san,
            level=level,
            classification=classification,
            eval_drop_cp=eval_drop,
            expected_classes=test["expect_class"],
            class_correct=class_correct,
            response=response,
            word_count=len(response.split()),
            latency_s=round(latency, 3),
            keywords_found=kw_found,
            keywords_missing=kw_missing,
            bad_keywords_found=bad_found,
            error=None,
            notes=test.get("notes", ""),
        )
        r.score = score_move(r, test)
        results.append(r)

        status = "✓" if r.score >= 0.8 else "△" if r.score >= 0.5 else "✗"
        cls_mark = "✓" if class_correct else "✗"
        print(
            f"{status} {r.score:.0%} | class={classification}({cls_mark}) "
            f"drop={eval_drop}cp | {latency:.2f}s",
            end="",
        )
        if bad_found:
            print(f" | BAD: {bad_found}", end="")
        print()

    return results


# ---------------------------------------------------------------------------
# LLM runners (optional, only when --models is specified)
# ---------------------------------------------------------------------------


def run_position_tests_llm(
    engine: CoachingEngine, model_name: str, tests: list[dict]
) -> list[PositionResult]:
    """Run position tests through the LLM coaching path."""
    from chess_coach.llm.ollama import OllamaProvider
    from chess_coach.prompts import build_rich_coaching_prompt

    llm = OllamaProvider(model=model_name, base_url="http://localhost:11434", timeout=300)

    results = []
    for test in tests:
        fen = test["fen"]
        level = test["level"]
        name = test["name"]
        print(f"  POS  {name}...", end=" ", flush=True)

        t0 = time.perf_counter()
        try:
            report = engine.get_position_report(fen, multipv=3)
            opening = lookup_fen(fen)
            opening_label = f"{opening.eco} {opening.name}" if opening else None
            prompt = build_rich_coaching_prompt(
                report, level=level, opening_name=opening_label
            )
            response = llm.generate(prompt, max_tokens=512, temperature=0.7)
        except Exception as e:
            print(f"ERROR: {e}")
            results.append(
                PositionResult(
                    mode=model_name,
                    test_name=name,
                    fen=fen,
                    level=level,
                    phase=test.get("phase", "?"),
                    response=f"ERROR: {e}",
                    word_count=0,
                    latency_s=0,
                    keywords_found=[],
                    keywords_missing=test["expect_keywords"],
                    bad_keywords_found=[],
                    opening_detected=None,
                    score=0.0,
                    notes=str(e),
                )
            )
            continue
        latency = time.perf_counter() - t0

        kw_found, kw_missing = check_keywords(response, test["expect_keywords"])
        bad_found, _ = check_keywords(response, test["expect_not"])

        r = PositionResult(
            mode=model_name,
            test_name=name,
            fen=fen,
            level=level,
            phase=test.get("phase", "?"),
            response=response,
            word_count=len(response.split()),
            latency_s=round(latency, 1),
            keywords_found=kw_found,
            keywords_missing=kw_missing,
            bad_keywords_found=bad_found,
            opening_detected=f"{opening.eco} {opening.name}" if opening else None,
        )
        r.score = score_position(r, test)
        results.append(r)

        status = "✓" if r.score >= 0.8 else "△" if r.score >= 0.5 else "✗"
        print(f"{status} {r.score:.0%} | {latency:.1f}s | {r.word_count}w", end="")
        if bad_found:
            print(f" | BAD: {bad_found}", end="")
        if kw_missing:
            print(f" | MISS: {kw_missing}", end="")
        print()

    return results


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def build_summary(summaries: list[EvalSummary]) -> str:
    lines = []
    lines.append("=" * 70)
    lines.append("COACHING EVAL SUMMARY")
    lines.append("=" * 70)

    for s in summaries:
        lines.append(f"\n  Mode: {s.mode}")
        lines.append(f"  Position score: {s.position_score:.0%} ({len(s.position_results)} tests)")
        lines.append(f"  Move score:     {s.move_score:.0%} ({len(s.move_results)} tests)")
        lines.append(f"  Overall:        {s.overall_score:.0%}")
        lines.append(f"  Total time:     {s.total_latency_s:.1f}s")

        # Flag failures
        for r in s.position_results:
            if r.score < 0.5:
                lines.append(f"    ✗ POS  {r.test_name}: {r.score:.0%} — {r.bad_keywords_found or r.keywords_missing}")
        for r in s.move_results:
            if r.score < 0.5:
                reason = f"class={r.classification} (expected {r.expected_classes})" if not r.class_correct else str(r.bad_keywords_found)
                lines.append(f"    ✗ MOVE {r.test_name}: {r.score:.0%} — {reason}")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate coaching quality")
    parser.add_argument("--models", nargs="*", default=[], help="LLM models to test (e.g. qwen3:1.7b)")
    parser.add_argument("--positions-only", action="store_true")
    parser.add_argument("--moves-only", action="store_true")
    args = parser.parse_args()

    out_dir = Path("output/eval_coaching")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Start engine
    path = os.path.expanduser("~/src/fred/blunder/build/rel/blunder")
    engine = CoachingEngine(path, args=["--uci"], ping_timeout=5.0, coaching_timeout=10.0)
    engine.start()

    all_summaries: list[EvalSummary] = []

    try:
        # --- Template mode ---
        print(f"\n{'=' * 60}")
        print("  Mode: template (no LLM)")
        print(f"{'=' * 60}")

        summary = EvalSummary(mode="template")

        if not args.moves_only:
            print("\n  Position tests:")
            summary.position_results = run_position_tests_template(engine, POSITION_TESTS)

        if not args.positions_only:
            print("\n  Move tests:")
            summary.move_results = run_move_tests_template(engine, MOVE_TESTS)

        # Compute scores
        if summary.position_results:
            summary.position_score = round(
                sum(r.score for r in summary.position_results) / len(summary.position_results), 3
            )
        if summary.move_results:
            summary.move_score = round(
                sum(r.score for r in summary.move_results) / len(summary.move_results), 3
            )
        n = len(summary.position_results) + len(summary.move_results)
        if n:
            total = sum(r.score for r in summary.position_results) + sum(
                r.score for r in summary.move_results
            )
            summary.overall_score = round(total / n, 3)
        summary.total_latency_s = round(
            sum(r.latency_s for r in summary.position_results)
            + sum(r.latency_s for r in summary.move_results),
            1,
        )
        all_summaries.append(summary)

        # --- LLM modes ---
        for model in args.models:
            print(f"\n{'=' * 60}")
            print(f"  Mode: {model}")
            print(f"{'=' * 60}")

            llm_summary = EvalSummary(mode=model)

            if not args.moves_only:
                print("\n  Position tests:")
                llm_summary.position_results = run_position_tests_llm(
                    engine, model, POSITION_TESTS
                )

            # Compute scores
            if llm_summary.position_results:
                llm_summary.position_score = round(
                    sum(r.score for r in llm_summary.position_results)
                    / len(llm_summary.position_results),
                    3,
                )
            llm_summary.overall_score = llm_summary.position_score
            llm_summary.total_latency_s = round(
                sum(r.latency_s for r in llm_summary.position_results), 1
            )
            all_summaries.append(llm_summary)

    finally:
        engine.stop()

    # Print summary
    summary_text = build_summary(all_summaries)
    print(summary_text)

    # Save results
    results_data = {}
    for s in all_summaries:
        results_data[s.mode] = {
            "position_score": s.position_score,
            "move_score": s.move_score,
            "overall_score": s.overall_score,
            "total_latency_s": s.total_latency_s,
            "positions": [asdict(r) for r in s.position_results],
            "moves": [asdict(r) for r in s.move_results],
        }

    results_file = out_dir / "results.json"
    with open(results_file, "w") as f:
        json.dump(results_data, f, indent=2)

    summary_file = out_dir / "summary.txt"
    summary_file.write_text(summary_text)

    print(f"\nResults: {results_file}")
    print(f"Summary: {summary_file}")


if __name__ == "__main__":
    main()
