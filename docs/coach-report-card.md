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

## Ledger — what the judge flagged, what we did, what happened

Newest last. One row per finding, so the loop is auditable: a review names a
problem, we make one change, we measure, and the row records whether it worked —
including the changes that did not, and the findings that turned out to be about
our own measurement rather than the coach. Detail for each is further down.

| # | Judge flagged | What we changed | Outcome | Verdict |
|---|---|---|---|---|
| 1 | Generic, recycled advice | Removed the always-on "CHESS PRINCIPLES" crib | Score +0.7, fabrication counts flat | kept |
| 2 | Fabricated causal chains ("Bc4 allows Nxd4") | Grounding rule forbidding unverifiable causes | No measurable effect — negative constraints do not work on this model | **reverted** |
| 3 | Same tone for a slight slip and a blunder | Severity tiers from our own eval-drop bands | Violations 13 -> 6 | kept |
| 4 | Verbose for the content delivered | Per-tier word limit + `max_tokens` | Replies shortened as designed | kept |
| 5 | Refutations too vague | State the full refutation line | Move-salad; `illegal_move` 0 -> 5 | **reverted** |
| 6 | (same) | Opponent's *single* first reply + opponent-aware checker | `illegal_move` -> 0 | kept |
| 7 | Leads with principle, not position | Reorder prompt: position before principle | Cost accuracy — placement/piece_type doubled | **reverted** |
| 8 | Wrong captured piece in opponent replies | Compose the captured piece from the board | Corrected a hallucination at zero cost | kept |
| 9 | Best move explained generically | Voice the engine's `best_move_idea` | Necessary but insufficient — the label has only 10 distinct values | kept |
| 10 | Closing maxims are interchangeable | Named principle + "next time you see X" hook | Kept on the judge's direct recommendation | kept |
| 11 | Coach parroted coordinates and invented what the move did | Correct SAN base position + truncate, never emit coordinates | Prompt leaks 27/44 -> 0/44 | kept |
| 12 | Coach misattributed whose move it was | Numbered SAN (`5...Nfg4 6.f4`) | Violations 8 -> 6, `piece_type` -> 0 | kept |
| 13 | Best-move "why" still a category label | Compose a board-derived clause (item 3) | Specificity 34% -> 52% (corrected figures) | kept |
| 14 | Guidance is abstract prose the model echoes | Instantiate each theme with the fact that fired it (item 4) | Cleanest fidelity of the series; teaching effect unmeasured | kept |
| 15 | (our finding) 30% of best moves had no description | Clauses for quiet moves: open file, mobility, castling, extra defender (Change A) | Coverage 70% -> 89% | kept |
| 16 | (our finding) Coach handed an EMPTY engine-lines section on 19/44 turns | Root-caused to a stale reference in the engine; fixed blunder + per-line base in the client | Empty sections 19 -> 0, rendered lines 25 -> 131; fidelity flat | kept |
| 17 | "Catastrophic square-naming failure — 0% novel squares" | Nothing in the coach: this was our own metric handed over without saying which direction was good | Re-judged the identical transcript: became **strength #2**, "the 66% board-fact voicing and 0% invented squares are exactly right" | **was our bug, not the coach's** |
| 18 | Same three lessons all game (counted by hand, twice) | Measured it: `lesson_concentration_rate` (4th design; two earlier ones deleted) | 82% (v17) -> 57% (v20) -> 68% (v21); judge now cites the number and confirms it independently | kept |
| 19 | Closing question recycled; "one of three templates" | Compose the closing lesson from what the move verifiably DOES, instead of letting the model pick | Bogus hooks gone ("fork opportunity" on a move that forks nothing: 3 turns -> 0); no closing repeats more than twice; concentration 68% -> 66% (metric under-reports, see below) | kept |
| 20 | Composed lessons are phase-blind (endgame taught as opening) | Phase-gate the lesson table: endgame rook-behind-passed-pawn, king as attacker, etc. | **Did not land.** Distinct lessons 11 -> 18 and top-3 coverage 57% -> 30% in the prompt, but only 2/18 endgame turns mention a passed pawn and none mention promotion or the king as a fighting piece — the model paraphrases the lesson back into its own vocabulary | kept (free, no fidelity cost) but ineffective |
| 21 | (our finding) The judge itself was wrong on 5 of 5 per-ply factual claims | Switched the default judge to `claude-opus-5` | On the same transcript opus-5 got 2 of 2 right and found two real defects the checker misses | kept |
| 22 | Coach text incoherent at ply 28 ("your opponent plays e3 … your pawn on e3 is undefended") | Name the piece, not the bare square: `"threatens your pawn on e3"` via a new `_describe_target` | v24: ply 28 reads correctly | kept |
| 23 | Our own centrality clause downgraded a more central king move (ply 1002) | Suppress the king-walk clause unless it beats the student's move (`rival_uci`) | Clause gone from the prompt — but the model now fabricates "closer to the center" unprompted | kept, insufficient |
| 24 | "Endgame: most turns, worst pedagogy, and it is inverted" — king safety preached on plies 52, 60, 76, 1000, 1002; a centralized king called "exposed" | `excludes_features` on guidance entries; `principle.exposed_king` excludes `phase:endgame` | The entry was in all five prompts, now in none — replaced by passed-pawn / king-activity / open-file guidance | kept |
| 25 | Ply 36: "capturing the undefended bishop on b4" when `bxc4` took a knight — and the checker said nothing | Widened `_CAPTURE_CLAIM_RE` to allow up to two words (adjectives) between the article and the piece noun | The check now fires on ply 36; "wins a pawn" idiom and "takes control of the bishop's diagonal" still clean | kept |
| 26 | (v25) Same endgame complaint again, because the guidance entry was only one of three sources of "king safety" | Drop the engine's king-safety idea label in endgames (keeping any verified clause), and remove the hardcoded "is my king safe?" example from the PEDAGOGY block | **v26: landed.** King-safety frames on endgame achievement lines 8 -> 0, and the coach's own endgame text 4/18 turns -> **0/18**. Lesson concentration 57% -> **45%** (series best), composed-fact 61% -> 66%, real violations flat at 2, score 4.3 -> 4.5. The judge's endgame complaint changed from "inverted / actively wrong" to "shallowest" | kept |
| 27 | (our finding, while checking v25) Two checker false positives at ply 60 | `Be6` naming a piece that already stands there is no longer read as a move; a capture claim attributed to the opponent is no longer judged against the victim of OUR named move | Both gone; the 2 remaining text-level violations in v25 are real coach errors | kept |
| 28 | (blind audit) Manufacturing fault on moves that were fine — classed **harmful**, not imperfect: 10 of 44 turns, at drops of 0-17cp | New `equal` tier under 25cp that withholds the alternative from the prompt entirely, describing the student's own move instead | All 10 turns now on a no-comparison tier; prompt-side verified, output unmeasured (needs v27) | kept, unmeasured |
| 29 | Harness bookkeeping voiced as a chess reason ("the evaluation spread shows it was a key decision", plies 12/18/24) | Stop passing the engine's `critical_reason` — its only format is "eval spread between best and Nth-best line is Xcp" — while keeping the critical-moment flag | Eval-spread text in the prompt: 20 turns -> 0 | kept, unmeasured |
| 30 | (our finding) The score never discriminated between coach versions | Rebuilt the ask as a per-category rubric with gates, derived externally (rubric v2), and re-judged the **identical** v26 transcript under both asks | Old ask 4.5, new rubric **2/10** — pre-gate weighted 4.3, capped by the fidelity gate on one false claim at ply 36. The two asks agree on quality and disagree on what to do about it | kept |
| 31 | (rubric v2) One false board claim makes everything else worth nothing — "nothing else you do can score above 2/10 while ply 36 is possible" | **next** — wire the existing fidelity check into the send path (regenerate once, then a composed fallback) | — | open |
| 32 | (rubric v2) The prompt orients around the engine's best move, so the model explains why THAT move is good and reverse-engineers a lesson from it | **next** — supply the cause of the student's loss as a first-class composer field and key the takeaway to it | — | open |
| 33 | Misses checkmate at ply 1003; intent attribution the coach cannot know ("aimed to develop your king's bishop"); cue quality near-tautological | **next** | — | open |

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

