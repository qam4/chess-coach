#!/usr/bin/env python3
"""Test harness: extract move insights from any position.

Usage:
  # Use default test position:
  python scripts/test_coaching_diff.py

  # Drop in any FEN (engine finds the best move):
  python scripts/test_coaching_diff.py "r2n1r1k/p1p2ppp/1p1p4/8/3Pq1b1/4BN2/P1P2PPP/R2QR1K1 w - - 0 16"

  # Specify FEN + move to analyze:
  python scripts/test_coaching_diff.py "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1" e7e5

Requires: blunder engine (uses config.yaml)
"""

from __future__ import annotations

import sys
from pathlib import Path

import chess

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from chess_coach.cli import _create_engine, load_config
from chess_coach.engine import CoachingEngine
from chess_coach.insights import extract_move_insight

DEFAULT_FEN = "r2n1r1k/p1p2ppp/1p1p4/8/3Pq1b1/4BN2/P1P2PPP/R2QR1K1 w - - 0 16"


def main() -> None:
    fen = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FEN
    move_uci = sys.argv[2] if len(sys.argv) > 2 else None

    cfg = load_config("config.yaml")
    engine = _create_engine(cfg["engine"])
    engine.start()

    try:
        assert isinstance(engine, CoachingEngine) and engine.coaching_available

        # Eval current position
        report_before = engine.get_position_report(fen, multipv=3)
        bd = report_before.eval_breakdown

        print(f"Position: {fen}")
        print(f"Eval: {report_before.eval_cp}cp")
        print(
            f"  material={bd.material} mobility={bd.mobility} "
            f"king_safety={bd.king_safety} pawn_structure={bd.pawn_structure} "
            f"tempo={bd.tempo} piece_bonuses={bd.piece_bonuses}"
        )
        print()

        # Determine move to analyze
        if move_uci is None:
            if report_before.top_lines and report_before.top_lines[0].moves:
                move_uci = report_before.top_lines[0].moves[0]
            else:
                print("No best move found in top lines.")
                return

        # Get SAN
        board = chess.Board(fen)
        try:
            move_san = board.san(chess.Move.from_uci(move_uci))
        except (ValueError, chess.InvalidMoveError):
            move_san = move_uci

        print(f"Analyzing move: {move_san} ({move_uci})")
        print()

        # Push move and eval the resulting position
        board.push(chess.Move.from_uci(move_uci))
        fen_after = board.fen()
        report_after = engine.get_position_report(fen_after, multipv=3)
        bd2 = report_after.eval_breakdown

        print(f"After {move_san}: {fen_after}")
        print(f"Eval: {report_after.eval_cp}cp")
        print(
            f"  material={bd2.material} mobility={bd2.mobility} "
            f"king_safety={bd2.king_safety} pawn_structure={bd2.pawn_structure} "
            f"tempo={bd2.tempo} piece_bonuses={bd2.piece_bonuses}"
        )
        print()

        # Extract insight
        insight = extract_move_insight(report_before, report_after, move_uci, move_san)

        print("=" * 60)
        print(f"MOVE INSIGHT: {insight.move_san}")
        print("=" * 60)
        print()

        if insight.factor_changes:
            print("What this move changes:")
            for fc in insight.factor_changes:
                arrow = "↑" if fc.improved else "↓"
                print(f"  {arrow} {fc.label}: {fc.delta_cp:+d}cp ({fc.before_cp} → {fc.after_cp})")
            print()

        if insight.capture:
            print(f"Captures: {insight.capture}")
            print()

        if insight.pieces_attacked:
            print(f"Attacks: {', '.join(insight.pieces_attacked)}")
            print()

        if insight.threats_created:
            print("New threats created:")
            for t in insight.threats_created:
                who = "⚔ Your threat" if not t.is_opponent_threat else "⚠ Opponent threat"
                print(f"  {who}: {t.description}")
            print()

        if insight.threats_resolved:
            print("Threats resolved:")
            for t in insight.threats_resolved:
                print(f"  ✓ {t.description}")
            print()

        if insight.threats_remaining:
            print("Remaining problems:")
            for t in insight.threats_remaining:
                print(f"  ⚠ {t.description}")
            print()

        if insight.plan:
            print(f"Follow-up plan: {' → '.join(insight.plan)}")
            print()

        print(
            f"Eval change: {insight.eval_before_cp}cp → {insight.eval_after_cp}cp "
            f"({insight.eval_after_cp - insight.eval_before_cp:+d}cp)"
        )

    finally:
        engine.stop()


if __name__ == "__main__":
    main()
