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
from chess_coach.coach import Coach  # noqa: E402
from chess_coach.coaching_phrases import build_move_menu, uci_to_san  # noqa: E402
from chess_coach.engine import CoachingEngine  # noqa: E402
from chess_coach.eval.coach_review import ReviewTurn, aggregate_review, build_coach_review_prompt  # noqa: E402
from chess_coach.eval.game_coaching import TurnRecord, play_game, student_moves  # noqa: E402
from chess_coach.llm import create_provider  # noqa: E402
from chess_coach.llm.ollama import OllamaProvider  # noqa: E402
from chess_coach.pedagogy.features import phase_of_board  # noqa: E402
from chess_coach.verify import check_coaching_fidelity  # noqa: E402

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

#: Opening positions the seed selects between, so different seeds play DIFFERENT games.
#:
#: This exists because `--seed` was decorative. `play_game` accepted it, recorded it in
#: metadata, and used it nowhere; the moves come from `move_fn`, a deterministic engine call at
#: fixed depth and Elo. So every report card ever run played the identical game, and passing
#: four different seeds produced four byte-identical transcripts — 23 minutes of engine time for
#: four copies of the game we already had. Every number in the ledger rests on that one game.
#:
#: Seed 7 keeps the standard start, so the whole v1-v43 series stays comparable. Other seeds
#: open from a few moves of mainline theory, which gives genuinely different middlegames without
#: making either player random — the engine stays deterministic, which is what keeps a rerun
#: reproducible.
SEED_OPENINGS: dict[int, tuple[str, str]] = {
    7: ("standard start", START_FEN),
    11: ("Italian", "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 5 4"),
    13: ("Queen's Gambit", "rnbqkbnr/ppp2ppp/8/3pp3/2PP4/8/PP2PPPP/RNBQKBNR w KQkq - 0 3"),
    17: ("Sicilian", "rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"),
    23: ("French", "rnbqkbnr/pppp1ppp/4p3/8/3PP3/8/PPP2PPP/RNBQKBNR b KQkq - 0 2"),
}


def _start_for_seed(seed: int) -> tuple[str, str]:
    """``(label, fen)`` for this seed, falling back to the standard start."""
    return SEED_OPENINGS.get(seed, ("standard start", START_FEN))

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


def _coach_turn(coach, ply, fen, move):  # type: ignore[no-untyped-def]
    """Coach one student move by calling the SHIPPING coach; return a ReviewTurn.

    This used to rebuild the middle of the coaching pipeline — fetch the reports,
    select guidance, build the prompt, call the model — and it drifted from the
    product three times: guidance selection was mirrored by hand, output
    verification was missing entirely, and the rule that keeps the coach SILENT on
    good moves was absent, which manufactured a repetition defect no student could
    ever see and cost three rounds of chasing it.

    So it calls ``Coach.evaluate_move``. The prompt and the generation time come
    from the debug callback the coach already emits; the engine reports come back
    attached to the result, so nothing is re-run and nothing is reconstructed.
    Whatever the product does — including saying nothing at all — is what gets
    reviewed.
    """
    captured: dict[str, object] = {}

    def on_debug(step) -> None:  # type: ignore[no-untyped-def]
        if step.step == "eval_llm_start":
            captured["prompt"] = step.detail.get("llm_prompt", "")
        elif step.step == "eval_llm_done":
            captured["latency"] = step.elapsed_s
        elif step.step == "eval_verify_fallback":
            print(f"  ply {ply}: {step.message}")

    t0 = time.monotonic()
    evaluation = coach.evaluate_move(fen, move, on_debug=on_debug)
    wall = time.monotonic() - t0

    comparison = evaluation._comparison
    pos_report = evaluation._position_report
    text = evaluation.feedback
    fid: Counter[str] = Counter()
    if text.strip() and pos_report is not None:
        menu = build_move_menu(pos_report)
        fid = Counter(v.kind for v in check_coaching_fidelity(text, pos_report, menu))
    return ReviewTurn(
        ply=ply,
        phase=phase_of_board(chess.Board(fen)),
        fen_before=fen,
        student_move_san=uci_to_san(fen, move),
        best_move_san=uci_to_san(fen, comparison.best_move) if comparison else "",
        classification=evaluation.classification,
        eval_drop_cp=evaluation.eval_drop_cp,
        coach_feedback=text,
        # The LLM generation time when there was one; otherwise the wall time of a
        # turn the coach answered without a model call (which is ~0 and honest).
        latency_s=float(captured.get("latency", wall)),  # type: ignore[arg-type]
        fidelity_kinds=dict(fid),
        prompt=str(captured.get("prompt", "")),
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

    # The coach under review: the real one, on the full-strength oracle engine, with
    # the shipping knobs from config. It loads and guards the pedagogy resource and
    # selects guidance itself — the harness no longer mirrors any of that.
    coaching_cfg = config.get("coaching", {})
    coach = Coach(
        engine=oracle,
        llm=model,
        depth=depth,
        coaching_depth=depth,
        top_moves=args.multipv,
        level=args.level,
        max_tokens=config.get("llm", {}).get("max_tokens", 512),
        temperature=0.0,  # deterministic, so a run is a clean before/after
        template_only=coaching_cfg.get("template_only", False),
        guidance=coaching_cfg.get("guidance", True),
        guidance_max=args.guidance_max,
        constrain_moves=coaching_cfg.get("constrain_moves", True),
        verify_output=coaching_cfg.get("verify_output", True),
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
        opening_label, start_fen = _start_for_seed(args.seed)
        print(f"  seed {args.seed}: {opening_label}")
        traj = play_game(
            start_fen=start_fen,
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
                turns.append(_coach_turn(coach, ply, fen, move))
                last = turns[-1]
                said = "silent" if not last.coach_feedback.strip() else f"{last.latency_s:.1f}s"
                print(f"  ply {ply}: {last.student_move_san} ({last.classification}, {said})")
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
                    turns.append(_coach_turn(coach, 1000 + i, fen, move))
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