## Measuring repetition (2026-08-11) — and two designs that failed first

The reviewer complained twice that the coaching says the same thing every move,
and counted it by hand: "the closing question is almost always one of three
templates", with "can I attack an undefended piece?" on roughly half the game. We
had no measurement for it at all, so every discussion of it was anecdote against
anecdote.

Because the reviewer had produced a hand count, there was something to check a
candidate metric *against* — which is how two plausible designs got caught.

**Attempt 1, repeated wording** (`recycled_phrase_rate`, kept). For each turn,
the share of its five-word windows that already appeared in an earlier turn. Reads
21-27% across five runs and its worst-offending turns overlapped the reviewer's
cited plies only **3 of 12**. Kept, because repeated wording is a real and
separate thing and the number is honest about what it is — but it does not measure
the complaint, because the model rewords freely while teaching the same lesson.

**Attempt 2, distinct closing sentences** (deleted). Scored **95-100%** — saturated
and useless. "Next time you see a fork..." and "next time you see your knight on
the back rank..." are different strings and the same template. Deleted rather than
kept with a warning, per the rule the previous metric taught us.

**Attempt 3, the dominant lesson term** (rejected). Whichever single content word
appears in the most closing sentences. Picks "king", which overlaps the reviewer's
cited plies **0 of 12** — because the complaint was not about one lesson, it was
about *three* covering everything.

