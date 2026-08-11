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

**You cannot check LLM prose by matching words against it.** That is the whole
reason the end-to-end frontier review exists: its written critique is the real
check on whether the coaching teaches anything. The numbers are here to anchor
that review in facts and to catch regressions.

Every number we keep answers a question that can be checked, and they come in two
kinds.

**Checked against the position.** The fidelity counts (`off_menu`,
`unsound_move`, `illegal_move`, `placement`, `piece_type`) come from `verify.py`,
which pulls move tokens out of the text and parses them against the real board.
Those can tell us the coach was *wrong*. `prompt_uci_leaks` checks our own
rendered prompt. Latency, `empty_feedback` and the phase / move-quality mixes are
plain counts.

**Checked against our own prompt.** `composed_fact_rate` (the coach named a square
we gave it) and `unsourced_square_rate` (it named one we did not). Both are facts
about our own data rather than guesses about meaning. Neither says whether the
sentence around the square is true or worth reading.

**One metric was deleted rather than kept with a caveat.**
`principle_connection_rate` looked for a word from a hardcoded list within 120
characters of a square, meaning to catch a principle stated abstractly instead of
applied to the position. It could not: words like "material", "capture",
"exchange" and "center" appear in essentially any chess sentence, so **all 44
responses** in the v19 transcript contained one, 95% contained a square, and it
reported 91% against that 95% ceiling. It also passed on prose written
specifically to fail it — *"Nf3 is a good move. In general, development matters a
lot in the opening."* Nothing was wrong with the code; the idea was wrong, and a
number that always says yes is worse than no number, because someone will cite it.
Whether the coaching bridges a principle to a position is the frontier review's
question.

**Do not maximize any of the rest either.** Every one can be improved by padding
the output with square names, which would make the coaching worse while the
numbers looked better.

**The 0–10 score is noise-dominated at n=1** and must NOT be the optimization
target either. Proof: five runs of the *identical* game (seed 7) with
monotonically refining prompts scored **3.5 → 4.2 → 4.5 → 4.5 → 3.5** — a ~1-point
band, and the last run (lever 4) scored *below baseline* despite outputs that are
demonstrably better differentiated.

