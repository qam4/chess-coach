# Coach report card — progression log

The **coach report card** is a single-mode holistic review (not an A/B): it
plays one real game, coaches every student move with the shipping config while
timing each generation, appends curated endgame/tactic positions for phase
coverage, then a frontier reviewer (claude-sonnet-4.6 via kiro-cli) returns one
verdict — a **0–10 score against the VISION "bridge" standard** plus honest
critique and phase-fit. It answers "is the coach the teacher we envisioned?".

- Tooling: `scripts/eval_coach_review.py` (driver) + `src/chess_coach/eval/coach_review.py` (pure core).
- Run: `--seed 7` fixes the game so successive runs are a clean before/after.
- Artifacts live under `output/` (gitignored); results are recorded here.

## Measurement philosophy (what to trust)

The 0–10 score is **noise-dominated at n=1** and must NOT be the optimization
target. Proof: five runs of the *identical* game (seed 7) with monotonically
refining prompts scored **3.5 → 4.2 → 4.5 → 4.5 → 3.5** — a ~1-point band, and
the last run (lever 4) scored *below baseline* despite outputs that are
demonstrably better differentiated. So we judge a lever by, in order of trust:

1. **Deterministic fidelity counts** (off_menu / unsound_move / placement /
   piece_type) — objective, no noise.
2. **Direct inspection of the outputs** — did the change do what it was designed
   to do (e.g. did best-move replies actually shorten)?
3. **The judge's qualitative shortcomings** — the *prose* critique is stable and
   informative across runs; that is the report card's real value.

The 0–10 score is kept only as a rough directional band, never as the thing we
tune against.

All runs below: qwen3:14b coach, sonnet judge, seed 7, 44 coached turns
(10 opening / 16 middlegame / 18 endgame; 23 good / 9 inaccuracy / 8 mistake /
4 blunder).

## Progression

| # | change | judge score | off_menu | unsound | placement | kept? |
|---|--------|:-----------:|:--------:|:-------:|:---------:|:-----:|
| baseline | shipping config (guidance on) | 3.5 | 8 | 4 | 1 | — |
| lever 1 | remove always-on opening "CHESS PRINCIPLES" crib from `SYSTEM_PROMPT_V2` | 4.2 | 8 | 5 | 1 | **yes** |
| lever 2 | add grounding rule: don't invent causal chains ("allows/supports/weakens") | 4.5 | 9 | 4 | 1 | **reverted** |
| lever 3 | severity-tiered response (tone + length by eval-drop band; no filler sign-offs) | 4.5 | **4** | **2** | 2 | **yes** |
| lever 4 | enforce per-tier length (word limit + max_tokens) in builder/Coach/driver | 3.5 | 4 | 2 | 1 | **yes** |
| lever 5 | tiers demand the concrete consequence (state the refutation line) | — | 7 | 6 | 1 | **reverted** |
| lever 6 | concrete consequence done right: first reply only + opponent-aware checker | 4.5 | **3** | 2 | 1 | **yes** |
| lever 7 | position→principle ordering (prompt directive; refined to anchor to data) | — | 4 | 3 | 2 | **reverted** |
| lever 8 | opponent's-reply block states the captured piece (composed from board) | 4.5 | 3 | 2 | 1 | **yes** |

**Lever 1 (kept).** The static crib was injected on every turn and drove
recycled generic advice ("develop your pieces / is my king safe?") even in the
endgame. Removing it lifted the holistic score (+0.7, directional) with **zero
change to deterministic fidelity** and no regression; low-risk (the pedagogy
guidance layer still supplies a principle). Kept.

