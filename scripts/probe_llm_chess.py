#!/usr/bin/env python3
"""Probe LLM chess knowledge — exploration script.

Tests whether a local LLM (via Ollama) can provide useful chess coaching
by running it through a set of positions with different prompt styles.

The goal is NOT automated scoring — it's generating outputs for human
review to understand what the model can and can't do.

Usage:
    # Default model (qwen3:8b):
    python scripts/probe_llm_chess.py

    # Specific model:
    python scripts/probe_llm_chess.py --model qwen3:4b

    # With engine data (requires Blunder engine running):
    python scripts/probe_llm_chess.py --with-engine

    # Quick mode (fewer positions):
    python scripts/probe_llm_chess.py --quick

Output: output/llm_probe/probe_results.md (human-readable review file)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import chess

from chess_coach.llm.ollama import OllamaProvider

# ---------------------------------------------------------------------------
# Test positions — each designed to test a specific aspect of chess knowledge
# ---------------------------------------------------------------------------

PROBE_POSITIONS: list[dict] = [
    {
        "id": "quiet_opening",
        "name": "Quiet opening — can it give useful general advice?",
        "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        "what_to_look_for": [
            "Does it suggest reasonable responses (e5, c5, e6, d5)?",
            "Does it mention center control?",
            "Does it give actionable advice vs generic fluff?",
            "Does it hallucinate pieces or squares?",
        ],
    },
    {
        "id": "hanging_piece",
        "name": "Hanging piece — does it spot undefended material?",
        "fen": "r1bqkb1r/pppppppp/2n5/4N3/4n3/8/PPPP1PPP/RNBQKB1R w KQkq - 0 4",
        "what_to_look_for": [
            "Does it notice the knight on e4 is undefended?",
            "Does it notice the knight on e5 is in the center?",
            "Does it suggest capturing or defending?",
            "Does it correctly identify which pieces are where?",
        ],
    },
    {
        "id": "tactical_fork",
        "name": "Knight fork — can it explain a tactic?",
        "fen": "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4",
        "what_to_look_for": [
            "Does it see Qxf7# (Scholar's mate)?",
            "Or at least that Qh5 threatens f7?",
            "Does it correctly read the board from the FEN?",
            "Does it invent threats that don't exist?",
        ],
    },
    {
        "id": "after_blunder",
        "name": "After a blunder — can it explain WHY a move is bad?",
        "fen": "rnbqkbnr/ppppp1pp/5p2/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
        "context": "Black just played 1...f6. This weakens the e8-h5 diagonal and blocks the knight from f6.",
        "what_to_look_for": [
            "Does it explain the diagonal weakness (e8-h5)?",
            "Does it mention that f6 blocks the knight?",
            "Does it suggest Qh5+ as a punishing idea?",
            "Or does it just say 'bad move' without explaining why?",
        ],
    },
    {
        "id": "endgame",
        "name": "K+R vs K endgame — does it give endgame-appropriate advice?",
        "fen": "8/8/8/4k3/8/8/8/4K2R w - - 0 1",
        "what_to_look_for": [
            "Does it recognize this is a basic winning endgame?",
            "Does it mention the technique (push king to edge)?",
            "Does it avoid mentioning development, castling, openings?",
            "Does it know the rook + king vs king technique?",
        ],
    },
    {
        "id": "complex_middlegame",
        "name": "Complex middlegame — can it prioritize what matters?",
        "fen": "r1b2rk1/pp1nqppp/2pbpn2/3p4/2PP4/2NBPN2/PP2QPPP/R1B2RK1 w - - 0 10",
        "what_to_look_for": [
            "Does it identify the key tension (d4/d5 pawn structure)?",
            "Does it suggest a plan (e4 break, minority attack, etc)?",
            "Does it prioritize 1-2 ideas or dump everything?",
            "Is the advice actionable or just descriptive?",
        ],
    },
]

# Quick subset for --quick mode
QUICK_POSITIONS = ["quiet_opening", "hanging_piece", "after_blunder"]

# ---------------------------------------------------------------------------
# Prompt styles — testing different ways to ask the LLM
# ---------------------------------------------------------------------------


def prompt_bare_fen(pos: dict) -> str:
    """Style A: Just the FEN, no engine data. Tests raw chess knowledge."""
    fen = pos["fen"]
    board = chess.Board(fen)
    side = "White" if board.turn == chess.WHITE else "Black"
    return f"""\
