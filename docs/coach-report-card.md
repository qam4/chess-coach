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
| lever 9 | good-move tiers voice the engine's best_move_idea, not a generic principle | 4.5 | 3 | 2 | 1 | **yes** |

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

**Lever 9 (kept).** The good-move tiers (best/sound/inaccuracy) now tell the
coach to voice the engine's `best_move_idea` — the "What the best move achieves"
field already in the prompt — instead of a generic principle. Composed, not
derived, so accuracy-safe by construction. Good moves became position-specific
("Nc3 focuses on rapid development, activating a knight toward the center";
"Bc4 develops a bishop to a strong, active square, prepare for castling")
rather than "develop your pieces". Fidelity stayed at the clean baseline except
placement 1→2 — a single count within the series' 1↔2 noise band and not
attributable at n=1 (voicing an engine field shouldn't cause a placement
error). Kept.

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

Levers 8 and 9 delivered the concrete lead on both sides (verified captured
piece on blunders; the engine's idea on good moves). One accuracy-safe
extension remains, plus the bigger deferred item:

- **Non-capture refutations:** when the opponent's reply is a strong non-capture
  (a check, a fork, a quiet killer), the capture clause is empty. Consider
  composing the motif (from the engine's tactic/threat data for that reply) so
  those blunders also get a concrete "why", not just the move.

Deferred companion (bigger, and likely necessary): opening-specific *content*
(named openings / plans) fed as data — the opening phase stays the most generic
and needs real content, not ordering. This is a knowledge/engine-feature build,
not a prompt change.

## Architecture review (2026-08-10) — the design critique, and the action list

After ten levers we hit the ceiling of interpreting an *output-only* judge: the
report-card reviewer never saw the prompt, the composers, the pedagogy layer, or
the lever history, so it kept re-proposing things we had already reverted. So we
built `scripts/eval_architecture_review.py` (+ `build_architecture_review_prompt`),
which hands a frontier model the **internals** — the exact rendered prompt, an
architecture summary, the hard constraints, and this lever log — and asks for a
DESIGN critique. Its verdict was materially more useful than any output review.

**Soundness:** the architecture is right and "Layer 1 composes verified facts /
Layer 2 voices them" is the correct load-bearing design (every kept lever
confirms it). The ceiling is not the architecture — it is **how much we still
leave the model to derive.**

**The architectural flaw it named (new, and a root cause we had not identified):**
the **pedagogy YAML layer is doing double duty it cannot do**. It is both the
content source ("what principle applies here") and the teaching scaffold ("how to
connect it to this position"), but a YAML entry can only supply an *abstract*
principle. The prompt therefore hands the model generic prose, and — quoting —
*"you cannot prompt your way out of this because the abstract text IS what the
model anchors to when the position-specific signal is weak."* That explains the
recycled-template problem we fought from lever 1 onward, and why levers 2/5/7/10
kept producing a *new* template rather than fixing it.

**Second root cause:** `best_move_idea` is a **category label**, not a fact
("piece activity — improving piece placement"), so voicing it can only produce
category sentences. Lever 9 was right to wire it in and wrong to stop there.

**A concrete bug it caught:** non-capture refutations get **no** composed
description (levers 6/8 handled captures only). On ply 8 the PV first move was
`f6g4` (a knight move); the coach said "gaining a strong central pawn" and our
`piece_type` counter fired.

### Baseline for the new metrics (item 1 — DONE, measured on the v13 transcript)

| metric | value | reading |
|---|---|---|
| specificity rate | **25%** | only 1 turn in 4 names a square/piece beyond the move itself — the "hollow second end of the bridge", quantified |
| principle-connection rate | **39%** | the principle is instantiated on the board in under half of turns; the rest is abstract recycling |
| fidelity by phase | endgame 5, opening 3, middlegame 1 | **overturns the review's guess** that the endgame would be cleanest and the opening worst — composer work should target the ENDGAME first |

That last row is why these metrics matter: a plausible narrative from the
reviewer was wrong, and a zero-noise count caught it. Both rates are the
before-numbers for items 2-4.

### Action items (in execution order)

1. **[metrics] Add deterministic teaching metrics to the report card** — DONE —
   *specificity rate* (does the response name a position-specific square/piece
   beyond the moved piece?) and *principle-to-position connection rate* (does a
   fired principle appear near a square reference?), plus a **per-phase fidelity
   breakdown**. Regex-checkable, zero-noise, and they measure the bridge
   directly — better than the noisy 0-10. Do this FIRST so the remaining levers
   are judged on stable numbers.
2. **[composer] Non-capture refutation description** — DONE (kept, but
   UNMEASURED end-to-end). `_refutation_capture_clause` now describes any
   opponent reply from the board: capture ("capturing your knight on g5",
   en-passant aware), fork ("hitting your queen on g5 and your rook on f4",
   most valuable first), single undefended ("attacking your undefended rook on
   f4"), check-only ("giving check"), else empty (never an invented "why").
   Pawns/king are excluded as named targets — an early version turned a real
   check into a pawn inventory, caught by testing against real boards.
   **Honest caveat:** the seed-7 game contains only **3** refutation-bearing
   turns and **all 3 are captures**, so the new branch never fired and the run
   metrics were byte-identical to v13. Unit tests verify all four branches on
   real positions; the change is strictly additive (empty when nothing is
   verifiable), so it is kept — but no measured game-level win is claimed.
   **Harness lesson:** one game cannot validate blunder/refutation-focused
   levers (3 of 44 turns). Before items 3-4, either run 2-3 seeds per
   measurement or add curated blunder/refutation positions (as we did for
   endgame coverage), or those levers risk the same "no-op / can't tell"
   outcome.

   **2b. [bug] Raw UCI was still reaching the coach — found while validating 2,
   now FIXED.** Chasing "why didn't item 2 move anything" uncovered a much
   bigger defect: a `ComparisonReport`'s `top_lines` describe the position AFTER
   the student's move (they open with the opponent's reply), but
   `_format_comparison_top_lines` converted SAN from `report.fen` (before it).
   The first move was illegal there, and `_uci_line_to_san`'s **silent**
   fault-tolerant fallback emitted the WHOLE line as raw coordinates —
   `f6g4 f2f4 e5c4 ...` — which the coach parroted and then invented a meaning
   for ("gaining a strong central pawn"; the correct SAN is `Nfg4`, a knight
   move). So the documented SAN migration was real but silently degraded in
   exactly one section. Root cause of the *remaining* leaks after the base-FEN
   fix turned out to be an **engine bug** (BUG-019: inconsistent PV, two Black
   moves in a row), so the converter genuinely could not replay the tail.
   Fix, in three parts: (a) correct base position; (b) `_uci_line_to_san` now
   **truncates** at the first unreplayable move with `...` and NEVER emits
   coordinates — an unconvertible first move omits the section entirely;
   (c) two guards, because a log warning is not a guard: a **CI sentinel test**
   (no bare UCI token in any rendered comparison prompt, all tiers) and a
   **`prompt_uci_leaks` metric** in every report-card run's stats.
   Measured: **prompt_uci_leaks 27/44 -> 19/44 -> 0/44**; total fidelity
   violations 9 -> 8; specificity/principle-connection unchanged (25% / 34%).
   **2c. [fix] PV side attribution — DONE, and it worked.** SAN fixed
   readability but not *whose move is whose*: at ply 8 the coach said "the
   opponent plays f4" when `f4` was the student's own (White) move — the second
   ply. A bare SAN sequence hides the alternation, so the model grabbed the
   wrong ply. `_uci_line_to_numbered_san` now renders move numbers from the
   board (`5...Nfg4 6.f4 Nxc4 7.bxc4`), and the section header names which
   colour is the opponent. Scope was verified before building, not assumed:
   this was the ONLY unlabelled multi-move surface (the refutation block,
   tactics, move menu and move fields all already carry attribution, and the
   position prompt has no raw PV since the move-menu work). A separate function
   was added rather than changing `_uci_line_to_san`, to leave the
   just-fixed refutation path untouched. Three off-by-one hazards were checked
   against real boards first: Black-start (`5...`), truncation of the engine's
   corrupt tail (numbering survives), and White-start (no spurious `...`).

   **Measured (v16 -> v17):** the ply-8 sentence is now correct ("the opponent
   plays **Nfg4**"), and the deterministic metrics improved — total violations
   **8 -> 6**, `piece_type` **1 -> 0** (consistent with the mechanism: the coach
   had been misreading which move, hence which piece, belonged to whom),
   specificity 25% -> 27%, principle-connection 34% (flat), leaks still 0. Best
   deterministic result of the series (baseline: 9 violations, 27 leaks).
3. **[composer] Compose the best-move "why" from the board** — DONE, and the
   **biggest single win of the series.** Evidence first: across the 44 turns
   `best_move_idea` had only **10 distinct values** (`king safety —
   repositioning the king` x13, `rook activity — improving rook placement` x8),
   so voicing it could only ever produce category sentences.
   `_best_move_achievement` now prepends a verified board-derived clause and
   keeps the label as the theme; the opponent's-reply and best-move clauses were
   unified into one `_move_effect_clause` (capture / fork / check / attack /
   escaping an attack / defending) so they cannot drift. Coverage was measured
   BEFORE spending a run: **31/44 (70%)** of best moves get a concrete clause;
   the rest return the label unchanged rather than inventing.

   **Measured (v17 -> v18): specificity 27% -> 66%, principle-connection
   34% -> 64%** — both roughly doubled — with **no fidelity cost** (total
   violations flat at 6, placement 1 -> 0, leaks still 0). The prose confirms the
   mechanism: ply 8 went from "Nfg4, gaining a strong central presence" (vague)
   to "Nfg4, **attacking your bishop on c4**" + "Be2, **moving your bishop to a
   safe and active square**"; ply 66 from "repositioning your king for better
   safety" to "repositioning your king to **target the opponent's rook on f4 and
   bishop on g4**". The coach says *why* in board terms because it was handed
   the fact.

   Two guards caught mistakes during the refactor and are worth noting: an
   existing test caught a word-order regression ("undefended your rook"), and
   **mypy caught dead code** the refactor orphaned (an unreachable branch using
   an undefined name). One "failure" was the test being wrong, not the code —
   the b4 bishop really is defended by the f8 bishop.
4. **[pedagogy] Instantiate the guidance block** — add an
   `instantiation_template` to each YAML entry with slots filled by the *board
   fact that made the feature fire* ("your Nb1 and Bc1 haven't moved yet — Be2
   develops toward the center"). Pure string composition; the LLM rephrases a
   specific claim instead of deriving one. This is the fix for the named
   architectural flaw.
5. **[option, not a recommendation] Blunder-only second pass** — a short
   self-critique call on the ~9% of turns that are blunders. Violates the
   one-LLM-call rule and doubles latency there; only pursue if 2-4 leave blunder
   quality unacceptable, with a hard fallback to pass 1.

### Stop doing (per the review)

- **Stop tuning the grounding rules** — lever 2 proved negative constraints on
  this model's causal reasoning have no measurable effect; the section is
  already long.
- **Stop leaning on `best_move_idea` as-is** — replace the label with a composed
  fact rather than voicing it harder.
- **Stop iterating on prompt ordering** — lever 7 showed available facts outweigh
  what the model is told to lead with. Revisit ordering only after grounding
  improves.
