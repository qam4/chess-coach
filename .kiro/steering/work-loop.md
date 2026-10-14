<!-- inclusion MUST stay `always` (no front matter). Per https://kiro.dev/docs/steering.md,
`auto` defers loading until the request matches a description, which is how commit-checklist
and project-overview silently stopped applying to the sessions that needed them most. -->

# The loop, bound to this project

The procedure is in the global `work-loop.md`. This file only says what each step means
*here* — which files are the record, what ground truth is, which instruments already exist,
and the thresholds measured on this codebase. If a step below disagrees with the global file,
the global file is the procedure and this one is out of date.

## Step 0 — the budget, and what the handoff must contain here

One backlog item per session. The handoff lives in `docs/coach-report-card.md` and
`BACKLOG.md`, and for this project it has to carry:

- the ledger row, with the counters and how each was measured — a number without its
  instrument is not a handoff;
- which sweep versions the numbers came from, and their transcripts committed, so the next
  session can re-derive them (`output/coach_review_v*/transcript.json` is tracked on purpose);
- anything retracted, marked as such in the row it corrects. Rows 164 and 165 carry
  amendments of exactly this kind;
- whether a measure is comparable across the change. B-014 exists because two counters are
  not, and that fact belongs with the numbers rather than in someone's memory.

A long sweep is a natural session boundary: launch it, end the session with the handoff
written, read the result in a fresh one. The sweeps take 14 minutes and the reading takes two,
so the context spent waiting is pure cost.

The opener for the next session is the item id alone — "take B-014 through the loop" — or
"where did we leave off?", which is answered from `docs/coach-report-card.md` and `BACKLOG.md`.
Both must work without the previous conversation. If a sweep is mid-flight when a session ends,
the handoff names the job id so the next one can read
`~/.kiro-monitor/runs/<job-id>/status.json` instead of relaunching it.

## Step 1 — the decision record

Search all of these, and report what came back including "nothing found":

- `docs/coach-report-card.md` — the ledger. Numbered rows, most recent last. The single most
  useful file in the repo: it holds what was tried, what it measured, and what was reverted.
- `BACKLOG.md` — open items with ids, plus a generated index (`scripts/backlog_index.py
  --check`). Closed items keep their measurements.
- `BUGS.md` — `BUG-nnn`, including fixed ones and the `PARTIALLY FIXED` ones.
- `src/chess_coach/engine_trust.py` — what we believe from the engine, what we do not, and
  what would change our mind.
- The target file's own comments. `prompts.py` in particular carries long notes recording what
  was measured at each lever; they are frequently the answer.

## Step 2 — ground truth

`python-chess`, against the FEN the turn is about. Reconstruct the board and check the claim.

A judge's per-ply claims are leads, never evidence: claude-sonnet-4.6 was wrong on 5 of 5
checked, and opus-5 produced three piece claims in one review that were all false. Its
structural observations have been reliable and are settled by counting across the corpus.

## Step 3 — the layers and the surfaces here

Layers, in the order the pipeline runs: engine output → `pedagogy/` selection →
`prompts.py` clause composition → the model → `verify.py` gate → fallback.

**Surfaces a student can reach, all five.** B-012 needed a withhold on every one:

1. the LLM path — `build_rich_move_evaluation_prompt` in `prompts.py`
2. the gate's fallback — `compose_safe_move_feedback` in `prompts.py`
3. template-only mode — `generate_move_coaching` in `coaching_templates.py`
4. the play payload — `web/server.py`
5. the UI — `web/static/app.js`

Committed transcripts under `output/coach_review_*/transcript.json` (93 of them) are fixture
data on purpose, so a corpus test is a real test. `output/` is otherwise gitignored: a check
reading uncommitted output protects nothing.

## Step 4 — the instruments that already exist

Generalise one of these before writing anything new:

- `scripts/eval_hard_metrics.py` — deterministic per-turn counters.
- `scripts/eval_prompt_coverage.py` — which prompt sections fire, engine only, no model, ~80s
  for five games. This is the coverage instrument; use it before spending the afternoon.