You are a chess coach. Here is a position (FEN notation):

{fen}

It is {side}'s turn to move.

What should {side} focus on in this position? Give specific, actionable advice.
Keep your response under 150 words."""


def prompt_with_board(pos: dict) -> str:
    """Style B: FEN + ASCII board. Tests if visual representation helps."""
    fen = pos["fen"]
    board = chess.Board(fen)
    side = "White" if board.turn == chess.WHITE else "Black"
    ascii_board = str(board)
    return f"""\
You are a chess coach. Here is a position:

FEN: {fen}

Board:
{ascii_board}

It is {side}'s turn to move.

What should {side} focus on? What are the key features of this position?
Give specific, actionable coaching advice. Keep it under 150 words."""


def prompt_with_context(pos: dict) -> str:
    """Style C: FEN + context about what just happened. Tests reasoning."""
    fen = pos["fen"]
    board = chess.Board(fen)
    side = "White" if board.turn == chess.WHITE else "Black"
    context = pos.get("context", "")
    context_line = f"\nContext: {context}\n" if context else ""
    return f"""\
You are a chess coach helping a beginner improve.

Position (FEN): {fen}
{context_line}
It is {side}'s turn.

Explain the most important thing about this position. Why does it matter?
What should {side} do and why? Be specific — mention squares and pieces.
Keep it under 150 words."""


def prompt_structured_task(pos: dict) -> str:
    """Style D: Structured task — tests if the model can follow instructions."""
    fen = pos["fen"]
    board = chess.Board(fen)
    side = "White" if board.turn == chess.WHITE else "Black"
    return f"""\
You are a chess coach. Analyze this position and respond with EXACTLY \
these sections:

Position (FEN): {fen}
Side to move: {side}

1. ASSESSMENT: Is the position equal, or does one side have an advantage? Why?
2. KEY FEATURE: What is the single most important thing about this position?
3. ADVICE: What should {side} do right now? Name a specific plan or move idea.
4. WARNING: What should {side} watch out for?

