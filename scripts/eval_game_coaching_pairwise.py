#!/usr/bin/env python3
"""Pairwise game-coaching eval: play whole games, then A/B the coaching.

A played game's student moves ARE move-feedback scenarios, so this plays N
games between two Blunder players at chosen Elo (the student weak enough to
make coachable mistakes), turns every student move into a scenario, and
feeds them to the *existing, validated* move-feedback pairwise harness
(guidance OFF vs ON), judged by a frontier model via kiro-cli. The win-rate
+ sign test then answer "does guidance help teaching over realistic games?"
— the same low-noise instrument that showed a significant win on curated
scenarios, now on the positions a player actually reaches.

A separate FULL-STRENGTH engine is the coaching oracle, so the players'
reduced Elo never weakens the feedback ground truth.

Usage:
    python scripts/eval_game_coaching_pairwise.py \
        --model qwen3:14b --base-url http://localhost:11435 \
        --student-elo 1350 --opponent-elo 1500 --games 2 --ply-cap 60 \
        --judge-provider cli --judge-model claude-sonnet-4.6 \
        --judge-command "kiro-cli chat --no-interactive --model claude-sonnet-4.6 {prompt}"
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chess_coach.cli import _resolve_engine_path, load_config  # noqa: E402
from chess_coach.engine import CoachingEngine  # noqa: E402
from chess_coach.eval import (  # noqa: E402
    render_pairwise,
    run_move_feedback_pairwise,
    summarize_skips,
)
from chess_coach.eval.game_coaching import TurnRecord, play_game, student_moves  # noqa: E402
from chess_coach.eval.move_feedback import MoveFeedbackScenario  # noqa: E402
from chess_coach.llm import create_provider  # noqa: E402
from chess_coach.llm.ollama import OllamaProvider  # noqa: E402
from chess_coach.pedagogy.guard import guard_entries  # noqa: E402
from chess_coach.pedagogy.resource import (  # noqa: E402
    KnowledgeResource,
    PedagogyError,
    default_resource_path,
    load_resource,
)

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def _build_engine(engine_cfg: dict, coaching_timeout: float) -> CoachingEngine:  # type: ignore[type-arg]
    path = _resolve_engine_path(engine_cfg["path"])
    args = [a for a in engine_cfg.get("args", []) if a != "--xboard"]
    if "--uci" not in args:
        args = ["--uci", *args]
    return CoachingEngine(path=path, args=args, coaching_timeout=coaching_timeout, ping_timeout=5.0)


def _generate_scenarios(
    player: CoachingEngine,
    *,
    games: int,
    student_elo: int,
    opponent_elo: int,
    student_white: bool,
    ply_cap: int,
    depth: int,
    level: str,
    seed: int,
) -> list[MoveFeedbackScenario]:
    """Play ``games`` games and return every student move as a scenario.

    A capture-only coach_fn records just the position + move (no LLM); the
    real coaching + judging happens later in the pairwise harness."""

    def move_fn(fen: str, elo: int) -> str:
        if elo > 0:
            player.set_option("UCI_LimitStrength", True)
            player.set_option("UCI_Elo", elo)
        else:
            player.set_option("UCI_LimitStrength", False)
        return player.play(fen, depth=depth)

    def capture_fn(ply: int, fen_before: str, student_move: str) -> TurnRecord:
        return TurnRecord(
            ply=ply,
            fen_before=fen_before,
            student_move=student_move,
            engine_best="",
            eval_before_cp=0,
            eval_after_cp=0,
            eval_drop_cp=0,
            classification="good",
            active_features=[],
            coach_feedback="",
        )

    scenarios: list[MoveFeedbackScenario] = []
    for gi in range(games):
        traj = play_game(
            start_fen=START_FEN,
            student_elo=student_elo,
            opponent_elo=opponent_elo,
            student_is_white=student_white,
            ply_cap=ply_cap,
            move_fn=move_fn,
            coach_fn=capture_fn,
            seed=seed + gi,
        )
        print(f"  game {gi + 1}/{games}: {traj.result}, {len(traj.turns)} student moves")
        for ply, fen, move in student_moves(traj):
            scenarios.append(MoveFeedbackScenario(id=f"g{gi + 1}p{ply}", fen=fen, move=move, level=level))
    return scenarios


def main() -> None:
    parser = argparse.ArgumentParser(description="Pairwise game-coaching A/B (guidance off vs on)")
    parser.add_argument("--model", required=True, help="Coaching model under test")
    parser.add_argument("--base-url", default="http://localhost:11435")
    parser.add_argument("--config", default="config.yaml")
    # Game generation.
    parser.add_argument("--student-elo", type=int, default=1350)
    parser.add_argument("--opponent-elo", type=int, default=1350)
    parser.add_argument("--student-white", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--games", type=int, default=2)
    parser.add_argument("--ply-cap", type=int, default=60)
    parser.add_argument("--level", default="intermediate")
    # Coaching + judging.
    parser.add_argument("--engine-timeout", type=float, default=120.0)
    parser.add_argument("--depth", type=int, default=None)
    parser.add_argument("--multipv", type=int, default=5)
    parser.add_argument("--guidance-max", type=int, default=3)
    parser.add_argument("--judge-repeats", type=int, default=1)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", default="output/game_coaching_pairwise")
    parser.add_argument("--judge-model", required=True)
    parser.add_argument("--judge-provider", default="cli")
    parser.add_argument("--judge-base-url", default="http://localhost:11434")
    parser.add_argument("--judge-command", default=None)
    parser.add_argument("--judge-api-key", default=os.environ.get("CHESS_COACH_JUDGE_KEY", ""))
    args = parser.parse_args()

    config = load_config(args.config)
    depth = args.depth if args.depth is not None else config.get("engine", {}).get("depth", 8)

    # Judge provider (frontier via kiro-cli, like the move-feedback pairwise).
    judge_kwargs: dict[str, object] = {
        "model": args.judge_model,
        "base_url": args.judge_base_url,
        "api_key": args.judge_api_key,
    }
    if args.judge_provider == "cli":
        if not args.judge_command:
            print("FATAL: --judge-provider cli requires --judge-command")
            sys.exit(1)
        judge_kwargs["command"] = shlex.split(args.judge_command)
    judge = create_provider(args.judge_provider, **judge_kwargs)

    model = OllamaProvider(model=args.model, base_url=args.base_url, timeout=300.0)

    # Two engine roles: player (leveled) generates games; oracle (full
    # strength) is the coaching ground truth for the pairwise harness.
    player = _build_engine(config["engine"], args.engine_timeout)
    oracle = _build_engine(config["engine"], args.engine_timeout)
    try:
        player.start()
        oracle.start()
    except Exception as e:
        print(f"FATAL: could not start engine: {e}")
        sys.exit(1)
    if not oracle.coaching_available:
        player.stop()
        oracle.stop()
        print("FATAL: engine is not coaching-capable (coach ping failed).")
        sys.exit(1)

    try:
        resource = load_resource(default_resource_path())
    except PedagogyError as e:
        player.stop()
        oracle.stop()
        print(f"FATAL: Knowledge_Resource unavailable: {e}")
        sys.exit(1)
    admitted, _ = guard_entries(resource.entries, engine=None)
    resource = KnowledgeResource(
        entries=tuple(admitted),
        feature_vocab=resource.feature_vocab,
        eco_vocab=resource.eco_vocab,
        levels=resource.levels,
    )

    reachable, model_found = model.check_status()
    if not reachable:
        player.stop()
        oracle.stop()
        print(f"FATAL: endpoint unreachable at {args.base_url} — is the SSH tunnel up?")
        sys.exit(1)
    if not model_found:
        player.stop()
        oracle.stop()
        print(f"FATAL: tunnel up but model {args.model} is not loaded at {args.base_url}")
        sys.exit(1)

    print(f"Playing {args.games} game(s): student {args.student_elo} vs opponent {args.opponent_elo} Elo")
    try:
        scenarios = _generate_scenarios(
            player,
            games=args.games,
            student_elo=args.student_elo,
            opponent_elo=args.opponent_elo,
            student_white=args.student_white,
            ply_cap=args.ply_cap,
            depth=depth,
            level=args.level,
            seed=args.seed,
        )
        if not scenarios:
            player.stop()
            oracle.stop()
            print("No student moves generated — nothing to judge.")
            sys.exit(1)
        print(f"\nGenerated {len(scenarios)} coaching scenarios; running pairwise (guidance off vs on)\n")
        rng = random.Random(args.seed)
        summary, records, skips = run_move_feedback_pairwise(
            scenarios,
            oracle,
            model,
            judge,
            resource,
            depth=depth,
            multipv=args.multipv,
            guidance_max=args.guidance_max,
            temperature=args.temperature,
            judge_repeats=args.judge_repeats,
            rng=rng,
            on_progress=lambda m: print(f"  {m}"),
        )
    finally:
        player.stop()
        oracle.stop()

    if skips:
        print(f"\n{len(skips)} scenario(s) skipped: {summarize_skips(skips)}")
    if summary is None:
        print("\nNo comparisons produced — nothing to summarize.")
        sys.exit(1)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "pairwise.json").write_text(
        json.dumps(
            {
                "model": args.model,
                "judge_model": args.judge_model,
                "path": "game_coaching",
                "games": args.games,
                "student_elo": args.student_elo,
                "opponent_elo": args.opponent_elo,
                "guidance_max": args.guidance_max,
                "judge_repeats": args.judge_repeats,
                "seed": args.seed,
                "summary": {
                    "n": summary.n,
                    "wins_off": summary.wins_a,
                    "wins_on": summary.wins_b,
                    "ties": summary.ties,
                    "on_win_rate": summary.win_rate_b,
                    "p_value": summary.p_value,
                    "significant": summary.significant,
                    "verdict": summary.verdict,
                },
                "comparisons": records,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("\n" + render_pairwise(summary))
    print(f"\nResults: {out_dir / 'pairwise.json'}")


if __name__ == "__main__":
    main()
