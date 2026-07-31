#!/usr/bin/env python3
"""End-to-end game-coaching eval: play a whole game, coach the student's
moves with the real pipeline, and capture a serializable trajectory.

Two Blunder players at chosen Elo generate the game (the *student* weak
enough to make coachable mistakes); a SEPARATE full-strength Blunder
instance is the coach's analysis oracle, so reduced play strength never
weakens the feedback ground truth. Each student move is coached via the
shipped ``Coach.evaluate_move`` and checked objectively with
``check_coaching_fidelity``. The frontier judge (kiro-cli) is added in a
later task; by default this runs judge-free (cheap smoke / tracker data).

Usage:
    # Short judge-free smoke against the local engine + Ollama:
    python scripts/eval_game_coaching.py --ply-cap 12 --games 1

    # A full game, student ~1350, coaching guidance on, vs the tunnel:
    python scripts/eval_game_coaching.py --student-elo 1350 --opponent-elo 1500 \
        --models qwen3:14b --base-url http://localhost:11435 --guidance on

Results: <out>/game_<i>.json (trajectory) + <out>/report.txt
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chess_coach.cli import _resolve_engine_path, load_config  # noqa: E402
from chess_coach.coach import Coach  # noqa: E402
from chess_coach.coaching_phrases import build_move_menu  # noqa: E402
from chess_coach.engine import CoachingEngine  # noqa: E402
from chess_coach.eval.game_coaching import (  # noqa: E402
    CoachFn,
    GameTrajectory,
    MoveFn,
    TurnRecord,
    aggregate,
    play_game,
)
from chess_coach.llm import create_provider  # noqa: E402
from chess_coach.pedagogy.features import extract_features  # noqa: E402
from chess_coach.verify import check_coaching_fidelity  # noqa: E402


def _build_engine(engine_cfg: dict, coaching_timeout: float) -> CoachingEngine:  # type: ignore[type-arg]
    """Build a UCI CoachingEngine from config (mirrors eval_run.py)."""
    path = _resolve_engine_path(engine_cfg["path"])
    args = [a for a in engine_cfg.get("args", []) if a != "--xboard"]
    if "--uci" not in args:
        args = ["--uci", *args]
    return CoachingEngine(path=path, args=args, coaching_timeout=coaching_timeout, ping_timeout=5.0)


def _make_move_fn(player: CoachingEngine, depth: int) -> MoveFn:
    """A player that sets its strength to the mover's Elo, then plays.

    Only the *player* engine's options are touched here — the coach oracle
    is a separate instance, so its full strength is never affected."""

    def move_fn(fen: str, elo: int) -> str:
        if elo > 0:
            player.set_option("UCI_LimitStrength", True)
            player.set_option("UCI_Elo", elo)
        else:
            player.set_option("UCI_LimitStrength", False)
        return player.play(fen, depth=depth)

    return move_fn


def _make_coach_fn(coach: Coach, oracle: CoachingEngine, multipv: int, depth: int) -> CoachFn:
    """Coach one student move: ground truth from the oracle + feedback from
    the shipped Coach.evaluate_move + an objective fidelity check."""

    def coach_fn(ply: int, fen_before: str, student_move: str) -> TurnRecord:
        report = oracle.get_position_report(fen_before, multipv=multipv, depth=depth)
        best_line = report.top_lines[0] if report.top_lines and report.top_lines[0].moves else None
        engine_best = best_line.moves[0] if best_line else ""
        menu = build_move_menu(report)
        features = sorted(extract_features(report))

        ev = coach.evaluate_move(fen_before, student_move)
        violations = check_coaching_fidelity(ev.feedback, report, menu)
        fidelity_kinds = dict(Counter(v.kind for v in violations))

        return TurnRecord(
            ply=ply,
            fen_before=fen_before,
            student_move=student_move,
            engine_best=engine_best,
            eval_before_cp=ev.eval_before_cp,
            eval_after_cp=ev.eval_after_cp,
            eval_drop_cp=ev.eval_drop_cp,
            classification=ev.classification,
            active_features=features,
            coach_feedback=ev.feedback,
            fidelity_kinds=fidelity_kinds,
        )

    return coach_fn


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="End-to-end game-coaching eval")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--models", nargs="*", default=[], help="Coaching model(s); default = config model")
    p.add_argument("--base-url", default=None, help="Override LLM base URL")
    p.add_argument("--student-elo", type=int, default=1350)
    p.add_argument("--opponent-elo", type=int, default=1350)
    p.add_argument("--student-white", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--start-fen", default=None, help="Start FEN (default: initial position)")
    p.add_argument("--ply-cap", type=int, default=80)
    p.add_argument("--games", type=int, default=1)
    p.add_argument("--depth", type=int, default=None, help="Engine depth (default: config engine.depth)")
    p.add_argument("--multipv", type=int, default=5)
    p.add_argument("--guidance", choices=["on", "off"], default="off")
    p.add_argument("--guidance-max", type=int, default=3)
    p.add_argument("--constrain-moves", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--template-only", action="store_true", default=False)
    p.add_argument("--level", default=None)
    p.add_argument("--engine-timeout", type=float, default=120.0)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default="output/game_coaching")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    cfg = load_config(args.config)
    engine_cfg = cfg["engine"]
    llm_cfg = cfg["llm"]
    coaching_cfg = cfg.get("coaching", {})

    depth = args.depth if args.depth is not None else engine_cfg.get("depth", 8)
    start_fen = args.start_fen or "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    model = args.models[0] if args.models else llm_cfg["model"]
    base_url = args.base_url or llm_cfg.get("base_url", "http://localhost:11434")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print(f"Game-coaching eval: student {args.student_elo} vs opponent {args.opponent_elo} Elo, depth {depth}")
    print(f"Coach: {model} @ {base_url}  (guidance={args.guidance}, constrain_moves={args.constrain_moves})")

    player = _build_engine(engine_cfg, args.engine_timeout)
    oracle = _build_engine(engine_cfg, args.engine_timeout)
    llm = create_provider(
        provider=llm_cfg["provider"], model=model, base_url=base_url, timeout=float(llm_cfg.get("timeout", 300))
    )

    reports = []
    try:
        player.start()
        oracle.start()
        coach = Coach(
            engine=oracle,
            llm=llm,
            depth=depth,
            coaching_depth=depth,
            top_moves=args.multipv,
            level=args.level or coaching_cfg.get("level", "intermediate"),
            temperature=float(llm_cfg.get("temperature", 0.7)),
            template_only=args.template_only,
            guidance=(args.guidance == "on"),
            guidance_max=args.guidance_max,
            constrain_moves=args.constrain_moves,
            play_elo=0,  # oracle stays full strength for coaching
        )
        move_fn = _make_move_fn(player, depth)
        coach_fn = _make_coach_fn(coach, oracle, args.multipv, depth)

        for i in range(args.games):
            print(f"\n=== game {i + 1}/{args.games} ===")
            traj = play_game(
                start_fen=start_fen,
                student_elo=args.student_elo,
                opponent_elo=args.opponent_elo,
                student_is_white=args.student_white,
                ply_cap=args.ply_cap,
                move_fn=move_fn,
                coach_fn=coach_fn,
                seed=args.seed + i,
            )
            traj.meta["model"] = model
            (out / f"game_{i + 1}.json").write_text(_dumps(traj), encoding="utf-8")
            report = aggregate(traj)  # judge added in a later task
            reports.append(report)
            print(report.render())
    finally:
        player.stop()
        oracle.stop()

    summary = "\n\n".join(r.render() for r in reports)
    (out / "report.txt").write_text(summary + "\n", encoding="utf-8")
    print(f"\nResults: {out}/game_*.json + {out}/report.txt")


def _dumps(traj: GameTrajectory) -> str:
    import json

    return json.dumps(traj.to_dict(), indent=2)


if __name__ == "__main__":
    main()