So a lever is accepted or rejected on: the board-validated counts, direct reading
of the outputs, and the review's prose critique. Never on a rate alone. A rate
that moves is a hint to go and read something.

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
4. **[pedagogy] Instantiate the guidance block** — DONE (kept; mechanism right,
   measurable gain small). Implemented leaner than the review proposed: instead
   of adding an `instantiation_template` to all 20 YAML entries plus a
   slot-filling mechanism, note that an entry fires *because* a board feature
   was found — so `pedagogy/instantiate.feature_facts(report)` composes the fact
   for that feature and `_render_entry` appends it as `HERE: ...`. No schema
   change, no content authoring, and the fact comes from the report the selector
   already matched against.

   Two self-inflicted bugs caught before running, both the failure mode we keep
   fighting: (a) the first version emitted "you are ahead in material" and "a
   capture is available" **unconditionally** — false in the starting position —
   so facts are now filtered to features actually present, with a regression
   test; a fabricated "fact" is worse than the abstraction it replaces.
   (b) The "pieces still at home" fact was keyed to `phase:opening`, which TWO
   entries share, so it landed on the wrong theme ("center control … HERE: your
   bishops have not moved"); that mapping was dropped — only semantically
   matched facts are emitted. mypy also caught a typing error in the
   wing-majority loop.

   **Measured (v18 -> v19): fidelity is the cleanest of the series — total
   violations 6 -> 5, and BOTH board-fact categories are now zero (placement 0,
   piece_type 0)**; only constraint-adherence violations remain (off_menu 3,
   unsound_move 2). But **principle-connection moved only 64% -> 66% and
   specificity was flat at 66%** — within noise for one run, so no teaching win
   is claimed. Inspection explains why: 39/44 prompts carried an instantiated
   fact, but the model consistently preferred the **move-anchored** fact from
   item 3 over the position-level guidance fact (offered "a fork involving
   d5, c4", it voiced "attacking Black's knight on e5"). For move feedback that
   is arguably correct — the coaching is *about a move* — and item 3's clauses
   are simply more specific. Kept because the mechanism removes abstract-only
   guidance (the named flaw), fidelity improved, and it cannot fabricate.
   **Hypothesis worth testing later:** item 4 should pay off on the
   *position-coaching* path (`chess-coach explain`), where there is no move to
   anchor to — untested here.
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

## Second architecture review (v3, after items 2b/2c/3/4)

The review script was re-run with the `ARCHITECTURE` summary updated to describe
items 2b/2c/3/4, so the frontier reviewer critiqued the *current* design rather
than the one it had already commented on. Full text: `output/architecture_review_v3/review.md`
(gitignored). Two process notes worth keeping:

- The rendered prompt plus architecture summary blew past Windows' ~32k command
  line limit. No new plumbing was needed: `CliProvider` already pipes the prompt
  on **stdin** when `{prompt}` is omitted from `--judge-command`. The usage
  docstring now says so.
- The first re-run reported "specificity 0% — alarming", which was **a bug in the
  script, not a regression**: it rebuilt `ReviewStats` field by field from the
  saved JSON and silently dropped every metric added after it was written. Fixed
  with `ReviewStats.from_dict` plus a regression test that fails if a field is
  dropped. A measurement harness that silently zeroes a metric is worse than no
  metric, because it invites a "fix" for a problem that does not exist.

**What the review confirmed.** Compose-facts-and-let-the-model-voice-them is the
right architecture; every kept lever obeys it and every reverted lever broke it.
It independently reached the same conclusion as our own item-4 inspection: the
guidance block is now "a third competing fact stream" that loses to the
move-effect clause, at roughly "three-to-one abstract:concrete tokens". It named
**coverage** — the 30% of best moves that still fall back to a bare category
label — as the fundamental remaining limit, not anything architectural.

**Recommended changes, in its priority order:**

- **A — compose the missing 30%.** Extend `_move_effect_clause` with branches for
  quiet improving moves: landing on an open file, centralizing, activating a
  previously blocked piece (legal-move count before vs after). Additive, no LLM
  involvement, and coverage is measurable before spending a run.
- **B — merge guidance INTO the move-effect clause instead of alongside it.**
  Pick the guidance entry whose feature matches the move-effect category and emit
  one teaching point; drop the block when nothing matches. Removes the
  abstract:concrete imbalance without removing the pedagogy layer.
- **C — mark the fallback honestly.** Tag the label-only case
  `[category only — no specific fact]` and instruct the coach to hedge. Today the
  prompt demands specificity while handing over an abstraction, and the model
  resolves that conflict by fabricating.
- **D — compose the takeaway hook** from (move-effect category x guidance theme)
  templates. Deferred by the review itself until A and B are measured; it is
  authoring work, ~20-30 templates.

**Measurement gaps it flagged:**

- `specificity_rate` cannot tell "specific because composed" from "specific
  because the model guessed right". A `composed_specificity_rate` counting only
  squares that appear in a composed prompt field would make the delta between
  the two an explicit hallucination buffer.
- The seed-7 game is too uniform for rare paths (3 of 44 turns carry a
  refutation). Curation should be systematic: one position per
  (move-quality x phase) cell plus a fixture per composer branch. Most of that
  can run as a prompt-rendering regression suite with **no LLM at all**.

**And one item it promoted that we had parked:** the opening is the *worst* phase
(3 fidelity violations vs middlegame's 1) and named openings are composable from
ECO data — a Layer 1 fact, not a prompt directive. That reframes "opening
content" from polish to the highest-violation target.

## Item 4 on the position-coaching path — and the attachment bug it exposed

Item 4's hypothesis was that instantiating guidance with a board fact should pay
off more on the **position-coaching** path than on move feedback, because there
is no move to anchor to. Wiring it there took one line
(`build_rich_coaching_prompt` already holds the `PositionReport`). Measuring it
took three attempts, and the second failure was the actual finding.

**Dead end 1 — a saturated metric.** Scoring the position path with
`is_specific` / `connects_principle` gave **6/6 facts-off vs 5/6 facts-on**. Both
metrics were built for move feedback, where the student's and engine's move
squares are *discounted*; the position path has no such move, so any square
mention passes, and a position explanation always puts a theme word near a
square. The run was discarded rather than reported — a saturated metric cannot
answer the question, and "5/6 vs 6/6" would have read as a regression.

**Dead end 2 — the metric could not find the facts.** Rescoring on "does the
composed fact reach the output" (the review's Gap-1 `composed_specificity_rate`)
**skipped 4 of 5 positions**, because no *selected* entry carried a fact at all.

**The coverage measurement.** Offline, engine only, no LLM — the same discipline
that saved a run on item 3. Over 10 positions: **10 of 30 selected entries (33%)
could be instantiated**, 6 of 10 positions carried a single fact, and every
opening position carried none. So item 4's small gain on move feedback was never
really about the model's preferences; two thirds of the mechanism was not
reaching the prompt.

**Cause, verified rather than guessed.** Entries tie on relevance (each matches
exactly one present feature) and the tie-break — type, then `id` — is blind to
whether a fact exists. In a position with a live threat, the abstract
`center control` beat `answer the threat first`, which would have rendered
"HERE: there is a live threat against f7".

The first fix folded the fact bias into the existing `preferred_features` hook
and reached only 18/30. Instrumenting the misses showed **two soft biases
colliding**: the engine's PV theme `"piece development"` maps to the broad
`phase:opening` feature, so the move-theme bias handed the same +1 to all three
abstract opening entries and cancelled the fact bias out; the `id` tie-break then
picked the abstraction. Fixed by giving instantiability its own `_sort_key` term,
above the theme bonus and below relevance.

| | attachment (selected entries) | positions with >=1 fact |
|---|---|---|
| before | 10/30 (33%) | 6/10 |
| fact bias inside `preferred_features` | 18/30 (60%) | 8/10 |
| fact bias as its own rank term | **23/30 (77%)** | **10/10** |

Still a tie-break: it never admits or drops an entry, and a genuinely more
relevant entry still wins — both have regression tests. The remaining 7 of 30
are positions with fewer than three eligible fact-bearing entries, which is a
content-coverage limit, not a ranking one.

**The transferable lesson** is about the harness, not the coach: two of the three
attempts failed because a metric borrowed from another path could not
discriminate on this one, and a third of the pipeline was silently inert. Before
spending LLM runs, check that the mechanism under test actually fires — the same
mistake as the `ReviewStats` bug that told a reviewer specificity was 0%.

## Correction: the square regex was blind to SAN, so the headline metrics were wrong

Reading the position-path responses turned up a measurement bug, not a coaching
one. `_SQUARE_RE` was `\b[a-h][1-8]\b`, which finds **no square at all** in
`Ra8#`, `Rxc8#`, `Nf3` or `cxd5` — the leading piece or file letter kills the
word boundary. Measured against the move generator, it missed the destination
square of **76.1% of all legal moves**. Two consequences, in opposite directions:

- `connects_principle` missed every case where the coach named a square in SAN,
  so principle-connection was **under**-reported.
- `is_specific` builds its discount set from the move SANs, so that set was
  **empty for every piece move** and nothing was discounted. Coaching that only
  echoed the played/best move's own square was credited as specific, so
  specificity was **over**-reported.

The transcripts are saved, so the corrected numbers cost nothing to recompute
(no LLM, no engine):

| run | specificity (was -> is) | principle-connection (was -> is) |
|---|---|---|
| v17 (before item 3) | 27% -> **34%** | 34% -> **82%** |
| v18 (item 3) | 66% -> **52%** | 64% -> **84%** |
| v19 (item 4) | 66% -> **52%** | 66% -> **91%** |

**Two earlier conclusions have to change.**

1. **Item 3's specificity win was overstated.** The real move is 34% -> 52%, not
   27% -> 66%. Still the largest specificity gain in the series, and the prose
   evidence for the mechanism stands — but a good part of the old jump was the
   coach being credited for repeating the move it was handed.
2. **Item 4 did help the move-feedback path after all.** Principle-connection
   went 84% -> 91%, not the 64% -> 66% we called "within noise" and only kept on
   mechanism grounds. Instantiating the guidance theme with a board fact was
   working; the metric could not see it.

**Then a second audit undercut conclusion 2, and it is the more important
result.** The principle-connection metric turned out to say yes to everything, and
has since been deleted — see the measurement philosophy section. So the 84% -> 91%
move is not evidence that item 4 helped; the question was never being measured.
Item 4 is kept on its mechanism (it removes abstract-only guidance and cannot
fabricate) and on fidelity, not on that number. What can be said is narrower and
honest:

- **Item 3 is a specificity lever and it worked.** On the split, honest metric,
  the rate of turns voicing a fact we composed went **27% -> 52%** (v16 -> v19),
  while the rate of turns naming a square we never supplied stayed at **2-5%** —
  so the gain came from the coach voicing supplied facts, not from inventing.
- **Item 4's effect on teaching quality is unmeasured.** Not disproven, unmeasured.
  It is the frontier review's prose critique that would show it, if anything does.

That also means the architecture review's premise cannot be repaired simply by
substituting a corrected number. It reasoned from principle-connection at 64% and
named YAML coverage as the fundamental limit; the truth is that the metric it
reasoned from never measured anything. Its **Change A (compose the missing
30% of best-move clauses)** survives on independent grounds, because
composed-clause coverage is a deterministic count and specificity is genuinely at
52%. The guidance-merge work (Change B) rested on the 64% figure, so it should be
reconsidered from scratch rather than reprioritized.

**The regex is now validated against the move generator, not by eyeball**, since
that is exactly where the first two attempts went wrong. A test generates every
legal move in a position and asserts the destination square is found; a wider
throwaway sweep over 128,411 legal-move SANs from 60 random games measured the
candidates:

| pattern | legal SANs missed |
|---|---|
| `\b[a-h][1-8]\b` (original) | **76.1%** — every piece move |
| `(?<![a-h])(?<![0-9])[a-h][1-8](?![0-9])` (first fix) | **1.1%** — disambiguated moves: `Nbd7`, `Rae1+`, `Rgg1`, `R1e2` |
| `(?<![a-h][1-8])[a-h][1-8]` (shipped) | **0.0%** |

The first fix looked right on hand-picked examples and was still wrong; the forms
it dropped (`Nfg4`, `Rae1+`, `Rgg1`) occur in the coach's real output. The single
rule "not the second half of a coordinate pair" is both simpler and complete, and
adds no false positives over 41k characters of real coach responses. Castling
contributes no square, deliberately and in both directions.

A second test pins that echoing the move back does not count as specific — which
could not have passed before, because `Ra8#` contributed nothing to either side
of the comparison.

## The honest metric split (2026-08-11)

`specificity_rate` conflated two different things, so it could rise for a good
reason or a bad one. It was replaced by the pair below, both computed against the
prompt the coach actually received:

| run | voiced a fact we composed | named a square we never supplied |
|---|---|---|
| v16 | 27% | 2% |
| v17 | 30% | 5% |
| v18 (item 3) | **52%** | 5% |
| v19 (item 4) | **52%** | 2% |

The first column is the architecture working as designed — compose the fact, let
the model voice it — and it is the rate worth watching. The second is where
fabrication would surface; at 2-5% it is low and flat, which is the reassuring
part of the item-3 result: the specificity gain came from voicing supplied facts,
not from the model getting inventive.

Neither says anything about whether the sentence around the square is true (that
is `verify.py`'s job) or worth reading (that is the frontier review's job). They
are screens.

**And the rule that comes out of this whole episode:** do not maximize any of
these. Every one can be moved by padding the output with square names, which
would make the coaching worse while every number improved. A rate that moves is a
prompt to go and read the output, not a result.

The other rule, from the deleted metric: if a measurement cannot fail, delete it.
Keeping it with a warning attached does not work — the number still gets printed,
still gets quoted in a review prompt, and still gets cited months later by someone
who did not read the warning. That is exactly how the 64% figure ended up
anchoring an architecture review.
