#!/usr/bin/env python3
"""Architecture review — have a frontier model critique the DESIGN.

The report card (scripts/eval_coach_review.py) shows the reviewer only the
coach's OUTPUT, so its advice is blind to the system and it re-proposes things we
already tried. This reads a report-card transcript (which now stores the exact
prompt sent to the local model) and asks a frontier model to review the
ARCHITECTURE: is the approach fundamentally sound, what is the real mechanism
behind the recurring failures, and which SYSTEM changes are highest-leverage —
while respecting our constraints and the log of already-tried levers.

Needs no engine and no tunnel: it consumes a saved transcript + the lever log.

Usage (omit {prompt} so the prompt goes on STDIN — this context is tens of
thousands of characters and exceeds the Windows command-line limit as an argv):
    python scripts/eval_architecture_review.py \
        --transcript output/coach_review_v19/transcript.json \
        --judge-model claude-sonnet-4.6 \
        --judge-command "kiro-cli chat --no-interactive --model claude-sonnet-4.6"
"""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chess_coach.eval.coach_review import (  # noqa: E402
    ReviewStats,
    ReviewTurn,
    build_architecture_review_prompt,
)
from chess_coach.llm import create_provider  # noqa: E402

# Kept in sync with the code by hand; the EXACT rendered prompt is also sent, so
# ground truth about what the model sees does not depend on this summary.
ARCHITECTURE = """\
Pipeline for one coached student move (the move-feedback path):
1. ENGINE (Blunder, a separate C++ UCI engine with a custom "coaching protocol")
   analyses the position and returns STRUCTURED data: comparison report
   (student move, engine best move, eval before/after, eval drop, a
   classification label, a short `best_move_idea` string, a refutation line as
   UCI moves, missed tactics) and a position report (top N PV lines with evals,
   hanging pieces, threats with structured source/target squares, tactical
   motifs, pawn-structure features, king-safety fields).
2. CLIENT-SIDE COMPOSERS (Python, deterministic, using python-chess) turn that
   structured data into plain-language prompt sections. The engine's own prose
   `description` fields are NEVER shown to the LLM (a past decision: all
   sentences are composed client-side from structured facts). Composers include:
   an explicit piece-placement block (the model cannot reliably read FEN), a
   board-derived pawn-structure block (isolated/doubled), a king-safety
   sentence, threats, missed tactics, an engine-verified candidate MOVE MENU
   (each move tagged best/sound/dubious/blunder from its eval drop), and the
   opponent's single first refutation reply with what it captures (computed from
   the board).
   Since the last review, four composer changes were made and measured:
   (a) the comparison report's top lines are rendered in SAN from the CORRECT
   base position (after the student's move) and NUMBERED so whose-move-is-whose
   is explicit ("5...Nfg4 6.f4"); a line is truncated at the first unreplayable
   move rather than degrading to raw coordinates (the engine sometimes emits an
   internally inconsistent PV);
   (b) the opponent's reply carries a verified effect clause (capture / fork /
   check / attack-on-undefended / escape / defend), shared with (c);
   (c) "What the best move achieves" is no longer the engine's category LABEL
   alone — a board-derived clause is prepended ("attacking their bishop on b4
   (pawn structure ...)"), covering ~70% of moves; the label alone is used when
   nothing is verifiable;
   (d) each selected guidance theme is instantiated with the board fact that
   made its feature fire ("... HERE: their knight on d5 is undefended"), filtered
   to features actually present so no fact can be fabricated.
3. PEDAGOGY LAYER: a curated YAML knowledge resource (~20 entries: principles,
   patterns, plans) each carrying a named theme, a `focus` statement and a
   `how_to_apply` statement, keyed to a closed vocabulary of board-derived
   "position features" (phase, undefended_piece, hanging_piece_opponent,
   tactic:fork/pin/back_rank, passed/isolated pawn, exposed_king, open_file,
   material_lead, pawn_majority, favorable_capture). A selector picks up to 3
   level-appropriate entries whose features are all present, and injects their
   theme + how-to-apply text into the prompt as a "guidance" block.
4. PROMPT: one big prompt = system prompt (grounding rules, pedagogy, tone) +
   the composed sections + severity-tiered instructions chosen from OUR OWN
   eval-drop bands (best / sound / inaccuracy / serious) + a per-tier word limit.
5. LOCAL LLM (single call, qwen3:14b via Ollama over an SSH tunnel, temp 0,
   per-tier max_tokens) writes the final coaching text. There is exactly ONE LLM
   call per coached move. No retry, no critique pass, no second model.
6. VERIFICATION (deterministic, after generation): a precision-first fidelity
   checker re-reads the text against the board and the move menu and counts
   violations: illegal_move, off_menu (named a move not in the best/sound menu),
   unsound_move, placement (piece claimed on a square that doesn't hold it),
   development, empty_source, piece_type (capture described as taking the wrong
   piece), pawn_structure, geometry. These counts are DIAGNOSTIC only today —
   they are recorded, but nothing is regenerated or blocked when violations are
   found.

There is also a template-only fallback path (no LLM) and a Socratic mode; the
above is the shipping coaching path.\
"""