**Attempt 4, lesson concentration** (shipped). The share of turns whose closing
sentence contains one of the three most common content words across the game.
Directly encodes the reviewer's claim, and reproduces it:

| run | lesson concentration | recycled phrasing |
|---|---|---|
| v17 | 82% | 25% |
| v18 | 80% | 27% |
| v19 | 68% | 23% |
| v20 | **57%** | 21% |
| v21 | 68% | 22% |

It has the properties the deleted metrics lacked. It is not saturated, it moves
across runs, it can fail, and it agrees with an independent count. It also shows
the lever series did reduce repetition (82% -> 57%) and that v21 gave some back.

**On the word list.** This metric strips template scaffolding and generic English
before counting, which is a hand-authored word list — the thing we just deleted a
metric for. The distinction is worth stating plainly: the old list used keywords to
decide whether prose was *good*, which a keyword cannot know. This list is used to
count *how often the same lesson recurs*. Adding a word to it cannot make the
coaching look better, only make the measurement blunter — and unlike the deleted
metric, the output was validated against a count nobody derived from it.

## Re-judging the same transcript with corrected metrics (2026-08-11)

A clean experiment, because the coach's output was byte-identical: only the stats
block the reviewer is handed changed (directions stated, repetition measured).
Anything that moved is attributable to that block. Artifacts in
`output/coach_review_v21_rejudge/`.

**The previous review's weakness #1 became strength #2.**

Before: *"Catastrophic square-naming failure (66% re-use, 0% novel). A chess
teacher who can't say 'your bishop is hanging on c4' is not teaching chess — it's
paraphrasing prompts."* It was the headline finding and the basis of the top
recommendation.

After: *"Fidelity to engine-supplied facts is solid. The 66% board-fact voicing and
0% invented squares are exactly right. The coach isn't hallucinating piece
locations or phantom threats. This is the floor the product needs, and it holds."*

Same coaching, same numbers, opposite conclusion. The whole complaint was a metric
handed over without its sign — and had we acted on it, the change would have been
"let the model name squares we did not give it", the exact opposite of every lever
that has worked.

