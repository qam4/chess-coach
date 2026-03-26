#!/usr/bin/env python3
"""Quick test: compare eval breakdowns before and after the best move.

Uses the position from the coaching quality discussion:
  r2n1r1k/p1p2ppp/1p1p4/8/3Pq1b1/4BN2/P1P2PPP/R2QR1K1 w - - 0 16
  Best move: d4d5

Run: python scripts/test_coaching_diff.py
Requires: blunder engine running (uses config.yaml)
"""

from __future__ import annotations

import sys
from pathlib import Path

import chess

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from chess_coach.cli import _create_engine, load_config
from chess_coach.coaching_templates import diff_eval_breakdowns
from chess_coach.engine import CoachingEngine
from chess_coach.insights import extract_move_insight

FEN = "r2n1r1k/p1p2ppp/1p1p4/8/3Pq1b1/4BN2/P1P2PPP/R2QR1K1 w - - 0 16"
BEST_MOVE = "d4d5"


def main() -> None:
    cfg = load_config("config.yaml")
    engine = _create_engine(cfg["engine"])
    engine.start()

    try:
        assert isinstance(engine, CoachingEngine) and engine.coaching_available

        # 1. Eval current position
        print(f"Position: {FEN}")
        print(f"Best move: {BEST_MOVE}")
        print()

        report_before = engine.get_position_report(FEN, multipv=3)
        bd_before = report_before.eval_breakdown
        print(f"BEFORE (current position):")
        print(f"  eval_cp: {report_before.eval_cp}")
        print(f"  material:       {bd_before.material}")
        print(f"  mobility:       {bd_before.mobility}")
        print(f"  king_safety:    {bd_before.king_safety}")
        print(f"  pawn_structure: {bd_before.pawn_structure}")
        print(f"  tempo:          {bd_before.tempo}")
        print(f"  piece_bonuses:  {bd_before.piece_bonuses}")
        print()

        # 2. Push best move and eval
        board = chess.Board(FEN)
        board.push(chess.Move.from_uci(BEST_MOVE))
        fen_after = board.fen()

        report_after = engine.get_position_report(fen_after, multipv=3)
        bd_after = report_after.eval_breakdown
        print(f"AFTER d5 ({fen_after}):")
        print(f"  eval_cp: {report_after.eval_cp}")
        print(f"  material:       {bd_after.material}")
        print(f"  mobility:       {bd_after.mobility}")
        print(f"  king_safety:    {bd_after.king_safety}")
        print(f"  pawn_structure: {bd_after.pawn_structure}")
        print(f"  tempo:          {bd_after.tempo}")
        print(f"  piece_bonuses:  {bd_after.piece_bonuses}")
        print()

        # 3. Diff
        diffs = diff_eval_breakdowns(bd_before, bd_after)
        print("BREAKDOWN DIFF (what d5 changed):")
        if diffs:
            for label, delta in diffs:
                direction = "improved" if delta > 0 else "worsened"
                print(f"  {label}: {delta:+d}cp ({direction})")
        else:
            print("  No significant changes (all deltas < 5cp)")
        print()

        # 4. Threats before
        print("THREATS (current position):")
        for side in ("white", "black"):
            for threat in report_before.threats.get(side, []):
                print(f"  [{side}] {threat.type}: {threat.description}")
        print()

        # 5. Threats after d5
        print("THREATS (after d5):")
        for side in ("white", "black"):
            for threat in report_after.threats.get(side, []):
                print(f"  [{side}] {threat.type}: {threat.description}")
        print()

        # 6. Check which threats were resolved
        threats_before = set()
        for side in ("white", "black"):
            for t in report_before.threats.get(side, []):
                threats_before.add(f"{t.type}:{t.source_square}")
        threats_after = set()
        for side in ("white", "black"):
            for t in report_after.threats.get(side, []):
                threats_after.add(f"{t.type}:{t.source_square}")

        resolved = threats_before - threats_after
        new_threats = threats_after - threats_before
        if resolved:
            print("RESOLVED THREATS (d5 fixed these):")
            for t in resolved:
                print(f"  ✓ {t}")
        if new_threats:
            print("NEW THREATS (d5 created these):")
            for t in new_threats:
                print(f"  ⚠ {t}")
        if not resolved and not new_threats:
            print("THREATS UNCHANGED")

        # 7. Full MoveInsight extraction
        print()
        print("=" * 60)
        print("MOVE INSIGHT (structured reasoning)")
        print("=" * 60)
        insight = extract_move_insight(
            report_before, report_after, BEST_MOVE
        )
        print(f"Move: {insight.move_san}")
        print()
        if insight.factor_changes:
            print("Why this move is good/bad:")
            for fc in insight.factor_changes:
                arrow = "↑" if fc.improved else "↓"
                print(f"  {arrow} {fc.label}: {fc.delta_cp:+d}cp")
        if insight.pieces_attacked:
            print(f"Attacks: {', '.join(insight.pieces_attacked)}")
        if insight.capture:
            print(f"Captures: {insight.capture}")
        if insight.threats_created:
            print("Creates threats:")
            for t in insight.threats_created:
                who = "opponent" if t.is_opponent_threat else "yours"
                print(f"  [{who}] {t.description}")
        if insight.threats_resolved:
            print("Resolves threats:")
            for t in insight.threats_resolved:
                print(f"  ✓ {t.description}")
        if insight.threats_remaining:
            print("Remaining problems:")
            for t in insight.threats_remaining:
                print(f"  ⚠ {t.description}")
        if insight.plan:
            print(f"Follow-up plan: {' → '.join(insight.plan)}")
        print()
        print(f"Eval: {insight.eval_before_cp}cp → {insight.eval_after_cp}cp")

    finally:
        engine.stop()


if __name__ == "__main__":
    main()
