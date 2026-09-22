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

The prompt goes on STDIN (never as an argv token): this context is tens of
thousands of characters and exceeds the Windows command-line limit.

    python scripts/eval_architecture_review.py \
        --transcript output/coach_review_v23/transcript.json

The judge defaults to claude-opus-5 and the command is derived from it. Do not
drop to a cheaper judge without re-checking its per-ply claims against the board:
claude-sonnet-4.6 was wrong on 5 of 5 such claims on one transcript, while
claude-opus-5 was right on 2 of 2 and found two defects the checker misses.
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
    resolve_judge_agent,
)
from chess_coach.llm import create_provider  # noqa: E402

# Kept in sync with the code BY HAND, which is the weak point: the exact rendered prompt is also
# sent, so ground truth about what the model SEES does not depend on this summary, but the
# reviewer's picture of the SYSTEM does.
#
# Rewritten 2026-09-21 from the code, because the previous version had gone materially wrong
# rather than merely stale. It told the reviewer "these counts are DIAGNOSTIC only today — nothing
# is regenerated or blocked when violations are found", when a gating violation has for some time
# triggered a retry and then a deterministic-template fallback. It also predated the error-cause
# field, the takeaway ladder, the guidance-substitution path, engine_trust, and the normalized
# eval thresholds, and it put the knowledge bank at ~20 entries against an actual 24.
#
# This matters more than an ordinary stale comment: a frontier model asked to critique a DESIGN
# will critique the design it is shown. The ledger already records one architecture review that
# reasoned from a broken metric and named the wrong fundamental limit. Before running this script,
# re-read this string against the code.
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
3. PEDAGOGY LAYER: a curated YAML knowledge resource, currently 24 entries (16
   principles, 6 patterns, 2 plans), each carrying a named theme, a `focus`
   statement and a `how_to_apply` statement, keyed to a closed vocabulary of
   board-derived "position features" (phase, undefended_piece,
   hanging_piece_opponent, tactic:fork/pin/back_rank, passed/isolated pawn,
   exposed_king, open_file, material_lead, pawn_majority, favorable_capture). A
   selector picks up to 3 level-appropriate entries whose features are all
   present, and injects their theme + how-to-apply text into the prompt as a
   "guidance" block.
   Coverage is uneven in a way that matters: only 10 of the 24 entries are
   phase-tagged and only 4 are endgame entries, while the endgame is the LARGEST
   phase in a report-card game (typically 13-26 of 40-51 turns). Two entries keyed
   on the same feature set are indistinguishable to the selector, so adding rivals
   to an existing entry recreates a monoculture one level down.
4. PROMPT: one big prompt = system prompt (grounding rules, pedagogy, tone) +
   the composed sections + severity-tiered instructions chosen from OUR OWN
   eval-drop bands (best / sound / inaccuracy / serious) + a per-tier word limit.
5. LOCAL LLM (single call, qwen3:14b via Ollama over an SSH tunnel, temp 0,
   per-tier max_tokens) writes the final coaching text. There is exactly ONE LLM
   call per coached move. No retry, no critique pass, no second model.
