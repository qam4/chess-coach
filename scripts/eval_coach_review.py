#!/usr/bin/env python3
"""Coach report card — single-mode holistic review.

Plays ONE real game, coaches every student move with the SHIPPING config
(guidance on, the model under test), times each generation, and records the
engine ground truth + deterministic fidelity + phase. A small curated endgame
set is appended so all phases are represented. Then a frontier reviewer
(kiro-cli) gives ONE honest verdict: a 0-10 score against the VISION "bridge"
standard, strengths, weaknesses (incl. latency/verbosity), and whether coaching
should differ by phase.

Not an A/B — it answers "is the coach what we envisioned, and where does it
fall short?".

Usage:
    python scripts/eval_coach_review.py \
        --model qwen3:14b --base-url http://localhost:11435 \
        --student-elo 1350 --opponent-elo 1500 --ply-cap 120 --seed 7

The judge defaults to claude-opus-5 and the command is derived from it, so neither
needs passing. Do not drop to a cheaper judge without re-checking its per-ply
claims against the board: claude-sonnet-4.6 was wrong on 5 of 5 such claims.

Under kiro-monitor, pass --progress-pattern "progress=(\\d+)/(\\d+)" to read the
progress line this prints. Without it the monitor guesses and has reported the chess
result "1/2-1/2" as 50% complete.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from collections import Counter
from pathlib import Path

import chess

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chess_coach.cli import _resolve_engine_path, load_config  # noqa: E402
from chess_coach.coaching_phrases import build_move_menu, uci_to_san  # noqa: E402
from chess_coach.coaching_templates import generate_move_coaching  # noqa: E402
from chess_coach.engine import CoachingEngine  # noqa: E402
from chess_coach.eval.coach_review import ReviewTurn, aggregate_review, build_coach_review_prompt  # noqa: E402
from chess_coach.eval.game_coaching import TurnRecord, play_game, student_moves  # noqa: E402
from chess_coach.llm import create_provider  # noqa: E402
from chess_coach.llm.ollama import OllamaProvider  # noqa: E402
from chess_coach.pedagogy.features import phase_of_board  # noqa: E402
from chess_coach.pedagogy.guard import guard_entries  # noqa: E402
from chess_coach.pedagogy.instantiate import feature_facts  # noqa: E402
from chess_coach.pedagogy.resource import KnowledgeResource, default_resource_path, load_resource  # noqa: E402
from chess_coach.pedagogy.selector import guidance_for_position  # noqa: E402
from chess_coach.pedagogy.theme_map import theme_features  # noqa: E402
from chess_coach.prompts import build_rich_move_evaluation_prompt, move_feedback_max_tokens  # noqa: E402
from chess_coach.verify import check_coaching_fidelity, generate_verified  # noqa: E402

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

# Curated positions to guarantee endgame (and one middlegame tactic) coverage so
# the reviewer can assess phase-appropriateness even if the game stalls earlier.
# (fen, student_move_uci). Ground truth is still engine-derived at eval time.
CURATED = [
    ("8/8/4k3/8/4P3/4K3/8/8 w - - 0 1", "e4e5"),  # K+P: push the pawn
    ("8/8/8/4k3/8/8/R7/4K3 w - - 0 1", "a2a5"),  # R endgame: cut the king
    ("8/5k2/8/3P4/8/8/5K2/8 w - - 0 1", "f2e3"),  # K+P: escort with the king
    ("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1", "a1a8"),  # back-rank idea
]


def _build_engine(engine_cfg: dict, coaching_timeout: float) -> CoachingEngine:  # type: ignore[type-arg]
    path = _resolve_engine_path(engine_cfg["path"])
    args = [a for a in engine_cfg.get("args", []) if a != "--xboard"]
    if "--uci" not in args:
        args = ["--uci", *args]
    return CoachingEngine(path=path, args=args, coaching_timeout=coaching_timeout, ping_timeout=5.0)


def _coach_turn(oracle, model, resource, ply, fen, move, *, level, depth, multipv, guidance_max):  # type: ignore[no-untyped-def]
    """Coach one student move with the shipping config; return a ReviewTurn."""
    comparison = oracle.get_comparison_report(fen, move, depth=depth)
    pos_report = oracle.get_position_report(fen, multipv=multipv, depth=depth)
    # Mirror Coach._select_guidance exactly, or the report card grades a
    # configuration that does not ship. Both biases matter: the recommended
    # move's theme, and preferring entries we can instantiate with a board fact
    # (without the latter, only a third of selected entries carried a fact).
    facts = feature_facts(pos_report)
    preferred: frozenset[str] = frozenset()
    if pos_report.top_lines and pos_report.top_lines[0].theme:
        preferred = theme_features(pos_report.top_lines[0].theme)
    guidance = guidance_for_position(
        resource,
        pos_report,
        level,
        guidance_max,
        preferred_features=preferred,
        fact_features=frozenset(facts),
    )
    prompt = build_rich_move_evaluation_prompt(comparison, level=level, guidance=guidance, guidance_facts=facts)
    t0 = time.monotonic()
    # Verify the finished text against the board before accepting it, exactly as
    # the shipping Coach does — via the SAME helper, so the report card cannot
    # grade a configuration that does not ship. Without this the harness measured
    # a coach with no output verification while the product had it.
    fallbacks: list[int] = []
    text = generate_verified(
        lambda: model.generate(prompt, max_tokens=move_feedback_max_tokens(comparison), temperature=0.0),
        fen,
        lambda: generate_move_coaching(comparison, level=level),
        on_fallback=lambda: fallbacks.append(ply),
    )
    latency = time.monotonic() - t0
    if fallbacks:
        print(f"  ply {ply}: every attempt contradicted the board — sent composed text instead")
    menu = build_move_menu(pos_report)
    fid = Counter(v.kind for v in check_coaching_fidelity(text, pos_report, menu))
    return ReviewTurn(
        ply=ply,
        phase=phase_of_board(chess.Board(fen)),
        fen_before=fen,
        student_move_san=uci_to_san(fen, move),
        best_move_san=uci_to_san(fen, comparison.best_move),
        classification=comparison.classification,
        eval_drop_cp=comparison.eval_drop_cp,
        coach_feedback=text,
        latency_s=latency,
        fidelity_kinds=dict(fid),
        prompt=prompt,
    )


def main() -> None:
    # Console may be cp1252 (Windows / kiro-monitor capture); the review text
    # contains em-dashes/box-drawing. Reconfigure so the final print can't crash
    # (the UTF-8 files are written regardless). Mirrors the cli.py BUG-012 fix.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="Coach report card (single-mode holistic review)")
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="http://localhost:11435")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--student-elo", type=int, default=1350)
    parser.add_argument("--opponent-elo", type=int, default=1500)
    parser.add_argument("--ply-cap", type=int, default=120)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--level", default="intermediate")
    parser.add_argument("--depth", type=int, default=None)
    parser.add_argument("--multipv", type=int, default=5)
    parser.add_argument("--guidance-max", type=int, default=3)
    parser.add_argument("--engine-timeout", type=float, default=120.0)
    parser.add_argument("--no-curated", action="store_true", help="skip the curated endgame/tactic positions")
    parser.add_argument("--out", default="output/coach_review")
    # Defaults to the strongest judge available. Measured on one transcript,
    # claude-sonnet-4.6 got 5 of 5 per-ply factual claims WRONG (twice insisting
    # dxe3 captured a pawn where the board has a knight on e3, and attributing a
    # piece_type violation to the wrong ply), and built a headline recommendation
    # on a misread metric. claude-opus-5 on the same transcript got 2 of 2 right
    # and found two real defects the deterministic checker misses. The extra
    # credits and ~2 minutes are cheap next to a wrong finding — we spent two
    # investigations on the phantom one.
    parser.add_argument("--judge-model", default="claude-opus-5")
    parser.add_argument(
        "--judge-command",
        default=None,
        help="judge command; defaults to kiro-cli with --judge-model (prompt on stdin)",
    )
    parser.add_argument("--judge-base-url", default="http://localhost:11434")
    args = parser.parse_args()

    config = load_config(args.config)
    depth = args.depth if args.depth is not None else config.get("engine", {}).get("depth", 12)

    # Derive the command from the model unless one is given. These two arguments
    # both named a model and could silently disagree — and the COMMAND is what
    # actually decides, so `--judge-model opus-5` with a sonnet command would have
    # recorded the wrong model against the run.
    judge_command = args.judge_command or f"kiro-cli chat --no-interactive --model {args.judge_model}"
    judge = create_provider(
        "cli", model=args.judge_model, base_url=args.judge_base_url, api_key="", command=shlex.split(judge_command)
    )
    model = OllamaProvider(model=args.model, base_url=args.base_url, timeout=300.0)

    player = _build_engine(config["engine"], args.engine_timeout)
    oracle = _build_engine(config["engine"], args.engine_timeout)
    player.start()
    oracle.start()
    if not oracle.coaching_available:
        player.stop()
        oracle.stop()
        print("FATAL: engine not coaching-capable")
        sys.exit(1)

    reachable, found = model.check_status()
    if not reachable or not found:
        player.stop()
        oracle.stop()
        print(f"FATAL: {args.model} not reachable/loaded at {args.base_url} (reachable={reachable}, found={found})")
        sys.exit(1)

    resource = load_resource(default_resource_path())
    admitted, _ = guard_entries(resource.entries, engine=None)
    resource = KnowledgeResource(
        entries=tuple(admitted),
        feature_vocab=resource.feature_vocab,
        eco_vocab=resource.eco_vocab,
        levels=resource.levels,
    )

    def move_fn(fen: str, elo: int) -> str:
        if elo > 0:
            player.set_option("UCI_LimitStrength", True)
            player.set_option("UCI_Elo", elo)
        else:
            player.set_option("UCI_LimitStrength", False)
        return player.play(fen, depth=depth)

    def capture_fn(ply: int, fen_before: str, student_move: str) -> TurnRecord:
        return TurnRecord(ply, fen_before, student_move, "", 0, 0, 0, "good", [], "")

    turns: list[ReviewTurn] = []
    try:
        print(f"Playing 1 game: student {args.student_elo} vs opponent {args.opponent_elo} Elo")
        traj = play_game(
            start_fen=START_FEN,
            student_elo=args.student_elo,
            opponent_elo=args.opponent_elo,
            student_is_white=True,
            ply_cap=args.ply_cap,
            move_fn=move_fn,
            coach_fn=capture_fn,
            seed=args.seed,
        )
        moves = student_moves(traj)
        # `total` counts the curated positions too, so the progress line covers the
        # whole job rather than resetting when the game ends.
        total = len(moves) + (0 if args.no_curated else len(CURATED))
        print(f"  game: {traj.result}, {len(moves)} student moves; coaching each...")
        for ply, fen, move in moves:
            try:
                turns.append(
                    _coach_turn(
                        oracle,
                        model,
                        resource,
                        ply,
                        fen,
                        move,
                        level=args.level,
                        depth=depth,
                        multipv=args.multipv,
                        guidance_max=args.guidance_max,
                    )
                )
                last = turns[-1]
                print(f"  ply {ply}: {last.student_move_san} ({last.classification}, {last.latency_s:.1f}s)")
            except Exception as e:  # noqa: BLE001
                print(f"  ply {ply}: SKIP ({e})")
            # An explicit, labelled progress line for kiro-monitor. Without one it
            # guesses, and it guessed the game result "1/2-1/2" was 50% complete.
            # No spaces in the token: the monitor's --progress-pattern is passed
            # through PowerShell's -ArgumentList, which splits on spaces, so a
            # pattern like "progress: (\d+)/(\d+)" arrives truncated to "progress:"
            # and matches with no capture groups (hence no percent).
            print(f"  progress={len(turns)}/{total}")

        if not args.no_curated:
            print("Coaching curated endgame/tactic positions for phase coverage...")
            for i, (fen, move) in enumerate(CURATED):
                try:
                    turns.append(
                        _coach_turn(
                            oracle,
                            model,
                            resource,
                            1000 + i,
                            fen,
                            move,
                            level=args.level,
                            depth=depth,
                            multipv=args.multipv,
                            guidance_max=args.guidance_max,
                        )
                    )
                    print(
                        f"  curated {i}: {turns[-1].student_move_san} ({turns[-1].phase}, {turns[-1].latency_s:.1f}s)"
                    )
                except Exception as e:  # noqa: BLE001
                    print(f"  curated {i}: SKIP ({e})")
                print(f"  progress={len(turns)}/{total}")
    finally:
        player.stop()
        oracle.stop()

    if not turns:
        print("No coached turns produced — nothing to review.")
        sys.exit(1)

    stats = aggregate_review(turns)
    review_prompt = build_coach_review_prompt(turns, stats)
    print("\nRequesting frontier review...")
    review = judge.generate(review_prompt, max_tokens=2048, temperature=0.0)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "transcript.json").write_text(
        json.dumps({"stats": stats.to_dict(), "turns": [t.to_dict() for t in turns]}, indent=2), encoding="utf-8"
    )
    (out_dir / "review.md").write_text(review.strip() + "\n", encoding="utf-8")
    print("\n" + "=" * 70)
    print(review.strip())
    print("=" * 70)
    print(f"\nSaved: {out_dir / 'review.md'} and {out_dir / 'transcript.json'}")


if __name__ == "__main__":
    main()