**The new #1 weakness is the one we just started measuring**, and the reviewer does
not merely repeat our figure — it verifies it from the transcript with its own
counts: "undefended piece" closing on ten turns, king safety on twelve, open file
on eight. First time a metric we built and a reviewer that had no hand in building
it have independently agreed. Score unchanged at 4.5/10, consistent with treating
it as too coarse to move on.

**Its recommended fix, and why we will not implement it literally:** "track which
principle was used in the last N turns and prohibit repetition in the prompt". The
prohibition half is a negative constraint, which is the one lever category that has
never worked on this model (row 2 of the ledger). The tracking half is sound. So
the composed version: derive the closing hook from the move-effect category we
already compute, so variety comes from the data rather than from an instruction.

**Two cautions about the reviewer itself.** It called the coach "Qwen3-8B" when we
run qwen3:14b — its incidental claims need checking. And it is capable of building a
headline recommendation on a misread number, so the stats block we hand it is part
of the experiment, not neutral scaffolding.

## The judge itself was the unreliable part (2026-08-12)

Two changes were measured against the judge's advice — composing the closing lesson
(v22) and phase-gating it (v23) — and while doing so its per-ply factual claims
were checked against the board for the first time. They did not hold up.

**claude-sonnet-4.6, five specific claims, five wrong.** It asserted twice that
ply 12's `dxe3` "recaptures a pawn, not a knight" and called it a fabrication; the
position has a black knight on e3 and the coach was correct. It attributed the
run's `piece_type` violation to that ply; the violation is at ply 60. It said ply
68's "you captured the undefended rook on f4" was wrong because `Kxf4` is a king
move; capturing a rook with the king is exactly what happened. It said ply 18's
"the opponent threatened f4" was invented; a knight on g6 attacks f4. Earlier it
built its entire headline recommendation on misreading a 0% metric as a defect.

**claude-opus-5 on the same transcript: two claims, both correct, both new.**

- Ply 28: the coach wrote *"your opponent plays e3, winning material because your
  pawn on e3 is undefended."* Verified — e3 holds OUR pawn. The coach has the
  opponent moving onto a square our own pawn occupies and calls it our undefended
  pawn in the same sentence. Incoherent, and the fidelity checker recorded nothing.
- Ply 1002 (white Kf2, pawn d5, black Kf7): the student played Ke3 and the coach
  said the alternative Kf3 "takes it one step closer to the center". Both squares
  are equidistant from the centre by the measure our own composer uses, and e3 is
  the more central file — so the coach downgraded a more central move by claiming
  the alternative was more central. **That one implicates our code**: the
  `king_activity` clause compares from-square to to-square, which is locally true
  and comparatively wrong when set against the student's move.

It also identified something sonnet listed as a strength: our own harness
bookkeeping leaking into the coaching as pseudo-explanation — "the evaluation
spread shows it was a key decision", "the best move was also your move" — on five
turns, occupying the slot where a chess reason belongs.

So `claude-opus-5` is now the default judge in both review scripts, at 2.20x
credits and ~3 minutes against sonnet's 1.30x and ~1 minute. That is cheap next to
a wrong finding: sonnet's phantom ply-12 error cost two investigations, and its
misread metric would have sent us to implement the opposite of what works.

**Also fixed while there:** `--judge-model` and `--judge-command` both named a
model and could silently disagree, with the command deciding — so a run could
record opus-5 while actually being judged by sonnet. The command is now derived
from the model unless explicitly given.

**And the standing rule this produces:** the judge's *structural* observations have
been consistently valuable — phase blindness, template closings, repetition counts,
the bridge critique. Its claims about specific plies are leads to verify, not
findings. Every one that has been checked against the board was wrong under
sonnet; opus-5 is better but the habit stays.

## Two per-ply defects, then the endgame inversion (2026-08-13)

The four fixes opus-5's v24 review produced, in the order they were made.

