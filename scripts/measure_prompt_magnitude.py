#!/usr/bin/env python3
"""Does any rendered prompt still put an eval magnitude in front of the model?

A deterministic before/after for the "stop asserting magnitude" change, on the
same footing as the way ledger rows 11 and 29 were measured: count the leak in the
prompts a real game produced, change the renderer, count again.

Two sides, and they answer different questions:

* **before** — the prompts stored in a saved ``transcript.json``. These are the actual
  bytes the local model received on that run, so the baseline is a record, not a
  reconstruction.
* **after** — the same positions re-rendered by today's code. Needs the engine (for
  the comparison report) but **no LLM**, so it is cheap and reproducible, and it does
  not depend on which model happens to be reachable.

That asymmetry is the point: it isolates the renderer. A full report card re-run would
also change the model's output, which is a separate question and needs the same model
the series used.

Usage:
    python scripts/measure_prompt_magnitude.py --transcript output/coach_review_v31/transcript.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import chess

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chess_coach.cli import _resolve_engine_path, load_config  # noqa: E402
from chess_coach.engine import CoachingEngine  # noqa: E402
from chess_coach.eval.coach_review import _PROMPT_MAGNITUDE_RE  # noqa: E402
from chess_coach.pedagogy.guard import guard_entries  # noqa: E402
from chess_coach.pedagogy.instantiate import feature_facts  # noqa: E402
from chess_coach.pedagogy.resource import (  # noqa: E402
    KnowledgeResource,
    default_resource_path,
    load_resource,
)
from chess_coach.pedagogy.selector import guidance_for_position  # noqa: E402
from chess_coach.pedagogy.theme_map import theme_features  # noqa: E402
from chess_coach.prompts import build_rich_move_evaluation_prompt  # noqa: E402


def _build_engine(engine_cfg: dict, timeout: float) -> CoachingEngine:  # type: ignore[type-arg]
    path = _resolve_engine_path(engine_cfg["path"])
    args = [a for a in engine_cfg.get("args", []) if a != "--xboard"]
    if "--uci" not in args:
        args = ["--uci", *args]
    return CoachingEngine(path=path, args=args, coaching_timeout=timeout, ping_timeout=5.0)


def _hits(text: str) -> list[str]:
    """Every magnitude/verdict fragment in ``text``, for reporting not just counting."""
    return [m.group(0).strip() for m in _PROMPT_MAGNITUDE_RE.finditer(text)]


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="Prompt-side magnitude leak: before vs after")
    parser.add_argument("--transcript", default="output/coach_review_v31/transcript.json")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--depth", type=int, default=None)
    parser.add_argument("--multipv", type=int, default=5)
    parser.add_argument("--level", default="intermediate")
    parser.add_argument("--guidance-max", type=int, default=3)
    parser.add_argument("--engine-timeout", type=float, default=120.0)
    args = parser.parse_args()

    turns = json.loads(Path(args.transcript).read_text(encoding="utf-8"))["turns"]
    # Only turns the coach actually spoke on: a turn with no prompt had no prompt to
    # leak, and counting the silent ones would flatter both sides equally.
    spoken = [t for t in turns if t.get("prompt")]
    print(f"{Path(args.transcript).name}: {len(turns)} turns, {len(spoken)} with a rendered prompt\n")

    before_bad = 0
    before_frags: Counter[str] = Counter()
    for t in spoken:
        hits = _hits(t["prompt"])
        if hits:
            before_bad += 1
            before_frags.update(hits)

    config = load_config(args.config)
    depth = args.depth if args.depth is not None else config.get("engine", {}).get("depth", 12)
    coaching_cfg = config.get("coaching", {})
    use_guidance = bool(coaching_cfg.get("guidance", True))

    resource = None
    if use_guidance:
        res = load_resource(default_resource_path())
        admitted, _ = guard_entries(res.entries, engine=None)
        resource = KnowledgeResource(
            entries=tuple(admitted),
            feature_vocab=res.feature_vocab,
            eco_vocab=res.eco_vocab,
            levels=res.levels,
        )

    engine = _build_engine(config["engine"], args.engine_timeout)
    engine.start()
    if not engine.coaching_available:
        engine.stop()
        print("FATAL: engine not coaching-capable")
        sys.exit(1)

    after_bad = 0
    after_frags: Counter[str] = Counter()
    rendered = skipped = 0
    try:
        for t in spoken:
            fen = t["fen_before"]
            board = chess.Board(fen)
            try:
                uci = board.parse_san(t["student_move_san"]).uci()
            except ValueError as exc:
                print(f"  ply {t['ply']}: SKIP (cannot parse {t['student_move_san']!r}: {exc})")
                skipped += 1
                continue
            try:
                comparison = engine.get_comparison_report(fen, uci, depth=depth)
                guidance = None
                facts = None
                if resource is not None:
                    pos = engine.get_position_report(fen, multipv=args.multipv)
                    preferred: frozenset[str] = frozenset()
                    if pos.top_lines and pos.top_lines[0].theme:
                        preferred = theme_features(pos.top_lines[0].theme)
                    facts = feature_facts(pos)
                    guidance = guidance_for_position(
                        resource,
                        pos,
                        args.level,
                        args.guidance_max,
                        preferred_features=preferred,
                        fact_features=frozenset(facts),
                    )
                prompt = build_rich_move_evaluation_prompt(
                    comparison, level=args.level, guidance=guidance, guidance_facts=facts
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  ply {t['ply']}: SKIP ({type(exc).__name__}: {exc})")
                skipped += 1
                continue
            rendered += 1
            hits = _hits(prompt)
            if hits:
                after_bad += 1
                after_frags.update(hits)
                print(f"  ply {t['ply']}: LEAK {hits}")
    finally:
        engine.stop()

    print("\n" + "=" * 68)
    print(f"BEFORE (prompts as sent on that run):   {before_bad}/{len(spoken)} turns carried a magnitude")
    if before_frags:
        print("  fragments: " + ", ".join(f"{frag!r} x{n}" for frag, n in before_frags.most_common(8)))
    print(f"AFTER  (same positions, today's code):  {after_bad}/{rendered} turns carried a magnitude")
    if after_frags:
        print("  fragments: " + ", ".join(f"{frag!r} x{n}" for frag, n in after_frags.most_common(8)))
    if skipped:
        print(f"  ({skipped} turns skipped — engine or SAN parse failure)")
    print("=" * 68)
    print(
        "\nNote: this measures the PROMPT only. Whether the model still grades or prices\n"
        "a move out of its own vocabulary is a separate question, measured by\n"
        "ReviewStats.graded_or_priced on the next report card with the series model."
    )


if __name__ == "__main__":
    main()
