"""Do the fidelity checks misfire on games the report card never plays?

The report card replays ONE game (byte-identical across v26-v29), and every check
that can now REPLACE a student's coaching was validated on those 44 turns. A check
that is subtly too aggressive would be invisible there and would quietly turn the
coach into a template elsewhere.

This answers that, and only that. Two numbers per game: how often a gating check
fired, and how many turns were replaced by composed text. **No judge** — both are
deterministic, so this costs engine and local-model time only.

Deliberately NOT random. Five fixed games, replayed identically every run, so a
result reproduces: if game 3 shows twenty fallbacks today it shows twenty tomorrow.
Randomness would destroy the property that makes the harness trustworthy.

Usage:
    python scripts/eval_check_breadth.py --model qwen3:14b --base-url http://localhost:11435
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chess_coach.cli import _resolve_engine_path, load_config  # noqa: E402
from chess_coach.coaching_phrases import uci_to_san  # noqa: E402
from chess_coach.coaching_templates import generate_move_coaching  # noqa: E402
from chess_coach.engine import CoachingEngine  # noqa: E402
from chess_coach.eval.game_coaching import play_game  # noqa: E402
from chess_coach.llm.ollama import OllamaProvider  # noqa: E402
from chess_coach.pedagogy.guard import guard_entries  # noqa: E402
from chess_coach.pedagogy.instantiate import feature_facts  # noqa: E402
from chess_coach.pedagogy.resource import KnowledgeResource, default_resource_path, load_resource  # noqa: E402
from chess_coach.pedagogy.selector import guidance_for_position  # noqa: E402
from chess_coach.pedagogy.theme_map import theme_features  # noqa: E402
from chess_coach.prompts import (  # noqa: E402
    build_rich_move_evaluation_prompt,
    compose_safe_move_feedback,
    move_feedback_max_tokens,
)
from chess_coach.verify import check_text_fidelity, gating_violations, generate_verified  # noqa: E402

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

#: (name, start_fen, student_is_white, student_elo). Chosen to cover what the report
#: card's single game does not: a quiet positional structure, the student on the black
#: side, and a stronger student (fewer blunders, so a different move-quality mix).
#: Game 1 is the report card's own game, as a control — its numbers must match.
GAMES: list[tuple[str, str, bool, int]] = [
    ("control (report-card game)", START, True, 1350),
    ("french-quiet", "rnbqkbnr/pppp1ppp/4p3/8/3PP3/8/PPP2PPP/RNBQKBNR b KQkq - 0 2", True, 1350),
    ("queens-gambit-quiet", "rnbqkbnr/ppp1pppp/8/3p4/2PP4/8/PP2PPPP/RNBQKBNR b KQkq - 0 2", True, 1350),
    ("student-as-black", START, False, 1350),
    ("stronger-student", START, True, 1650),
]


def _build_engine(engine_cfg: dict, timeout: float) -> CoachingEngine:  # type: ignore[type-arg]
    # Identical to the report card's builder, deliberately: the sweep is only
    # meaningful if it runs the same engine configuration.
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

    p = argparse.ArgumentParser(description="Do the fidelity checks misfire on other games?")
    p.add_argument("--model", default="qwen3:14b")
    p.add_argument("--base-url", default="http://localhost:11435")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--opponent-elo", type=int, default=1500)
    p.add_argument("--ply-cap", type=int, default=120)
    p.add_argument("--level", default="intermediate")
    p.add_argument("--multipv", type=int, default=5)
    p.add_argument("--guidance-max", type=int, default=3)
    p.add_argument("--engine-timeout", type=float, default=120.0)
    p.add_argument("--out", default="output/check_breadth")
    p.add_argument("--only", default="", help="substring of a game name; run just that game")
    args = p.parse_args()

    games = [g for g in GAMES if args.only.lower() in g[0].lower()] if args.only else list(GAMES)
    if not games:
        print(f"FATAL: --only {args.only!r} matched no game in {[g[0] for g in GAMES]}")
        sys.exit(2)

    config = load_config(args.config)
    depth = config.get("engine", {}).get("depth", 12)
    model = OllamaProvider(model=args.model, base_url=args.base_url, timeout=300.0)
    # Same construction as the report card, so the sweep exercises the shipping
    # guidance selection rather than a near-copy of it.
    loaded = load_resource(default_resource_path())
    admitted, _ = guard_entries(loaded.entries, engine=None)
    resource = KnowledgeResource(
        entries=tuple(admitted),
        feature_vocab=loaded.feature_vocab,
        eco_vocab=loaded.eco_vocab,
        levels=loaded.levels,
    )

    reachable, found = model.check_status()
    if not reachable or not found:
        player_started = False  # noqa: F841  (engines not started yet)
        print(f"FATAL: {args.model} not reachable/loaded at {args.base_url}")
        sys.exit(1)

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
            side = "white" if student_white else "black"
            print(f"progress={i}/{len(games)} game {name} (student {side} {student_elo})")
            fired: Counter[str] = Counter()
            rejected: list[dict] = []  # type: ignore[type-arg]
            fallback_plies: list[int] = []
            coached = 0
            t_game = time.monotonic()

            def move_fn(f: str, elo: int) -> str:
                if elo > 0:
                    player.set_option("UCI_LimitStrength", True)
                    player.set_option("UCI_Elo", elo)
                else:
                    player.set_option("UCI_LimitStrength", False)
                return player.play(f, depth=depth)

            def coach_fn(ply: int, fen_before: str, student_move: str):  # type: ignore[no-untyped-def]
                nonlocal coached
                from chess_coach.eval.game_coaching import TurnRecord

                comparison = oracle.get_comparison_report(fen_before, student_move, depth=depth)
                # Mirror the shipping skip rules: good moves get no LLM call.
                move_number = int(fen_before.split()[-1]) if fen_before.split() else 1
                if (move_number <= 6 and comparison.eval_drop_cp <= 150) or comparison.eval_drop_cp <= 50:
                    return TurnRecord(ply, fen_before, student_move, "", 0, 0, 0, "good", [], "")
                pos_report = oracle.get_position_report(fen_before, multipv=args.multipv, depth=depth)
                facts = feature_facts(pos_report)
                preferred = (
                    theme_features(pos_report.top_lines[0].theme)
                    if pos_report.top_lines and pos_report.top_lines[0].theme
                    else frozenset()
                )
                guidance = guidance_for_position(
                    resource,
                    pos_report,
                    args.level,
                    args.guidance_max,
                    preferred_features=preferred,
                    fact_features=frozenset(facts),
                )
                prompt = build_rich_move_evaluation_prompt(
                    comparison, level=args.level, guidance=guidance, guidance_facts=facts
                )
                coached += 1

                def _on_violation(attempt: int, _b: int, bad: list, _ply: int = ply) -> None:  # type: ignore[type-arg]
                    for v in bad:
                        fired[v.kind] += 1
                        # The count alone cannot answer the only question that
                        # matters here — was the coach wrong, or was the check? So
                        # keep the rejected fragment and the position with it.
                        rejected.append(
                            {
                                "ply": _ply,
                                "attempt": attempt,
                                "kind": v.kind,
                                "text": " ".join(v.text.split()),
                                "detail": v.detail,
                                "fen": fen_before,
                            }
                        )

                text = generate_verified(
                    lambda: model.generate(prompt, max_tokens=move_feedback_max_tokens(comparison), temperature=0.0),
                    fen_before,
                    lambda: (
                        compose_safe_move_feedback(comparison) or generate_move_coaching(comparison, level=args.level)
                    ),
                    on_violation=_on_violation,
                    on_fallback=lambda _bad: fallback_plies.append(ply),
                )
                return TurnRecord(
                    ply,
                    fen_before,
                    student_move,
                    uci_to_san(fen_before, comparison.best_move),
                    comparison.eval_drop_cp,
                    0,
                    0,
                    comparison.classification,
                    [],
                    text,
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
            # Anything left in the SHIPPED text is a check that should have fired and
            # did not; anything in `fired` is a check that did.
            leaked = 0
            for t in traj.turns:
                if t.coach_feedback.strip():
                    leaked += len(gating_violations(check_text_fidelity(t.coach_feedback, t.fen_before)))
            row = {
                "game": name,
                "result": traj.result,
                "turns": len(traj.turns),
                "coached": coached,
                "fired": dict(fired),
                "fired_total": sum(fired.values()),
                "fallbacks": len(fallback_plies),
                "fallback_plies": fallback_plies,
                "rejected": rejected,
                "leaked_after_gate": leaked,
                "seconds": round(time.monotonic() - t_game, 1),
            }
            rows.append(row)
            print(
                f"  {name}: coached={coached} fired={sum(fired.values())} {dict(fired)} "
                f"fallbacks={len(fallback_plies)} leaked={leaked} ({row['seconds']}s)"
            )
    finally:
        player.stop()
        oracle.stop()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "breadth.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    print("\n=== summary: fallbacks per coached turn ===")
    for r in rows:
        rate = (r["fallbacks"] / r["coached"] * 100) if r["coached"] else 0.0
        print(f"  {r['game']:<28} {r['fallbacks']:>2}/{r['coached']:<3} ({rate:.0f}%)  fired={r['fired']}")

    # Every rejected claim, so the run can be READ rather than inferred from counts.
    # Each line is a judgement call for a human: coach wrong, or check wrong?
    print("\n=== rejected claims (was the coach wrong, or the check?) ===")
    for r in rows:
        if not r["rejected"]:
            continue
        print(f"  --- {r['game']} ---")
        for x in r["rejected"]:
            print(f"    ply {x['ply']:>3} attempt {x['attempt']} {x['kind']}: {x['text']!r}")
            print(f"        {x['detail']}")
            print(f"        {x['fen']}")
    print(f"\nSaved: {out_dir / 'breadth.json'}")


if __name__ == "__main__":
    main()