Be concrete — mention specific squares and pieces. Under 150 words total."""


PROMPT_STYLES = {
    "A_bare_fen": ("Bare FEN only", prompt_bare_fen),
    "B_with_board": ("FEN + ASCII board", prompt_with_board),
    "C_with_context": ("FEN + context", prompt_with_context),
    "D_structured": ("Structured task", prompt_structured_task),
}

# ---------------------------------------------------------------------------
# Factual checks — automated sanity checks on the output
# ---------------------------------------------------------------------------


def check_piece_hallucinations(fen: str, response: str) -> list[str]:
    """Check if the LLM mentions pieces on squares where they don't exist.

    This is a basic hallucination detector — not exhaustive, but catches
    the most common errors like "the bishop on e4" when there's no bishop there.

    Only flags placement claims ("piece on square"). Skips:
    - Influence verbs: "controlling", "targeting", "attacking", "defending"
    - Square assessments: "weak square X", "strong square X"
    """
    import re

    board = chess.Board(fen)
    issues: list[str] = []
    response_lower = response.lower()

    piece_names = {
        "pawn": chess.PAWN,
        "knight": chess.KNIGHT,
        "bishop": chess.BISHOP,
        "rook": chess.ROOK,
        "queen": chess.QUEEN,
        "king": chess.KING,
    }

    # Pre-filter: collect squares mentioned in "weak square X" / "strong square X"
    # patterns — these are square assessments, not placement claims.
    square_assessment_pattern = r"(?:weak|strong)\s+square\s+([a-h][1-8])"
    assessment_squares: set[tuple[int, int]] = set()
    for m in re.finditer(square_assessment_pattern, response_lower):
        # Store (start, end) of the full match so we can skip overlapping placement matches
        assessment_squares.add((m.start(), m.end()))

    # Influence verbs — if these appear in the ~30 chars before a "piece on square"
    # match, the sentence is about square control, not piece placement.
    influence_verbs = ("controlling", "targeting", "attacking", "defending")

    # Look for placement claims: "knight on e4", "bishop on c4", etc.
    for piece_name, piece_type in piece_names.items():
        pattern = rf"{piece_name}\s+on\s+([a-h][1-8])"
        for match in re.finditer(pattern, response_lower):
            square_name = match.group(1)

            # Skip if this match overlaps with a square assessment phrase
            match_overlaps_assessment = any(
                a_start <= match.start() <= a_end or a_start <= match.end() <= a_end
                for a_start, a_end in assessment_squares
            )
            if match_overlaps_assessment:
                continue

            # Skip if an influence verb appears in the ~30 chars before the match
            context_start = max(0, match.start() - 30)
            preceding_text = response_lower[context_start : match.start()]
            if any(verb in preceding_text for verb in influence_verbs):
                continue

            try:
                sq = chess.parse_square(square_name)
                actual = board.piece_at(sq)
                if actual is None:
                    issues.append(f"HALLUCINATION: claims {piece_name} on {square_name} — square is empty")
                elif actual.piece_type != piece_type:
                    actual_name = chess.piece_name(actual.piece_type)
                    issues.append(f"HALLUCINATION: claims {piece_name} on {square_name} — actually a {actual_name}")
            except ValueError:
                pass

    return issues


def check_move_validity(fen: str, response: str) -> list[str]:
    """Check if any moves mentioned in the response are actually legal."""
    board = chess.Board(fen)
    issues: list[str] = []

    import re

    # Look for SAN-like moves (e.g., Nf3, Bxf7, O-O, e4)
    san_pattern = r"\b([KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?|O-O(?:-O)?)\b"
    for match in re.finditer(san_pattern, response):
        move_str = match.group(1)
        try:
            move = board.parse_san(move_str)
            if move not in board.legal_moves:
                issues.append(f"ILLEGAL MOVE: {move_str} is not legal in this position")
        except (ValueError, chess.InvalidMoveError, chess.AmbiguousMoveError):
            # Could be a reference to a future move or notation we can't parse
            pass

    return issues


# ---------------------------------------------------------------------------
# Engine-assisted prompts (optional, requires Blunder)
# ---------------------------------------------------------------------------


def prompt_with_engine_data(pos: dict, report_dict: dict) -> str:
    """Style E: FEN + full engine data. Tests if engine data improves output."""
    fen = pos["fen"]
    board = chess.Board(fen)
    side = "White" if board.turn == chess.WHITE else "Black"

    # Format engine data sections
    sections = []

    eb = report_dict.get("eval_breakdown", {})
    sections.append(
        f"--- Eval Breakdown ---\n"
        f"Overall: {report_dict.get('eval_cp', '?')}cp\n"
        f"Material: {eb.get('material', '?')}cp\n"
        f"Mobility: {eb.get('mobility', '?')}cp\n"
        f"King safety: {eb.get('king_safety', '?')}cp\n"
        f"Pawn structure: {eb.get('pawn_structure', '?')}cp"
    )

    # Hanging pieces
    hanging = []
    for side_key in ("white", "black"):
        for hp in report_dict.get("hanging_pieces", {}).get(side_key, []):
            hanging.append(f"{side_key.title()}'s {hp['piece']} on {hp['square']}")
    if hanging:
        sections.append("--- Hanging Pieces ---\n" + "\n".join(hanging))

    # Tactics
    tactics = report_dict.get("tactics", [])
    if tactics:
        tac_lines = [f"- {t['type']}: {t['description']}" for t in tactics]
        sections.append("--- Tactics ---\n" + "\n".join(tac_lines))

    # Top lines
    top_lines = report_dict.get("top_lines", [])
    if top_lines:
        pv_lines = []
        for i, line in enumerate(top_lines[:3]):
            moves = " ".join(line.get("moves", [])[:5])
            pv_lines.append(f"Line {i + 1}: {moves} (eval: {line.get('eval_cp', '?')}cp)")
        sections.append("--- Top Engine Lines ---\n" + "\n".join(pv_lines))

    engine_data = "\n\n".join(sections)

    return f"""\
You are a chess coach. You are given a position with engine analysis data.

Position (FEN): {fen}
Side to move: {side}

Engine Analysis:
{engine_data}

Using the engine data above, explain this position to a beginner.
Focus on the most important thing first. Be specific — mention squares
and pieces. Keep it under 150 words.

IMPORTANT: Only use information from the engine data. Do not invent
analysis or claim things not supported by the data."""


def prompt_template_rephrase(pos: dict, template_text: str) -> str:
    """Style F: Rephrase template output. Tests pure rephrasing ability."""
    return f"""\