**Lever 2 (reverted).** A bare "don't invent cause-and-effect" grounding rule
did **not** measurably reduce fabrication — off_menu 8→9, unsound 5→4 (flat),
and the judge still cited hallucinated justifications. +0.3 is within noise.
No demonstrable benefit, so it was reverted to keep the prompt lean (a negative
result is a valid finding: qwen3:14b doesn't reliably follow a negative
constraint on causal reasoning the way it followed the concrete "no `and
then...` continuations" rule).

**Lever 3 (kept).** Severity-tiered move feedback — the response's directness
and length scale with the eval-drop band (best/sound → short affirmation;
inaccuracy → brief redirect; serious → direct "lead with the cost", no
cushioning), keyed on OUR own bands (`SOUND_MAX_DROP_CP`/`DUBIOUS_MAX_DROP_CP`),
never the engine's label (BUG-016). Score flat (+0.3, within noise) but the
**trustworthy signal moved: off_menu + unsound roughly halved (13 → 6)** — the
tighter, tiered responses give the model fewer openings to ramble into off-menu
/ fabricated recommendations — and the judge now lists calibrated severity as a
*strength*. Kept (measurable deterministic benefit, no regression), unlike
lever 2. What it did NOT fix: the model under-delivers on the *length/depth*
part from prompt text alone — still ~3-5 sentences on best moves, still opens
with "Great job!", still platitudes on blunders. The judge's new #1: enforce
depth differentiation by quality + phase (blunders longest/most specific;
top-moves one sentence) and give opening moves a *named opening concept*. Two
future levers: (a) enforce length/depth (prompt text isn't enough — likely
per-tier generation limits); (b) opening-specific content.

**Lever 4 (kept — on direct evidence, NOT the score).** Per-tier word limit +
`max_tokens`, wired into the prompt builder, the runtime `Coach`, and the
report-card driver, via a shared `_move_feedback_tier` helper (bands are our
own, per BUG-016). Direct inspection confirms it did its job: best-move replies
dropped to ~23–35 words (from ~100+), blunder replies stayed longer and got
more concrete ("Kd1 … allows Black to capture your knight on g5"); no
truncation; deterministic fidelity held (off_menu 4 / unsound 2). The judge
score fell to 3.5 — but that is the noise band (see above), contradicted by the
direct evidence, so lever 4 is kept.

**Lever 5 (reverted — backfired).** Sharpening the tiers to "state the
Refutation Line explicitly" made the coach dump the raw multi-move PV as
move-salad — ply 20: "After Kd1, Black plays fxg5, fxg5, Ne5, Bb2, d6, Bxe5,
dxe5, Nd2" — *worse* than lever 4's clean "allows Black to capture your knight
on g5", and `illegal_move` spiked 0 → 5 (off_menu 4→7, unsound 2→6). Two
insights it surfaced:
1. **It re-opened BUG-013.** "Voice the line" fights the "don't narrate
   `and then...` continuations" rule; the model recites a long, partly-garbled
   PV.
2. **The illegal_move spike is largely a checker artifact.** The coach now
   names the *opponent's* reply ("Black plays fxg5"), but the fidelity checker
   validates every named move against the pre-move position where it's the
   *student* to move — so a correctly-attributed opponent reply is flagged
   illegal. The checker can't tell "opponent's punishing reply" from "a move I
   recommend the student play."

The concrete-consequence direction is still right (ply 34's "After Ke2, Black
plays ...Qa5, targeting your king" is exactly it), but it needs a **proper
design, not a prompt tweak**: (a) name only the opponent's *single immediate
reply* (the first move of the refutation line), tersely — never the whole PV;
(b) make the checker **opponent-move-aware** so a correctly-attributed reply
isn't counted illegal. Deferred as a small feature.

**Lever 6 (kept — the proper concrete-consequence feature).** Three parts that
fixed what lever 5 broke: (a) `_format_refutation_line` renders only the
opponent's FIRST reply (a single move), never the PV; (b) the SERIOUS tier
voices that one reply and forbids listing a sequence; (c) the fidelity checker
is opponent-move-aware (`_attributed_to_opponent`) so a correctly-attributed
"the opponent plays X" reply isn't counted as an illegal student move. Result —
the best deterministic run of the series and the lever-5 regression gone:
**illegal_move 5 → 0, off_menu 7 → 3** (lowest yet), unsound 6 → 2. Qualitatively
the move-salad is gone and blunders now name the single concrete consequence
("the opponent plays fxg5, winning material"; "exd4, winning a pawn"). Graceful
degradation when no refutation is available (ply 34 hedged rather than
fabricating). Kept.

**Lever 7 (reverted — costs accuracy).** A prompt directive to lead with the
concrete position point flipped the ordering nicely (blunders opened with "your
opponent plays fxg5, winning material") but pushed the model to assert more
board facts than it can ground: fidelity regressed (raw: illegal_move 0→1,
placement/piece_type 1→2). Refining it to "only from the data shown, don't
invent" fixed the worst (illegal_move back to 0, off_menu down) but the
accuracy-critical categories stayed doubled (placement 1→2, piece_type 1→2).
Per the rule "do not sacrifice accuracy," reverted.

**Lever 8 (kept — the Layer-1→Layer-2 lesson, proven).** After lever 7 showed a
prompt directive can't add concreteness without inventing, lever 8 does it the
composed way: `_refutation_capture_clause` computes what the opponent's reply
captures — reading the piece off the board *after* the student's move — and the
"Opponent's reply" block states it verbatim ("capturing your knight on g5").
Result: deterministic fidelity identical to the clean v6 baseline (off_menu 3,
unsound 2, placement 1, piece_type 1, illegal 0) — **zero accuracy cost** — while
blunders gained a concrete, verified consequence. Decisive evidence: at ply 30
the model's own guess in earlier runs was "winning a pawn"; the composer
computed the truth (a white **bishop** sat on d4, captured by ...exd4) and the
coach voiced "capturing your bishop on d4." **The composer corrected a model
hallucination at no cost — exactly the pattern below.**

## The pattern across levers (the strategic lesson)

Sorting the levers by outcome reveals a sharp, consistent rule:

- **KEPT — levers 1, 3, 4, 6:** each either removed noise (drop the crib) or
  **composed/constrained a verified fact deterministically and had the LLM
  voice it** (severity bands from our eval-drop, per-tier length, the opponent's
  first reply rendered from the refutation + an opponent-aware checker).
- **REVERTED — levers 2, 5, 7:** each **asked the LLM to *derive* more** via a
  prompt directive — "don't fabricate causal chains" (no effect), "state the
  refutation line" (move-salad), "lead with the concrete point" (invented
  facts). All regressed or did nothing.

**Conclusion: we have hit the ceiling of prompt-directing the local model toward
more concreteness. Every further teaching gain has to move the concreteness OUT
of the LLM's derivation and INTO deterministic Layer-1 composition — compose the
verified point, hand it over, and let the LLM only *voice* it.** That is the
"Layer 1 facts → Layer 2 voice" principle, and it is what every kept lever
already does.

## Stable qualitative findings (across all runs — the real signal)

1. **Generic recycled principle.** A small rotating set of platitudes
   ("develop knights and bishops", "king safety", "improve your pawn
   structure") repeats regardless of position — one generic lecture
   masquerading as 44 lessons. Lever 1 helped but did not eliminate it.
2. **Flat severity + uniform verbosity.** Blunders and best moves get the same
   warm opener ("Great job / It sounds like you were aiming to…") and the same
   4–6 sentences. A −878cp blunder feels identical to a 0cp best move. The
   judge promoted this to its **#1 highest-leverage change** by run 3: a
   *severity-tiered response protocol* (blunder → direct "this was a serious
   mistake, here's why it loses" + fix; good move → one short affirmation + one
   idea; inaccuracy → brief redirect).
3. **Fabricated / off-menu causal claims.** ~13 deterministic off_menu/unsound
   per run, plus invented mechanisms ("Bc4 allows …capture on d4", "a3 supports
   d4"). Stable; not fixed by lever 2's prompt rule. Likely needs a stronger
   mechanism than a negative instruction (e.g. constraining named moves to the
   menu / a repair pass) — revisit after severity tiering.

## Next: extend the composed-lead approach

Lever 8 delivered the blunder side of the concrete lead (the verified captured
piece). Two accuracy-safe extensions remain, both composed-not-derived:

- **Good / best / sound moves:** the coach is still generic here ("develop your
  pieces"). Surface the engine's `best_move_idea` (a structured field) more
  prominently and have the coach voice *it* as the specific idea, rather than a
  generic principle. Composed, so no invention risk.
- **Non-capture refutations:** when the opponent's reply is a strong non-capture
  (a check, a fork, a quiet killer), the capture clause is empty. Consider
  composing the motif (from the engine's tactic/threat data for that reply) so
  those blunders also get a concrete "why", not just the move.

Deferred companion (bigger, and likely necessary): opening-specific *content*
(named openings / plans) fed as data — the opening phase stays the most generic
and needs real content, not ordering. This is a knowledge/engine-feature build,
not a prompt change.