**Ply 28 — a bare square read as a destination.** The prompt said *"the opponent
threatens e3"*. The model read that as the opponent *moving to* e3, and wrote a
sentence where the opponent plays onto a square our own pawn occupies. Fixed by
naming what is actually there: `_describe_target` resolves the square against the
board and produces `"your pawn on e3"`, falling back to `"the f3 square"` when the
square is genuinely empty. v24 confirms ply 28 now reads correctly.

**Ply 1002 — our clause was comparatively wrong.** `_move_effect` now takes the
student's move (`rival_uci`) and drops the king-walk clause unless the
alternative is actually more central than what the student played. The clause is
gone from the prompt. The model then said "closer to the center" anyway, from its
own vocabulary, with nothing supplied — the same failure mode as the phase-gated
lesson table (row 20): **a fact we hand over gets voiced faithfully; a lesson we
hand over gets paraphrased away, and a lesson we withhold gets invented.**

**The endgame inversion — the structural one.** The judge's sharpest phase note
was that the endgame, with the most turns, had the worst pedagogy *and it was
backwards*: plies 52, 60, 1000 and 1002 all hunted for a "safer square" for the
king, and ply 76 called a centralized king "exposed" and recommended retreating
it. In a rook endgame the king is a fighting piece.

The cause was in our own knowledge base, not the model: `principle.exposed_king`
had no phase condition, so it stayed eligible to the last move of the game.
`GuidanceEntry` gained an optional `excludes_features`, checked in three places
that select entries — the feature path, the ECO path, and the empty-selection
fallback — with the guard validating exclusions against the same closed
vocabulary as inclusions. Verified per-ply rather than in aggregate: the entry was
present in the v24 prompt for all five flagged plies and is absent from all five
now, replaced by `passed_pawn_endgame`, `endgame_king_activity` and `open_file`.

Two implementation notes worth keeping. Adding `excludes_features` as a required
field broke 26 tests; last with a `frozenset()` default it broke none. And an
exclusion has to be applied on *every* path that can select an entry — the ECO
path and the fallback would otherwise reintroduce exactly what the feature path
just excluded.