You are a friendly chess coach. Below is a factual analysis of a chess \
position. Your job is to rephrase it in a warm, encouraging tone suitable \
for a beginner. Do NOT add new chess analysis or change the facts — just \
make it sound more natural and helpful.

Factual analysis:
{template_text}

Rephrase the above for a beginner. Keep the same information but make it \
sound like a friendly coach talking to a student. Under 150 words."""


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


@dataclass
class ProbeResult:
    """Result of one probe (one position × one prompt style)."""

    position_id: str
    position_name: str
    prompt_style: str
    prompt_style_desc: str
    prompt: str
    response: str
    latency_s: float
    hallucinations: list[str] = field(default_factory=list)
    move_issues: list[str] = field(default_factory=list)


def run_probe(
    llm: OllamaProvider,
    positions: list[dict],
    styles: dict[str, tuple[str, object]],
    max_tokens: int = 512,
    temperature: float = 0.7,
) -> list[ProbeResult]:
    """Run all positions through all prompt styles."""
    results: list[ProbeResult] = []

    total = len(positions) * len(styles)
    count = 0

    for pos in positions:
        for style_key, (style_desc, style_fn) in styles.items():
            count += 1
            print(f"  [{count}/{total}] {pos['id']} × {style_key}...", end=" ", flush=True)

            prompt = style_fn(pos)
            t0 = time.perf_counter()
            try:
                response = llm.generate(prompt, max_tokens=max_tokens, temperature=temperature)
            except Exception as e:
                response = f"ERROR: {e}"
            t1 = time.perf_counter()

            # Run automated checks
            hallucinations = check_piece_hallucinations(pos["fen"], response)
            move_issues = check_move_validity(pos["fen"], response)

            latency = round(t1 - t0, 1)
            print(f"{latency}s, {len(response)} chars", end="")
            if hallucinations:
                print(f", ⚠ {len(hallucinations)} hallucination(s)", end="")
            print()

            results.append(
                ProbeResult(
                    position_id=pos["id"],
                    position_name=pos["name"],
                    prompt_style=style_key,
                    prompt_style_desc=style_desc,
                    prompt=prompt,
                    response=response,
                    latency_s=latency,
                    hallucinations=hallucinations,
                    move_issues=move_issues,
                )
            )

    return results


def run_engine_probes(
    llm: OllamaProvider,
    positions: list[dict],
    max_tokens: int = 512,
    temperature: float = 0.7,
) -> list[ProbeResult]:
    """Run positions through engine-assisted prompt styles (E and F).

    Requires the Blunder engine with coaching protocol.
    """
    import os

    from chess_coach.coaching_templates import generate_position_coaching
    from chess_coach.engine import CoachingEngine

    path = os.path.expanduser("~/src/fred/blunder/build/rel/blunder")
    if not os.path.exists(path):
        print(f"  Engine not found at {path} — skipping engine probes")
        return []

    print("  Starting engine...")
    engine = CoachingEngine(path, args=["--uci"], ping_timeout=5.0, coaching_timeout=10.0)
    engine.start()

    results: list[ProbeResult] = []
    total = len(positions) * 2  # styles E and F

    try:
        count = 0
        for pos in positions:
            fen = pos["fen"]

            # Get engine report
            print(f"  Analyzing {pos['id']}...", end=" ", flush=True)
            t0 = time.perf_counter()
            try:
                report = engine.get_position_report(fen, multipv=3)
                report_dict = report.to_dict()
                t1 = time.perf_counter()
                print(f"engine {t1 - t0:.1f}s")
            except Exception as e:
                print(f"engine error: {e}")
                continue

            # Style E: with engine data
            count += 1
            print(f"  [{count}/{total}] {pos['id']} × E_with_engine...", end=" ", flush=True)
            prompt_e = prompt_with_engine_data(pos, report_dict)
            t0 = time.perf_counter()
            try:
                response_e = llm.generate(prompt_e, max_tokens=max_tokens, temperature=temperature)
            except Exception as e:
                response_e = f"ERROR: {e}"
            t1 = time.perf_counter()
            latency_e = round(t1 - t0, 1)
            hallucinations_e = check_piece_hallucinations(fen, response_e)
            print(f"{latency_e}s, {len(response_e)} chars", end="")
            if hallucinations_e:
                print(f", ⚠ {len(hallucinations_e)} hallucination(s)", end="")
            print()
            results.append(
                ProbeResult(
                    position_id=pos["id"],
                    position_name=pos["name"],
                    prompt_style="E_with_engine",
                    prompt_style_desc="FEN + engine data",
                    prompt=prompt_e,
                    response=response_e,
                    latency_s=latency_e,
                    hallucinations=hallucinations_e,
                    move_issues=check_move_validity(fen, response_e),
                )
            )

            # Style F: template rephrase
            count += 1
            print(f"  [{count}/{total}] {pos['id']} × F_rephrase...", end=" ", flush=True)
            template_text = generate_position_coaching(report, level="beginner")
            prompt_f = prompt_template_rephrase(pos, template_text)
            t0 = time.perf_counter()
            try:
                response_f = llm.generate(prompt_f, max_tokens=max_tokens, temperature=temperature)
            except Exception as e:
                response_f = f"ERROR: {e}"
            t1 = time.perf_counter()
            latency_f = round(t1 - t0, 1)
            hallucinations_f = check_piece_hallucinations(fen, response_f)
            print(f"{latency_f}s, {len(response_f)} chars", end="")
            if hallucinations_f:
                print(f", ⚠ {len(hallucinations_f)} hallucination(s)", end="")
            print()
            results.append(
                ProbeResult(
                    position_id=pos["id"],
                    position_name=pos["name"],
                    prompt_style="F_rephrase",
                    prompt_style_desc="Template rephrase",
                    prompt=prompt_f,
                    response=response_f,
                    latency_s=latency_f,
                    hallucinations=hallucinations_f,
                    move_issues=check_move_validity(fen, response_f),
                )
            )
    finally:
        engine.stop()

    return results


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_report(
    results: list[ProbeResult],
    model: str,
    positions: list[dict],
) -> str:
    """Generate a human-readable markdown report for review."""
    lines: list[str] = []
    lines.append(f"# LLM Chess Knowledge Probe — {model}")
    lines.append(f"\nGenerated: {time.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"Model: {model}")
    lines.append(f"Positions tested: {len(positions)}")
    lines.append(f"Total probes: {len(results)}")

    # Summary stats
    total_hallucinations = sum(len(r.hallucinations) for r in results)
    total_latency = sum(r.latency_s for r in results)
    lines.append(f"\nTotal hallucinations detected: {total_hallucinations}")
    lines.append(f"Total time: {total_latency:.0f}s")

    # Per-style summary
    lines.append("\n## Summary by Prompt Style\n")
    lines.append("| Style | Avg Latency | Hallucinations | Avg Length |")
    lines.append("|-------|-------------|----------------|------------|")
    style_groups: dict[str, list[ProbeResult]] = {}
    for r in results:
        style_groups.setdefault(r.prompt_style, []).append(r)
    for style_key, group in sorted(style_groups.items()):
        avg_lat = sum(r.latency_s for r in group) / len(group)
        total_hal = sum(len(r.hallucinations) for r in group)
        avg_len = sum(len(r.response) for r in group) / len(group)
        desc = group[0].prompt_style_desc
        lines.append(f"| {desc} | {avg_lat:.1f}s | {total_hal} | {avg_len:.0f} chars |")

    # Detailed results grouped by position
    lines.append("\n---\n")
    lines.append("## Detailed Results\n")

    for pos in positions:
        pos_results = [r for r in results if r.position_id == pos["id"]]
        if not pos_results:
            continue

        lines.append(f"\n### {pos['name']}")
        lines.append(f"\nFEN: `{pos['fen']}`")

        # Show the board
        board = chess.Board(pos["fen"])
        lines.append(f"\n```\n{board}\n```")

        lines.append("\n**What to look for:**")
        for item in pos.get("what_to_look_for", []):
            lines.append(f"- {item}")

        for r in pos_results:
            lines.append(f"\n#### Style: {r.prompt_style_desc} ({r.latency_s}s)")

            if r.hallucinations:
                lines.append("\n⚠️ **Hallucinations detected:**")
                for h in r.hallucinations:
                    lines.append(f"- {h}")

            if r.move_issues:
                lines.append("\n⚠️ **Move issues:**")
                for m in r.move_issues:
                    lines.append(f"- {m}")

            lines.append(f"\n**Response:**\n")
            lines.append(f"> {r.response.strip()}")

            lines.append("")  # blank line

    # Grading section (for human reviewer)
    lines.append("\n---\n")
    lines.append("## Your Assessment\n")
    lines.append("For each position, rate the responses:\n")
    lines.append("| Position | Best Style | Notes |")
    lines.append("|----------|-----------|-------|")
    for pos in positions:
        lines.append(f"| {pos['id']} | | |")

    lines.append("\n### Overall Questions\n")
    lines.append("1. Does the model add value over templates?")
    lines.append("2. Which prompt style produces the best results?")
    lines.append("3. What kinds of mistakes does it make?")
    lines.append("4. Is the model's chess knowledge sufficient for coaching?")
    lines.append("5. Would a different model be worth trying?")

    return "\n".join(lines)


def generate_comparison_report(
    all_model_results: dict[str, list[ProbeResult]],
    positions: list[dict],
) -> str:
    """Generate a cross-model comparison report."""
    lines: list[str] = []
    models = list(all_model_results.keys())
    lines.append("# LLM Chess Coaching — Model Comparison")
    lines.append(f"\nGenerated: {time.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"Models tested: {', '.join(models)}")
    lines.append(f"Positions: {len(positions)}")

    # Overall comparison table
    lines.append("\n## Overall Comparison\n")
    lines.append("| Model | Probes | Hallucinations | Avg Latency | Avg Length |")
    lines.append("|-------|--------|----------------|-------------|------------|")
    for model, results in all_model_results.items():
        n = len(results)
        hal = sum(len(r.hallucinations) for r in results)
        avg_lat = sum(r.latency_s for r in results) / n if n else 0
        avg_len = sum(len(r.response) for r in results) / n if n else 0
        lines.append(f"| {model} | {n} | {hal} | {avg_lat:.1f}s | {avg_len:.0f} chars |")

    # Per-style comparison
    all_styles = set()
    for results in all_model_results.values():
        for r in results:
            all_styles.add(r.prompt_style)

    lines.append("\n## Hallucinations by Style\n")
    header = "| Style |" + " | ".join(models) + " |"
    sep = "|-------|" + " | ".join(["---"] * len(models)) + " |"
    lines.append(header)
    lines.append(sep)
    for style in sorted(all_styles):
        row = f"| {style} |"
        for model in models:
            results = all_model_results[model]
            style_results = [r for r in results if r.prompt_style == style]
            hal = sum(len(r.hallucinations) for r in style_results)
            row += f" {hal} |"
        lines.append(row)

    # Per-style latency comparison
    lines.append("\n## Avg Latency by Style (seconds)\n")
    lines.append(header)
    lines.append(sep)
    for style in sorted(all_styles):
        row = f"| {style} |"
        for model in models:
            results = all_model_results[model]
            style_results = [r for r in results if r.prompt_style == style]
            avg = sum(r.latency_s for r in style_results) / len(style_results) if style_results else 0
            row += f" {avg:.1f}s |"
        lines.append(row)

    # Side-by-side responses for each position × style E (engine data)
    lines.append("\n---\n")
    lines.append("## Side-by-Side: Style E (FEN + engine data)\n")
    lines.append("This is the most important comparison — how each model handles structured engine data.\n")

    for pos in positions:
        lines.append(f"\n### {pos['name']}\n")
        board = chess.Board(pos["fen"])
        lines.append(f"```\n{board}\n```\n")

        for model in models:
            results = all_model_results[model]
            e_results = [r for r in results if r.position_id == pos["id"] and r.prompt_style == "E_with_engine"]
            if e_results:
                r = e_results[0]
                hal_note = f" ⚠️ {len(r.hallucinations)} hallucination(s)" if r.hallucinations else ""
                lines.append(f"**{model}** ({r.latency_s}s{hal_note}):")
                lines.append(f"> {r.response.strip()}\n")
            else:
                lines.append(f"**{model}**: (no engine probe)\n")

    # Verdict section
    lines.append("\n---\n")
    lines.append("## Your Verdict\n")
    lines.append("| Model | Quality (1-5) | Speed (1-5) | Hallucinations | Would Use? | Notes |")
    lines.append("|-------|--------------|-------------|----------------|------------|-------|")
    for model in models:
        lines.append(f"| {model} | | | | | |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe LLM chess knowledge")
    parser.add_argument(
        "--model", nargs="+", default=["qwen3:8b"], help="Ollama model name(s). Pass multiple to compare."
    )
    parser.add_argument("--base-url", default="http://localhost:11434", help="Ollama base URL")
    parser.add_argument("--with-engine", action="store_true", help="Include engine-assisted probes (E, F)")
    parser.add_argument(
        "--engine-only", action="store_true", help="Only run engine-assisted probes (E, F) — skip styles A-D"
    )
    parser.add_argument("--quick", action="store_true", help="Run only 3 positions")
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--max-tokens", type=int, default=512)
    args = parser.parse_args()

    out_dir = Path("output/llm_probe")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Select positions
    if args.quick:
        positions = [p for p in PROBE_POSITIONS if p["id"] in QUICK_POSITIONS]
    else:
        positions = PROBE_POSITIONS

    models = args.model
    multi_model = len(models) > 1

    print(f"LLM Chess Knowledge Probe")
    print(f"Models: {', '.join(models)}")
    print(f"Positions: {len(positions)}")
    if args.engine_only:
        print(f"Prompt styles: E + F (engine-only mode)")
    else:
        print(f"Prompt styles: {len(PROMPT_STYLES)}" + (" + 2 engine" if args.with_engine or args.engine_only else ""))
    print()

    all_model_results: dict[str, list[ProbeResult]] = {}

    for model in models:
        print(f"\n{'=' * 60}")
        print(f"  Model: {model}")
        print(f"{'=' * 60}\n")

        # Connect to Ollama
        llm = OllamaProvider(model=model, base_url=args.base_url, timeout=300.0)
        if not llm.is_available():
            print(f"  WARNING: Model {model} not available — skipping")
            continue

        results: list[ProbeResult] = []

        # Run basic probes (no engine needed) — skip if engine-only
        if not args.engine_only:
            print(f"  Running basic probes (styles A-D)...")
            results = run_probe(
                llm,
                positions,
                PROMPT_STYLES,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
            )

        # Run engine-assisted probes if requested
        if args.with_engine or args.engine_only:
            print(f"\n  Running engine-assisted probes (styles E-F)...")
            engine_results = run_engine_probes(
                llm,
                positions,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
            )
            results.extend(engine_results)

        all_model_results[model] = results

        # Generate per-model report
        report = generate_report(results, model, positions)
        safe_name = model.replace(":", "_").replace("/", "_")
        report_file = out_dir / f"probe_{safe_name}.md"
        report_file.write_text(report)

        # Print per-model summary
        total_hal = sum(len(r.hallucinations) for r in results)
        total_time = sum(r.latency_s for r in results)
        print(f"\n  {model}: {len(results)} probes, {total_hal} hallucinations, {total_time:.0f}s")
        print(f"  Report: {report_file}")

    # Save raw data for all models
    raw_data = {}
    for model, results in all_model_results.items():
        raw_data[model] = [
            {
                "position_id": r.position_id,
                "prompt_style": r.prompt_style,
                "prompt": r.prompt,
                "response": r.response,
                "latency_s": r.latency_s,
                "hallucinations": r.hallucinations,
                "move_issues": r.move_issues,
            }
            for r in results
        ]
    raw_file = out_dir / "probe_raw.json"
    with open(raw_file, "w") as f:
        json.dump(raw_data, f, indent=2)

    # Generate comparison report if multiple models
    if multi_model:
        comparison = generate_comparison_report(all_model_results, positions)
        comparison_file = out_dir / "probe_comparison.md"
        comparison_file.write_text(comparison)
        print(f"\n{'=' * 60}")
        print(f"  Comparison report: {comparison_file}")

    # Also write the last model's report as the default probe_results.md
    if all_model_results:
        last_model = list(all_model_results.keys())[-1]
        last_report = generate_report(all_model_results[last_model], last_model, positions)
        (out_dir / "probe_results.md").write_text(last_report)

    print(f"\n{'=' * 60}")
    print(f"Done! Raw data: {raw_file}")
    if multi_model:
        print(f"Open output/llm_probe/probe_comparison.md for the side-by-side comparison.")


if __name__ == "__main__":
    main()
