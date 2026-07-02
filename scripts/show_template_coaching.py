#!/usr/bin/env python3
"""View the deterministic TEMPLATE coaching for one or more positions.

This isolates the engine-output -> template-render path (no LLM, no judge):
it runs the engine's ``coach eval`` on each FEN and prints the raw tactic /
threat descriptions the engine emitted alongside the rendered template
coaching text. Use it to eyeball whether the Blunder coaching output is
correct after engine changes.

Usage:
  # Default spread of tactic-rich positions:
  python scripts/show_template_coaching.py

  # One or more FENs of your own:
  python scripts/show_template_coaching.py "6k1/5ppp/8/8/8/8/8/4R1K1 w - - 0 1"

  # Pick a coaching level (beginner|intermediate|advanced):
  python scripts/show_template_coaching.py --level beginner "<FEN>"

Requires: blunder engine (uses config.yaml).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from chess_coach.cli import _create_engine, load_config
from chess_coach.coaching_templates import generate_position_coaching
from chess_coach.engine import CoachingEngine

# A spread that exercises each tactic type + a couple of quiet positions.
DEFAULT_FENS: list[tuple[str, str]] = [
    ("discovered_attack", "rnb1kbnr/pppp1ppp/4p3/6q1/4P3/2N5/PPPP1PPP/R1BQKB1R w KQkq - 2 3"),
    ("back_rank", "6k1/5ppp/8/8/8/8/8/4R1K1 w - - 0 1"),
    ("knight_fork", "r3k2r/ppp2ppp/8/3N4/8/8/PPP2PPP/R3K2R w KQkq - 0 1"),
    ("pin", "4k3/8/8/8/1b6/2N5/8/4K3 b - - 0 1"),
    ("starting_position", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"),
    ("kr_vs_k", "8/8/8/4k3/8/8/4K3/4R3 w - - 0 1"),
]

SEP = "=" * 72


def _show(engine: CoachingEngine, label: str, fen: str, level: str) -> None:
    report = engine.get_position_report(fen, multipv=3)

    print(SEP)
    print(f"{label}   {fen}")
    print(f"eval={report.eval_cp}cp  level={level}")
    print("-" * 72)

    # Raw engine tactic/threat descriptions (what we are verifying).
    if report.tactics:
        print("engine tactics:")
        for t in report.tactics:
            pv = " [PV]" if t.in_pv else ""
            print(f"  ({t.type}){pv} {t.description}")
    else:
        print("engine tactics: (none)")

    for side in ("white", "black"):
        threats = report.threats.get(side, [])
        for th in threats:
            print(f"engine threat [{side}]: {th.description}")

    print("-" * 72)
    print("TEMPLATE COACHING:")
    print(generate_position_coaching(report, level=level))
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fens", nargs="*", help="FEN(s) to render; defaults to a built-in spread")
    parser.add_argument(
        "--level",
        default="intermediate",
        choices=["beginner", "intermediate", "advanced"],
        help="coaching level (default: intermediate)",
    )
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    args = parser.parse_args()

    positions: list[tuple[str, str]]
    if args.fens:
        positions = [(f"fen[{i}]", f) for i, f in enumerate(args.fens)]
    else:
        positions = DEFAULT_FENS

    cfg = load_config(args.config)
    engine = _create_engine(cfg["engine"])
    engine.start()
    try:
        if not (isinstance(engine, CoachingEngine) and engine.coaching_available):
            print("ERROR: engine does not expose the coaching protocol.", file=sys.stderr)
            sys.exit(1)
        for label, fen in positions:
            _show(engine, label, fen, args.level)
    finally:
        engine.stop()


if __name__ == "__main__":
    main()
