"""How many coached turns can a prompt-side change actually reach? Engine only, no LLM.

The standing rule (report card row 87) is to count coverage BEFORE spending a run: a
change touching 2 of 18 turns cannot move anything, however good those 2 become. Until
now the only way to count was a full report card or breadth sweep, both of which need the
remote model — so the rule was applied by hand, or not at all.

This replays the same five games as ``eval_check_breadth.py`` with the engine alone and
reports, per coached turn, which conditional parts of the move prompt were present. No
model call, no judge, so it costs engine time only and can be run before deciding whether
a change is worth measuring.

It answers coverage and only coverage. It cannot say what the model wrote, so it cannot
replace the breadth sweep — it sizes the opportunity the sweep then measures.

Usage:
    python scripts/eval_prompt_coverage.py --out output/prompt_coverage
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Same five games as the breadth sweep, so a coverage number here is about the same
# population the sweep reports fallbacks over. Imported rather than copied.
from eval_check_breadth import GAMES  # type: ignore[import-not-found]  # noqa: E402

from chess_coach.cli import _resolve_engine_path, load_config  # noqa: E402
from chess_coach.engine import CoachingEngine  # noqa: E402
from chess_coach.error_diagnosis import diagnose  # noqa: E402
from chess_coach.eval.game_coaching import TurnRecord, play_game  # noqa: E402
from chess_coach.prompts import (  # noqa: E402
    build_rich_move_evaluation_prompt,
    compose_safe_move_feedback,
)

#: Distinctive fragments of the two conditional instruction blocks. Matched against the
#: rendered prompt rather than recomputed, so this measures what the model would be told
#: rather than a near-copy of the branch that tells it.
_REPLY_OFFERED = "name the single reply shown above"
_REPLY_HELD_BACK = "is NOT given above, so you do not know it"
_REASON_OFFERED = "the ONLY reason you may give"


def _build_engine(engine_cfg: dict, timeout: float) -> CoachingEngine:  # type: ignore[type-arg]
    path = _resolve_engine_path(engine_cfg["path"])
    args = [a for a in engine_cfg.get("args", []) if a != "--xboard"]
    if "--uci" not in args:
        args = ["--uci", *args]
    return CoachingEngine(path=path, args=args, coaching_timeout=timeout, ping_timeout=5.0)


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    p = argparse.ArgumentParser(description="Conditional-prompt coverage, engine only")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--opponent-elo", type=int, default=1500)
    p.add_argument("--ply-cap", type=int, default=120)
    p.add_argument("--level", default="intermediate")
    p.add_argument("--engine-timeout", type=float, default=120.0)
    p.add_argument("--out", default="output/prompt_coverage")
    p.add_argument("--only", default="", help="substring of a game name; run just that game")
    args = p.parse_args()

    games = [g for g in GAMES if args.only.lower() in g[0].lower()] if args.only else list(GAMES)
    if not games:
        print(f"FATAL: --only {args.only!r} matched no game")
        sys.exit(2)

    config = load_config(args.config)
    depth = config.get("engine", {}).get("depth", 12)
    player = _build_engine(config["engine"], args.engine_timeout)
    oracle = _build_engine(config["engine"], args.engine_timeout)
    player.start()
    oracle.start()
    if not oracle.coaching_available:
        print("FATAL: engine not coaching-capable")
        player.stop()
        oracle.stop()
        sys.exit(1)

    rows: list[dict] = []  # type: ignore[type-arg]
    try:
        for i, (name, fen, student_white, student_elo) in enumerate(games, start=1):
            print(f"progress={i}/{len(games)} game {name}")
            turns: list[dict] = []  # type: ignore[type-arg]
            t_game = time.monotonic()

            def move_fn(f: str, elo: int) -> str:
                if elo > 0:
                    player.set_option("UCI_LimitStrength", True)
                    player.set_option("UCI_Elo", elo)
                else:
                    player.set_option("UCI_LimitStrength", False)
                return player.play(f, depth=depth)

            def coach_fn(ply: int, fen_before: str, student_move: str):  # type: ignore[no-untyped-def]
                comparison = oracle.get_comparison_report(fen_before, student_move, depth=depth)
                # Mirror the shipping skip rules exactly: a turn the coach never speaks on
                # is not part of the population a prompt change can reach.
                move_number = int(fen_before.split()[-1]) if fen_before.split() else 1
                if (move_number <= 6 and comparison.eval_drop_cp <= 150) or comparison.eval_drop_cp <= 50:
                    return TurnRecord(ply, fen_before, student_move, "", 0, 0, 0, "good", [], "")
                prompt = build_rich_move_evaluation_prompt(comparison, level=args.level)
                found = diagnose(fen_before, student_move, comparison.best_move)
                turns.append(
                    {
                        "ply": ply,
                        "fen": fen_before,
                        "classification": comparison.classification,
                        "drop_cp": comparison.eval_drop_cp,
                        "reply_offered": _REPLY_OFFERED in prompt,
                        "reply_withheld": _REPLY_HELD_BACK in prompt,
                        "reason_offered": _REASON_OFFERED in prompt,
                        "cause": found[0].kind if found else "",
                        "fallback_has_cause": bool(found) and bool(compose_safe_move_feedback(comparison)),
                    }
                )
                return TurnRecord(
                    ply, fen_before, student_move, "", comparison.eval_drop_cp, 0, 0, comparison.classification, [], ""
                )

            traj = play_game(
                start_fen=fen,
                student_elo=student_elo,
                opponent_elo=args.opponent_elo,
                student_is_white=student_white,
                ply_cap=args.ply_cap,
                move_fn=move_fn,
                coach_fn=coach_fn,
            )
            rows.append(
                {
                    "game": name,
                    "result": traj.result,
                    "plies": len(traj.turns),
                    "coached": len(turns),
                    "turns": turns,
                    "seconds": round(time.monotonic() - t_game, 1),
                }
            )
            offered = sum(1 for t in turns if t["reply_offered"])
            withheld = sum(1 for t in turns if t["reply_withheld"])
            caused = sum(1 for t in turns if t["cause"])
            print(
                f"  {name}: coached={len(turns)} reply_offered={offered} reply_withheld={withheld} "
                f"cause={caused} ({rows[-1]['seconds']}s)"
            )
    finally:
        player.stop()
        oracle.stop()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "coverage.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    all_turns = [t for r in rows for t in r["turns"]]
    n = len(all_turns)
    print(f"\n=== coverage over {n} coached turns, {len(rows)} games ===")
    if n:
        for label, key in (
            ("opponent reply supplied", "reply_offered"),
            ("opponent reply withheld", "reply_withheld"),
            ("our clause supplied as the reason", "reason_offered"),
            ("fallback would carry a cause", "fallback_has_cause"),
        ):
            k = sum(1 for t in all_turns if t[key])
            print(f"  {label:<36} {k:>3}/{n} ({k / n * 100:.0f}%)")
        kinds: dict[str, int] = {}
        for t in all_turns:
            kinds[t["cause"] or "(none)"] = kinds.get(t["cause"] or "(none)", 0) + 1
        print("  cause class: " + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items(), key=lambda x: -x[1])))
    print(f"\nSaved: {out_dir / 'coverage.json'}")


if __name__ == "__main__":
    main()