- `chess_coach.eval.run_compare` — SAME / MODEL / INPUT attribution, wired into
  `eval_repeat_budget.py --compare A B`.
- `scripts/eval_transcript_pairwise.py` — the quality instrument, 94% self-agreement.
- `scripts/eval_coach_rejudge.py` — re-judge a saved transcript with no coach, engine or
  tunnel, to isolate the judge's ask from the coach's output.
- `scripts/snapshot_clauses.py --check docs/clause-snapshot.tsv` — 5062 positions; run it on
  any change to the clause pipeline.

Anchor measures on the board or on text we composed, never on the model's words — see "No
regex, phrase list or keyword match over prose a model wrote" in `working-agreements.md`, which
`tests/test_model_text_matchers.py` enforces. The retired phrase list is kept in the code only as
a warning against rebuilding it.

**`verify.py` is not an instrument to reuse.** This list used to say its `_SAN_RE`,
`_legal_san` and `_recommended_tokens` "already encode which moves this text names, and whose —
do not write a second move parser". They do it by reading the model's wording ("better",
"opponent", reply-verb lists), so that line pointed agents at exactly what the rule forbids, and
the gate's word lists grew under it. They predate the ruling: do not extend them, do not copy
them, and do not build a measure on top of them.

## Step 5 — what a good gate message looks like here

Two real turns with their real coach text, pulled from a committed transcript, one the measure
flags and one it does not. The owner has said plainly that a measure described in the abstract
means nothing until applied to an example.

## Step 6 — attribution and the noise floor here

**Identical prompt ⇒ identical output.** Twelve repeat runs gave standard deviation zero on
every counter. So `run_compare` reporting no prompt change means the change did nothing — that
is how a token-ceiling lever was caught producing byte-identical output after a plausible code
comment had already asserted it was binding.

**The report card's 0-10 score is noise.** 5.5, 5.0 and 2.0 on byte-identical input, and four
of seven category scores move on a re-run of one transcript. Never the acceptance test; the
written critique is the useful output.

## Step 7 — generalising here

Five seeds minimum: 7 standard, 11 Italian, 13 Queen's Gambit, 17 Sicilian, 23 French. Every
ledger number up to v43 rests on seed 7 alone, which the owner raised before it was acted on.

Anything prompt-side also goes through the four-model matrix — a fix that only works on
qwen3:14b is not known to be a fix.

Coverage varies far more than expected: piece history reached 2 of 18 turns, centre control 0
of 36.

## Step 8 — done, here

`pytest`, `mypy src/`, `ruff check src/ tests/ scripts/`, `ruff format --check src/ tests/
scripts/`, plus the clause snapshot when the clause pipeline moved. Then CI — see
`commit-checklist.md`, and check it rather than assuming.

Ledger row in `docs/coach-report-card.md`, `BACKLOG.md` updated. Rows for items that died
before any code exist and are worth more than the rest: row 158 (measured first, said no,
nothing built) and rows 160 and 165 (built, measured as nothing, reverted).

## Running a sweep

The model is `qwen3:14b` over an SSM tunnel on `localhost:11435`, not a local process. Use
`scripts/run_coach_review_tunnelled.ps1`, which opens the tunnel, waits for a real HTTP
response rather than just the port, and starts the run with no idle gap — the tunnel drops if
it idles. Do not redirect `~/ec2-ssm.sh` output to a file: it prints live AWS credentials.

Launch long sweeps detached via kiro-monitor (see the global `kiro-monitor.md`). Five seeds
with `--no-judge` is about 14 minutes.

## Division of labour with Blunder

The engine answers what is TRUE about the position; this project answers what is worth
TEACHING and how. Rules geometry via `python-chess` is ours. Do not work around an engine
shortcoming — drop the untrustworthy data, record it in `engine_trust.py`, fix it in Blunder.