**Ply 36 — the checker had a hole shaped like an adjective.** The coach wrote
*"wins material by capturing the undefended bishop on b4"* when `bxc4` captured a
knight, and `piece_type` recorded nothing. `_CAPTURE_CLAIM_RE` required the piece
noun to follow the article directly, so any adjective hid the claim. It now allows
up to two intervening words. The bound matters in both directions: "undefended" is
a word **our own composer uses constantly** ("attacking their undefended rook on
f4") and the coach echoes it, so the gap was hiding precisely the errors most
likely to occur — while three-or-more words still means the phrase is about
something else, which keeps "takes control of the bishop's diagonal" unflagged.
Both cases are pinned by tests, along with the "wins a pawn" material idiom that
the excluded `win` verb protects.

## v25 — the fix worked and the complaint stayed (2026-08-13)

Score 4.2 -> 4.3, which is noise. The interesting part is that the judge repeated
the endgame complaint almost verbatim, and was right to.

**The exclusion did exactly what it claimed.** The exposed-king guidance was in the
prompt on 16 of 18 endgame plies in v24 and on 0 of 18 in v25, still correctly
present on the middlegame plies 34-50.

**It was one of three sources.** Two more, both ours, were untouched:

1. **The engine's `best_move_idea` label**, rendered as "What the best move
   achieves: king safety — repositioning the king". Present on 14 turns, 8 of them
   endgame — *the same count in v24 and v25*. This is the loudest source and it
   sits in the highest-value line of the prompt.
2. **A hardcoded example in our own PEDAGOGY block**: `ask yourself: is my king
   safe?`, on every turn of every game, endgames included.

So the source that was easy to see was not the source that mattered. The lesson
generalises: when a review complains after a fix, count how many places produce
the thing complained about before concluding the fix failed.

**What we did.** Dropped the king-safety label in endgame positions using the same
phase heuristic the feature extractor uses (`phase_of_board`), and replaced the
PEDAGOGY example. Deliberately **no substitute label** — swapping one category word
for another is precisely what failed when the lesson table was phase-gated (row
20). On 6 of the 8 affected turns the composer already had a verified clause
("moving your king off e5 where it was attacked", "hitting their rook on f4 and
their bishop on g4" — the engine had mislabelled a double attack as king safety),
so the fact survives and only the frame goes. Only plies 1000 and 1002 lose the
whole line, and that is honest: we have nothing verified to say there.

**A dangling reference the test caught.** Three tier instruction blocks tell the
model to *use "What the best move achieves" shown above*. Removing the line left
that pointing at a section no longer in the prompt — an open invitation to invent
what it would have said, which is how "closer to the center" appeared on a turn
where we supplied nothing. The reference is now redirected when the line is
dropped.

**Two checker false positives, found by checking our own new violations.** v25
reported 4 text-level violations against v24's 2. Reading them:

- `illegal_move: Be6` at ply 60. The coach wrote "the pin on Be6 and f7", using
  `Be6` to mean *the bishop on e6*. Our own composer emits that notation ("Re1 pins
  Be6 to Ke7") and the coach echoed it. The board settles the ambiguity: plain SAN
  onto an occupied square is impossible, so when a piece of the named type already
  stands on the named square the token can only be a reference.
- `piece_type: "capture your knight"` at ply 60. The turn names one SAN capture
  (`Rxh7`, taking a pawn) and the checker applied that victim type to every capture
  phrase — including one about what the *opponent* could capture. Opponent-attributed
  capture claims are now skipped, reusing the same attribution helper the illegal-move
  check already had.

After both fixes, the two remaining violations are real: ply 36 names a bishop for a
knight capture, ply 40 puts the king on an empty f2. **And `piece_type` 1 -> 2 was
the checker improving, not the coach degrading** — ply 36 made the same error in v24
and the old regex could not see it.

**One real defect nothing catches.** At ply 60 the coach says "your opponent can
capture your knight on c3". Verified against the board: after the student's `Kf3`,
Black has **no legal captures at all**. A fabricated refutation, and no check exists
for it.

## v26 — the endgame inversion is gone, and why an empty slot is worse than no slot (2026-08-13)

Accept on every criterion written before the run.

| | v25 | v26 |
|---|---|---|
| king-safety frames on endgame achievement lines | 8 | **0** |
| endgame turns where the COACH says king safety | 4 / 18 | **0 / 18** |
| lesson concentration | 57% | **45%** (series best; was 82% at v17) |
| turns voicing a composed board fact | 61% | 66% |
| real text-level violations | 2 | 2 (identical) |
| judge score | 4.3 | 4.5 |

Two of 18 endgame turns lost the achievement line entirely (plies 1000 and 1002),
exactly as predicted — nothing verified was available to say there.

**The finding worth keeping is the output-side zero.** At ply 1002 we suppressed our
centrality clause and the model promptly invented "closer to the center" from its own
vocabulary. Here we removed the king-safety frame and it was **not** replaced by
anything. The difference is not the model, it is the slot: at ply 1002 the
"What the best move achieves:" header was still in the prompt with the clause taken
out of it, so there was a labelled hole demanding a reason. In v26 the whole line
disappears when nothing is verified.

**So: an empty slot is worse than no slot.** A header with nothing under it is an
instruction to fabricate. That refines the earlier rule (row 20 / row 23) — facts get
voiced, abstractions get paraphrased away, and *blanks get filled in*. It also means
the fix only worked because the dangling-reference problem was fixed alongside it:
three tier instruction blocks still said "use 'What the best move achieves' shown
above", and leaving those in place would have recreated the ply-1002 failure.

**The judge's endgame verdict changed character**, which is the independent
confirmation:

- v24: "most turns, worst pedagogy, and it is inverted… calls a centralized king
  'exposed' and recommends retreating it".
- v25: "the worst fit, and actively wrong in principle… frames it as *King safety
  first*".
- v26: "over-represented but shallowest… Plies 64, 70, 74, 78 are all 'move the piece
  off the attacked square' — that is threat avoidance, not endgame technique."

The inversion is gone. What remains is the hole we knowingly left, i.e. the
"endgame facts, not endgame prose" item. "King safety" now appears exactly once in the
whole review, under *No memory across turns* — flagged at plies 6, 16, 26, 34, 40
without ever saying "this is the fourth time". That is the middlegame, where the frame
is correct, so it argues for cross-turn memory rather than against this fix.

**Also worth noting the concentration drop was not the target.** 57% -> 45% came free:
removing a frame that fitted any position removed one of the three lessons everything
was collapsing onto. The metric moved because the cause moved, which is the first time
that has happened rather than the metric being argued with.

## Rebuilding the ask: same transcript, two rubrics (2026-08-14)

The coach's output and the judge's *ask* are two independent variables and we had
been changing them together. `scripts/eval_coach_rejudge.py` now re-judges a saved
transcript with no coach, no engine and no tunnel, so the ask can be isolated.

Run on the **identical** v26 transcript:

| | old ask (v1) | rubric v2 |
|---|---|---|
| headline | 4.5/10 | **2/10** |
| pre-gate weighted | — | 4.3/10 |
| fidelity | — | 4/10 — **gate fired** |
| diagnosis | — | 4/10 |
| transfer handle | — | 4/10 |
| executability | — | 6/10 |
| load discipline | — | 5/10 |
| stance | — | 6/10 |
| stream behaviour | — | 3/10 |

**The two asks agree on quality and disagree on what to do about it.** 4.3 pre-gate
against 4.5 is the same judgement. The gate is the new information: one false claim
about the board caps everything, because the student cannot detect it.

It fired on ply 36 — `bxc4` described as capturing "the undefended bishop on b4"
when it captured a knight. **Independently confirmed**: our own deterministic
checker flags that exact ply. The judge added a detail we had missed — b4 was still
occupied by that bishop twelve plies later (attacked at 44 and 46, hit by a3 at 48,
captured at 50), so the student would have carried a false board state for a quarter
of the game.

**The recommendation flipped.** Under the old ask, twice, it was cross-turn memory.
Under the rubric it is: verify claims about named pieces and squares *before
sending*, regenerate once, fall back to a composed sentence — noting that we already
run these checks and merely report them to a scoreboard. Cross-turn memory dropped
to being the Stream Behaviour blocker, and was split by cost: a silence rule for
quiet moves and an n-gram duplicate block are SMALL, the recurring-error tally is
MEDIUM.

**It reached the audit's Finding 2 independently**, from the transcript alone:

> The prompt orients around the engine's best move, so the model explains why that
> move is good and then reverse-engineers a lesson from it — which is why the
> student's hanging knight at ply 20 produced a lesson about attacking b4.

Its fix is concrete and cheaper than expected: give the composer the *cause of the
student's loss* as a first-class field (what was left undefended, which defender
moved away, what the moved piece had been doing) and require the takeaway to come
from that field, never from the best move's virtues. MEDIUM, and it observes the
engine data is largely present already.

**It also listed both fixes we shipped the same morning** under "what to remove" —
eval-machinery talk, and inventing a difference on 0cp moves — from a transcript
that predates them. Two independent routes to the same two changes.

**A correction to an earlier claim.** The flat 3.5-4.5 series was described here as
mostly judge re-anchoring noise. That is wrong: the old ask reproduced **4.5
exactly** on a transcript it had already scored 4.5. It is stable within a
transcript; what it fails to do is discriminate *between* coach versions. The
instrument was insensitive, not noisy — same conclusion, different diagnosis.

Raw reviews: `docs/audit/rejudge-v26-{v1,v2}.md`.