CONSTRAINTS = """\
- All inference must run LOCALLY on open models (no proprietary API at runtime).
  A frontier model is allowed ONLY as an offline eval judge / design aid — never
  as the runtime coach. Assume the runtime model is roughly qwen3:14b class.
- The engine (Blunder) can be extended, but its thresholds/labels are its own;
  the client must not depend on tunable engine labels.
- ACCURACY IS THE PRIORITY: a more concrete coach that states more wrong board
  facts is a regression. Every change is measured, and reverted if fidelity
  worsens.
- One coached move currently costs ~5s of LLM latency; interactive play means a
  few seconds is acceptable, tens of seconds is not.
- Coaching text is short (a per-tier word budget, ~40-120 words).\
"""


def main() -> None:
    p = argparse.ArgumentParser(description="Frontier design review of the coaching architecture")
    p.add_argument("--transcript", required=True, help="report-card transcript.json (with prompts)")
    p.add_argument("--lever-log", default="docs/coach-report-card.md")
    p.add_argument("--out", default="output/architecture_review")
    p.add_argument("--judge-model", required=True)
    p.add_argument("--judge-command", required=True)
    p.add_argument("--judge-base-url", default="http://localhost:11434")
    args = p.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    import json

    data = json.loads(Path(args.transcript).read_text(encoding="utf-8"))
    turns = [ReviewTurn(**{k: v for k, v in t.items()}) for t in data["turns"]]
    # Via from_dict: reconstructing field-by-field here silently dropped the
    # newer metrics, and the reviewer was told specificity was 0%.
    stats = ReviewStats.from_dict(data["stats"])

    # A representative sample across severities keeps the review prompt focused.
    def pick(pred, n=2):  # type: ignore[no-untyped-def]
        return [t for t in turns if pred(t)][:n]

    sample_turns = (
        pick(lambda t: t.eval_drop_cp > 100)
        + pick(lambda t: 50 < t.eval_drop_cp <= 100)
        + pick(lambda t: t.student_move_san == t.best_move_san)
        + pick(lambda t: t.phase == "phase:endgame")
    )
    sample_prompt = next((t.prompt for t in turns if t.eval_drop_cp > 100 and t.prompt), "")
    if not sample_prompt:
        sample_prompt = next((t.prompt for t in turns if t.prompt), "")
    if not sample_prompt:
        print("FATAL: transcript has no stored prompts — re-run the report card first.")
        sys.exit(1)

    prompt = build_architecture_review_prompt(
        architecture=ARCHITECTURE,
        constraints=CONSTRAINTS,
        lever_log=Path(args.lever_log).read_text(encoding="utf-8"),
        sample_prompt=sample_prompt,
        sample_turns=sample_turns,
        stats=stats,
    )

    judge = create_provider(
        "cli",
        model=args.judge_model,
        base_url=args.judge_base_url,
        api_key="",
        command=shlex.split(args.judge_command),
    )
    print(f"Requesting architecture review ({len(prompt)} chars of context)...")
    review = judge.generate(prompt, max_tokens=4096, temperature=0.0)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "review.md").write_text(review.strip() + "\n", encoding="utf-8")
    (out_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    print("\n" + review.strip())
    print(f"\nSaved: {out_dir / 'review.md'}")


if __name__ == "__main__":
    main()