6. VERIFICATION IS A GATE, NOT A SCORE (deterministic, after generation). A
   precision-first fidelity checker re-reads the text against the board and the
   move menu. `generate_verified` runs the check, RETRIES the generation once on a
   gating violation (the model is sampled, so the same prompt is a different draw),
   and if it still fails, discards the model's text and ships deterministic
   composed coaching instead. So there is no credit for being true, only a penalty
   for being false. The same routine is used by the shipping coach and by this
   harness, deliberately, so the report card cannot grade a configuration that
   does not ship.
   The gating kinds: illegal_move, placement, piece_type, geometry, relation,
   development, pawn_structure, empty_source, ownership, intent, move_claim,
   opponent_reply, terminal_label. Non-gating kinds are still counted and
   reported (off_menu, unsound_move).
   Recent additions worth knowing when judging the output: a CONFINEMENT check
   (claims that a move cuts off / traps / confines the enemy king are tested by
   counting that king's legal moves before and after), and an ownership check
   (clauses naming a piece as "yours" when it is the opponent's).

7. WHAT IS TAUGHT IS CHOSEN, NOT LEFT TO THE MODEL. The closing takeaway is
   derived from what the relevant move verifiably DOES (a category: capture,
   fork, check, attack, escape, defend, castle, open_file, mobility,
   king_activity, centre_control, development, extra_defender), keyed together
   with the phase. Left to choose, the coach closed on one of three ideas on 68%
   of turns, sometimes an idea that did not apply.
   On top of that sits a REPEAT LADDER: teach the lesson, then name the
   recurrence ("the SAME idea as earlier"), then say nothing. When the ladder
   would repeat itself and the pedagogy layer offers an unused principle that is
   anchored to a verified board fact, that principle is substituted instead;
   substituted lessons obey the same ladder.
   A STRONG diagnosis of the student's error outranks the move-derived lesson:
   `error_diagnosis` diffs `board.attackers()` across the two resulting positions
   into five classes (left undefended, moved the only defender, missed a free
   capture, stopped defending, opened a line), each carrying the habit that would
   have caught it.

8. WHAT WE DO NOT BELIEVE FROM THE ENGINE is recorded in code, not in comments.
   `engine_trust` lists each consumed engine field with a trust level, the reason,
   and a measurable criterion that would reinstate it. Eval MAGNITUDES are dropped
   (the engine disagrees with a reference engine by ~139cp mean absolute error on
   the turns where the coach speaks, and agrees on the best move 4 times in 18);
   structural facts that python-chess can re-derive are trusted. The division of
   labour: the engine answers what is TRUE about the position, this project
   answers what is worth TEACHING and how, and rules-level geometry is ours to
   compute.

There is also a template-only fallback path (no LLM) and a Socratic mode; the
above is the shipping coaching path.

KNOWN OPEN DEFECTS, so they are not re-proposed as discoveries:
- On roughly 11 of 81 spoken turns nothing about the recommended move is
  verifiable, so the prompt falls back to the engine's bare category LABEL as the
  only permitted reason, and the model restates it ("c5, which improves your pawn
  structure").
- A substituted guidance lesson is anchored to the POSITION but not to the MOVE,
  so a turn about a hanging bishop can close on "isolated pawn" — true of the
  board, unrelated to the turn. Around 9 of 81 turns.
- The coach has NO MEMORY ACROSS TURNS of what it has recommended. 17 of 81
  spoken turns re-recommend a move already recommended in that game, at full
  length; and when the student finally plays it, the turn is silent.
- Silence on turns where the student played the engine's top move is DELIBERATE
  and is not a defect to be re-proposed: teaching a fork to a student who just
  played a fork is not teaching.\
"""

CONSTRAINTS = """\
- All inference must run on infrastructure the user controls, on open-weight
  models (Apache 2.0 preferred). A frontier model is allowed ONLY as an offline
  eval judge / design aid — never as the runtime coach. The runtime model is
  qwen3:14b served by Ollama; "local" here means ownership, not the laptop.
- ANY MEASURE YOU PROPOSE MUST BE COMPUTABLE FROM: the board (full legal move
  generation via python-chess), the student's move and the engine's preferred move
  in SAN, the eval drop, the phase, the prompt we composed (including the clause
  describing what the recommended move does and the closing lesson we instructed),
  the coach's output text, and every earlier turn of the same game. A measure that
  depends on matching PHRASES or WORDINGS in the coach's output is not acceptable:
  it has been tried repeatedly here and fails, because the model rewords freely, so
  a phrase list measures only the examples whoever wrote it happened to quote.
  Measures anchored on squares, on move tokens checked against the board, or on
  text we composed ourselves are acceptable — the model cannot paraphrase a
  coordinate.
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
    # See the module docstring for why opus-5 is the default rather than a cheaper
    # judge, and why the command is derived from the model instead of repeated.
    p.add_argument("--judge-model", default="claude-opus-5")
    p.add_argument("--judge-agent", default="judge-opus5")
    p.add_argument("--judge-command", default=None)
    p.add_argument("--judge-base-url", default="http://localhost:11434")
    p.add_argument(
        "--judge-timeout",
        type=float,
        default=1200.0,
        help="Seconds to wait for the review. The provider default of 300 is not enough here: "
        "this prompt carries the whole transcript plus the lever log (~300KB together), and a "
        "run timed out mid-generation at 300s with nothing written.",
    )
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

    # Via --agent, not --model: `--model` is a no-op in kiro-cli 2.22.1 and every review this
    # project recorded as claude-opus-5 was actually served by the `auto` default. See
    # `resolve_judge_agent`, which refuses to run when the agent file and the recorded label
    # disagree.
    if args.judge_command is None:
        resolved = resolve_judge_agent(args.judge_agent, args.judge_model)
        print(f"judge: agent {args.judge_agent} pins {resolved}")
    judge = create_provider(
        "cli",
        model=args.judge_model,
        base_url=args.judge_base_url,
        api_key="",
        command=shlex.split(args.judge_command or f"kiro-cli chat --no-interactive --agent {args.judge_agent}"),
        timeout=args.judge_timeout,
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
