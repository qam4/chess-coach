# Backlog

Things we discussed but deliberately deferred. The rule: if we talk
about doing something and don't do it now, it lands here with enough
context to pick up later. Distinct from:

- **IDEAS.md** — open-ended feature ideas / research directions.
- **BUGS.md** — known defects.
- **`.kiro/specs/*/tasks.md`** — committed, scoped work for an active feature.

This file is for "real, agreed, not-yet-scheduled" follow-ups.

## Coaching-eval harness

- **Eval sensitivity & validity — THE next investment (decided 2026-06-18).**
  After three guidance A/Bs (more entries, tighter prompt, sharper cap-1
  selection) every teaching-quality result came back *within judge noise*:
  the absolute 0–1 rubric score wobbles ~±0.14 when the judge re-scores the
  same text, which swamps the effect we are trying to detect (gemma on-vs-off
  was +0.141 vs a ±0.143 band). We could not tell whether a change helped.
  Two distinct problems, and fixing only the first would just measure the
  wrong thing more precisely:

  - **(A) Sensitivity** — the judge is too noisy at n=3 × 9 positions to
    resolve small teaching deltas.
  - **(B) Validity** — the benchmark only tests the *position-explanation*
    path (Step 3 of the play loop: “explain this position”). That is the
    “position analyser” mode the product explicitly does NOT want to be
    (see VISION.md). It does not test the *move-feedback* path (Step 1:
    given the move the student just played, is the feedback good teaching?),
    which is the reactive, student-facing moment that matters most.

  **Decision / direction (in priority order):**

  1. **Switch change-detection from absolute scoring to PAIRWISE judging.**
     Biggest sensitivity win. Instead of scoring each response 0–1 and
     differencing two jittery numbers, show the judge BOTH responses for the
     same position (randomized, recorded order) and ask *which teaches
     better*. A judge re-anchoring “what does 0.4 mean?” every time is the
     dominant noise source; a relative A-vs-B preference removes it. Output
     becomes a **win-rate** (“on beats off 7/9”) with a real significance
     test (binomial / sign test) — directly answering “did this change
     (prompt / model / guidance) have the impact we want?”, which absolute
     diffs could not. This is the standard tool for preference/arena evals.
     **The pairwise library already exists and is tested** (`pairwise_compare`,
     randomized+recorded order, Property 6); it is only missing a CLI mode
     (tasks.md 6.3 `[~]`). So this is high value, low cost. Keep absolute
     rubric scoring as the secondary factual/safety readout (the objective
     Layer 1 is unaffected and remains the safety backstop).
  2. **Fix validity: evaluate the move-feedback path, with a teaching
     rubric.** Add benchmark scenarios of the form `(position, move the
     student just played)` with ground truth (sound/inaccuracy/blunder +
     the principle it touches), so we measure the Step-1 coaching moment,
     not just position analysis. The move-feedback prompt is structurally
     about *the student’s move*, so it resists “position analyser” answers.
     Lean the rubric further toward teaching: reward naming ONE transferable
     idea + ONE concrete action, penalize feature-dumping.
  3. **Grow + curate the benchmark** to 20–40 positions across phases/levels,
     biased toward cases where a teaching principle clearly applies (so the
     signal is not diluted by positions where guidance cannot matter). The
     annotation guard (`eval_check_annotations.py`) makes authoring safe.
  4. **Calibrate the (pairwise) judge** against a few of the product owner’s
     own A-vs-B picks (Layer 3 agreement) before trusting it at scale.

  **Honest ceiling (do not lose sight of):** a frontier judge rating a
  one-shot response is a *proxy*. The true measure of teaching is **student
  improvement over time** — a much bigger, longitudinal build with real
  users. Pairwise + calibration keeps the proxy trustworthy; it does not
  replace outcome measurement. Ties to the “Who calibrates teaching
  quality?” and “Structured Learning Path” items.

  **First concrete step:** wire `--pairwise` into `eval_run.py`, then re-run
  the gemma guidance on-vs-off as a pairwise A/B. If guidance truly helps
  teaching, “on” should win materially more than 50% of head-to-heads —
  visible where the absolute-score diff was not.

  **First pairwise result — DONE (2026-06-18): confirms guidance does NOT
  help gemma, and validates the instrument.** Ran `eval_pairwise.py` over the
  saved gemma 3x3 off/on runs (27 randomized head-to-heads, sonnet judge,
  no tunnel — judge-only). Result: **off 14, on 11, 2 ties; on win-rate 44%;
  two-sided sign test p=0.69 — NOT significant.** Head-to-head, ON does not
  beat OFF (off is marginally ahead, within chance). This is the decisive
  read the absolute score couldn't give: the earlier +0.141 absolute “gain”
  was judge noise, not real teaching improvement. The pairwise instrument
  earned its keep — a clear yes/no where differencing noisy 0–1 scores was a
  shrug.

  *Independence caveat:* gemma generation is deterministic at temp 0, so the
  27 comparisons are really ~9 unique text-pairs each re-judged ~3x with
  randomized slot order — they sample judge variance, not response variance,
  so effective n is closer to 9. The sign-test p slightly overstates power;
  but the signal is so flat (44%) that the conclusion (no benefit) is robust
  either way. For models with non-deterministic generation (qwen) the 3 runs
  would add genuine response diversity too.

  **Implication:** the pedagogy layer as built does not improve teaching for
  gemma even by the low-noise measure. The lever is now CONTENT/VALIDITY, not
  more measurement: (a) evaluate the move-feedback path (step 1), not just
  position explanation; (b) rethink what the guidance entries actually add.
  The instrument is ready to gate any such change with a real win-rate.

  **Pairwise qwen3:14b off vs on — DONE (2026-06-18): also no teaching
  benefit; completes the picture.** Same 3x3 saved runs (27 head-to-heads,
  sonnet judge). Result: **off 12, on 14, 1 tie; on win-rate 54%; p=0.85 —
  NOT significant.** qwen's ON wins marginally more (directionally matching
  the absolute-score hint that guidance helped qwen), but at 54% it is a coin
  flip. Crucially qwen generation is non-deterministic, so these 27 are truer
  independent samples than gemma's ~9 — a stronger 'no effect' read. Both
  models side by side: gemma 44% on (p=0.69, off-leaning), qwen 54% on
  (p=0.85, on-leaning) — within chance in OPPOSITE directions, the signature
  of no real effect. And qwen's guidance also carried a factual cost
  (0.28→0.23), so for qwen the layer is net-negative.

  **DECISIVE CONCLUSION (both models, low-noise measure):** the pedagogy
  layer as currently built produces NO detectable teaching improvement — the
  earlier absolute-score 'gains' (gemma +0.141, qwen +0.097) were judge
  noise. This is no longer 'unproven within noise'; pairwise actively shows
  no benefit. Redirect effort accordingly: (1) measure the move-feedback path
  (step 1), the coaching moment that matters most and which we have NOT tested;
  (2) rethink what guidance entries add (the current 'name a theme' framing
  may simply not move a one-shot position explanation); (3) the layer is still
  SAFE (cap-1: 0 hallucination/illegal, factual up) so it can ship as a
  no-harm default while the teaching question moves to the move-feedback path.

  **Move-feedback path MEASURED (2026-06-23): also no benefit for gemma,
  once the measurement was de-confounded.** Built the move-feedback
  benchmark (`data/eval/move_feedback.yaml`, now 20 (position, student-move)
  situations, engine-graded, mistake-biased) and a pairwise A/B harness
  (`scripts/eval_move_feedback_pairwise.py`) with repeated judging
  (`--judge-repeats N`, majority-voted per situation to denoise the judge;
  generation is deterministic so this doesn't inflate n). First gemma run
  (5 votes/pair) read guidance ON 11-6 (65%, p=0.33) — but reading the
  judge's per-situation rationales showed most verdicts were decided by one
  response **misidentifying which piece moved** from the raw UCI coordinates
  in the prompt (e.g. reading `e1g1` as a bishop move), NOT by teaching
  quality. That was a real prompt bug: moves were fed as UCI. Fixed by
  rendering moves in SAN (named piece) in the rich prompts (commit on
  prompts.py; `_uci_to_san`/`_uci_line_to_san`). Re-run after the fix:
  **8-8 tie (50%, p=1.0)**, and crucially **zero piece-misID complaints in
  any of the 16 judge rationales** — the confound was gone and the judge
  compared actual teaching. So the 11-6 was largely the artifact; the clean
  result is **no detectable teaching benefit for gemma on the move-feedback
  path either**. Mechanism visible in the votes: guidance ON adds a named
  principle (sometimes helps) but also adds filler (judge preferred the more
  concise OFF on clear blunders) — a wash. **Both coaching paths, cleanly
  measured, now agree: the pedagogy layer as built does not improve teaching
  for gemma.** The remaining lever is CONTENT (what the guidance entries say)
  or MODEL CAPABILITY (qwen3:14b showed a borderline gain on position
  explanation — worth a move-feedback run), not more measurement. Side
  findings banked: the SAN fix is a genuine coaching-quality win for real
  users; the kiro-cli judge intermittently returns malformed JSON (raw
  newline / trailing prose) — hardened `_extract_json_object` (brace-matched,
  string-aware) + `json.loads(strict=False)` so situations stop being
  dropped (was losing ~3-4 of 20 per run).

  **Capability gradient — FIRST SIGNIFICANT WIN (2026-06-23).** With the
  de-confounded measurement (SAN moves, 20 situations, 5-vote majority,
  hardened judge parsing => 0 dropped), ran the move-feedback A/B on three
  models:
  | model | type | result | p | verdict |
  |---|---|---|---|---|
  | gemma4:12b-it-qat | non-reasoning | 8-8 (50%) | 1.00 | no benefit |
  | qwen3:8b | reasoning | 14-6 (70%) | 0.115 | leans positive, ns |
  | **qwen3:14b** | reasoning | **15-5 (75%)** | **0.041** | **significant** |

  A clean, coherent gradient: guidance does nothing for the non-reasoning
  model, helps the small reasoning model (promising, just short of
  significance), and **significantly helps the larger reasoning model** —
  the FIRST statistically significant teaching benefit for the pedagogy
  layer anywhere. qwen3:14b judge rationales confirm it's real teaching
  (ON wins by naming the concrete principle / actual move / tactical
  punishment), not the old piece-misID artifact. **Conclusion: the pedagogy
  layer is validated for a model strong enough to use it.** Reframes the
  default-model choice — gemma was attractive on speed but can't use the
  guidance; a reasoning model (qwen3:14b, maybe 8b) unlocks the teaching
  benefit. Caveats: single runs; qwen3:14b p=0.041 is solid-not-bulletproof
  and qwen generation is non-deterministic, so a replication would firm it
  up; 8b's 70% would likely cross into significance with a little more data.
  Still a frontier-judge proxy, not measured student improvement (true
  north). Results: output/eval_mf_pairwise_qwen14/pairwise.json; qwen3:8b in
  output/mf_qwen8_monitor/output.log (its pairwise.json write hit a full
  disk — data intact in the log). Next levers: replicate qwen3:14b (≥3x);
  test capability threshold; revisit whether guidance content can help a
  non-reasoning model; consider the default coaching model bump.

- **Model-capability profiler — SHIPPED (lean).** The manual model-vetting
  this session (gemma can't use guidance, qwen3:14b can, models misread UCI,
  some hallucinate) is now an automated tool:
  `.kiro/specs/model-capability-profiler/` + `scripts/profile_model.py` +
  pure core `src/chess_coach/eval/profile.py` (see
  [`docs/model-profiler.md`](docs/model-profiler.md)). Point it at a model; it
  runs cheapest-first dimensions (reachability → factual → guidance uptake →
  latency) reusing the existing eval harness, prints per-dimension facts, and
  recommends a config block (`coaching.template_only`, `coaching.guidance`) —
  advisory only, never auto-applied. Mirrors FITT's `capability_profile.py`
  design (facts-not-verdicts, capability/cost separate, operator-in-the-loop,
  dimensions-as-a-list) but deliberately drops the heavier machinery.
  **Deferred (append-only when missed):** stored baselines + diffing on model
  swap (the JSON output is written to seed it); a declared-facts catalog
  dimension; an instruction-following dimension; a `chess-coach profile` CLI
  wrapper. **Related cross-project:** the capability-profile concept overlaps
  FITT's (and the "shared llm-access library" item below) — a future shared
  component if the projects converge.

- **Knobs wired into the live Coach + durable scorecard — DONE
  (2026-06-19).** Closed the last mile of the profile→config→live-app loop.
  The profiler used to recommend config knobs (`coaching.template_only`,
  `coaching.guidance`) that did not exist in the live app, and guidance was
  never wired into the runtime `Coach`. Now: `config.yaml` /
  `config.example.yaml` have a `coaching:` block with `guidance` (default
  off), `guidance_max` (3), `template_only` (false). `Coach.__init__` honors
  them — loads a guarded `KnowledgeResource` only when guidance is on,
  `_select_guidance()` injects a named principle into the rich
  position-coaching and move-evaluation prompts, and `template_only` skips the
  LLM in favour of deterministic templates. `cli.py` (serve + explain) passes
  the knobs through from config. So profiling a model now produces a config
  block you can paste in and the live app actually obeys it — no code changes
  per model. The validated findings are made durable in
  [`docs/model-scorecard.md`](docs/model-scorecard.md) (the raw
  `output/profile_*.json` are gitignored/local-only): hermes3:8b
  (template_only), gemma4:12b (grounded but no guidance benefit), qwen3:8b
  (guidance borderline), qwen3:14b (guidance significant 80% p=0.012 →
  guidance on, template_only on for raw facts). **Deferred (append-only when
  missed):** `play_move`'s two rich-prompt call sites (user-move feedback +
  engine-move explanation) are not yet guidance-wired (only `explain` +
  `evaluate_move` are); and path-scoped recommendations (template_only for the
  explanation path vs guidance for the move-feedback path can pull in
  different directions for the same model — qwen3:14b is the live example).

- **`rubric.v2` — shipped (leniency defects fixed); teaching-bridge
  grounding still open.** `data/eval/rubric.v2.yaml` now exists: it adds
  the `teaches_principle` bridge criterion, ties `actionable` to the key
  idea, and adds **gated scoring** (`grounded` ×0.3, `key_idea` ×0.5) so
  fluent-but-ungrounded or position-blind filler can't score well. The
  in-session validation that motivated it (hermes3:8b, 3 positions) was
  re-scored under v2 and the three defects are fixed: `italian`
  0.75→0.15, `after_1f6` 0.62→0.20, `kr_vs_k` 0.25→0.03; Layer-2 mean
  0.54→0.13, now tracking the Layer-1 factual mean (0.17).

  **Still open:** the `teaches_principle` criterion is currently judged
  on the frontier model's own chess sense. To keep the "what to teach"
  half *grounded* (not just trusting the judge's chess), it needs the
  pedagogy/curriculum layer below feeding the judge a standard. Also
  pending: a true frontier judge endpoint (the validation used Kiro
  in-session, which is Layer-3 calibration, not automatable Layer 2 —
  see judging-endpoint item) and a wider re-validation once v2 is
  judged at scale.

- **Pedagogy / curriculum layer — SHIPPED.** Implemented as the
  `pedagogy-layer` spec (`.kiro/specs/pedagogy-layer/`, see
  [`docs/pedagogy.md`](docs/pedagogy.md)). A curated local
  `data/pedagogy/knowledge.yaml` (principles/patterns/plans keyed to
  engine Position_Features + ECO, with citations), a pure `Selector`, an
  annotation guard (schema/refs/legality + engine-soundness, no LLM), and
  injection into BOTH the coach prompt and the judge's
  `teaches_principle` standard via one shared selection. Wired into the
  eval harness behind `eval_run.py --guidance on/off` for the A/B.
  **Remaining:** grow the resource beyond the seed (breadth across the
  theme families / openings), run the live `--guidance on` vs `off` A/B
  to quantify the teaching-quality delta, and (later arc) progress
  tracking + level-adaptive teaching that build on it. Connects to
  IDEAS.md "Structured Learning Path".

  **First live A/B (baseline to beat) — 2026-06-15, hermes3:8b, 9
  positions, claude-sonnet-4.6 judge, rubric.v2:**
  | metric | off | on |
  |---|---|---|
  | factual (L1) | 0.17 | 0.22 |
  | coverage | 0.26 | 0.35 |
  | illegal moves | 4 | 6 |
  | teaching quality (L2) | 0.09 | 0.07 |

  Read: non-regression holds (L1 factual + coverage *rose* with guidance,
  so Req 5.2 is satisfied), but teaching quality was flat/slightly down
  (−0.02, within noise) — on the 13-entry seed the injected guidance
  doesn't yet improve judged teaching. Notable side effect: illegal-move
  suggestions rose 4→6, i.e. prompting a weak 8B model to *apply* a
  principle makes it propose more concrete-but-unsound moves (the
  engine/illegal-move check is what catches this). Conclusion: the A/B
  instrument works end-to-end; the **content (seed), not the plumbing,
  is the lever** — growing the resource must beat the −0.02 baseline.

  **Batch-2 result (2026-06-15) — adding entries did NOT help.** After
  adding 6 entries for the uncovered features (phase:middlegame,
  phase:endgame, hanging_piece_opponent, exposed_king, open_file,
  threat_present → 19 entries), the on-run got *worse*, not better:
  L1 factual 0.22→0.18, coverage 0.35→0.20, teaching quality 0.07→0.06
  (vs off 0.17 / 0.09). Likely cause: with cap 3 and a bigger pool, the
  weak 8B model received more *abstract* guidance ("make a plan", "answer
  the threat") in place of concrete keyed facts, wrote shorter, and
  covered fewer engine facts. **"More entries" is the wrong lever.**

  **Methodology — the experiment is underpowered (do this before more
  content work):** single runs × 9 positions × one weak model is within
  judge noise; we cannot conclude the layer helps or hurts. To get a real
  signal: (1) repeat runs (≥3× off/on) to separate signal from noise;
  (2) a **bigger sample of models under test** — not just hermes3:8b but
  qwen3:14b and ideally several across a capability range, since guidance
  may only help models strong enough to *use* it (an 8B may be too weak
  to benefit, making the layer's value invisible at that size); (3)
  sharpen selection (cap 1–2, most-specific-first) rather than expand;
  (4) a larger benchmark. The pedagogy layer's value is unproven until
  measured across models with noise controlled.

  **Repeat-run instrument — BUILT (2026-06-16).** The "separate signal
  from noise" step above now has tooling: `scripts/eval_aggregate.py`
  (logic in `src/chess_coach/eval/aggregate.py`, fully unit-tested) rolls
  N repeated `eval_run.py` result dirs into per-metric `mean ± std`, and
  in `--off … --on …` mode reports each metric's delta against a **noise
  band** (combined sample std), labelling it `improves` / `regresses` /
  `within noise` — and honestly `need >=2 runs/group` when under-powered.
  Run the benchmark ≥3× per condition into separate `--out` dirs, then
  aggregate. The single-run gemma A/B fed through it confirms it refuses
  to call the +0.198 quality delta significant off one run each (correct).
  **Noise-controlled gemma A/B — DONE (2026-06-16), and it deflates the
  single-run claim.** Ran 3× off + 3× on for gemma4:12b-it-qat (rubric.v2,
  9 positions, kiro-cli/claude-sonnet-4.6 judge, temp 0.0 so generation is
  deterministic — repeats isolate *judge* noise), then aggregated:
  | metric | off (mean) | on (mean) | delta | noise band | verdict |
  |---|---|---|---|---|---|
  | factual (L1) | 0.296 | 0.333 | +0.037 | 0.000 | deterministic ↑ |
  | coverage | 0.296 | 0.333 | +0.037 | 0.000 | deterministic ↑ |
  | hallucinations | 0 | 0 | 0 | — | none |
  | illegal moves | 0 | 0 | 0 | — | none |
  | teaching quality (L2) | **0.276** | **0.417** | **+0.141** | **0.143** | **within noise** |

  Per-run quality: off = {0.26, 0.32, 0.25}; on = {0.43, 0.55, **0.27**}.
  The judge scored the *identical* ON coaching texts anywhere from 0.27 to
  0.55 — an on-condition std of ~0.14, as large as the effect itself. So
  the headline teaching gain (+0.141) sits **within the combined judge
  noise band (±0.143)**: on this data we **cannot** claim the pedagogy
  layer improves judged teaching for gemma. The earlier single-run
  +0.198 (0.26→0.45) was partly judge luck — exactly the over-claim the
  repeat-run instrument was built to catch. (Even using the more lenient
  standard-error-of-the-mean, delta/SE ≈ 1.6 — suggestive, not
  significant at n=3.)

  What *does* hold up: **factual non-regression is real and
  deterministic** — guidance reproducibly nudges factual/coverage +0.037
  with zero variance, 0 hallucinations, 0 illegal moves every run (Req 5.2
  satisfied robustly for gemma). So the layer is *safe* here; its
  *teaching benefit* is unproven against judge noise.

  Implications / next: (a) the judge is the dominant noise source — to get
  a real teaching signal, shrink it (more repeats to tighten the SEM, a
  multi-judge panel averaged, or a larger benchmark so each mean rests on
  more positions); (b) consider reporting SEM / a proper significance
  measure in `eval_aggregate.py`, not just the conservative per-run-spread
  band; (c) re-run the same protocol for qwen3:14b (whose single-run
  +0.17 came *with* a factual regression) to see if its delta also
  collapses into noise.

  **Noise-controlled qwen3:14b A/B — DONE (2026-06-17): the trade-off is
  REAL (opposite shape from gemma).** Full 3× off + 3× on (rubric.v2, 9
  positions, kiro-cli/sonnet-4.6 judge). Note qwen is a *thinking* model
  and its generation is **not** deterministic even at temp 0 (factual
  varied 0.22–0.24 across on-runs), so these repeats capture generation +
  judge noise combined — more realistic than gemma's judge-only noise.
  | metric | off | on | delta | t | df | significance |
  |---|---|---|---|---|---|---|
  | teaching quality (L2) | 0.120 | 0.217 | +0.097 | 2.04 | 2.0 | suggestive |
  | factual (L1) | 0.284 | 0.233 | −0.051 | −3.69 | 2.9 | suggestive |
  | coverage | 0.284 | 0.272 | −0.012 | −0.89 | 2.9 | ns |
  | hallucinations | 0.0 | 1.33 | +1.33 | 2.00 | 2.0 | suggestive |
  | illegal moves | 0.33 | 1.67 | +1.33 | 2.83 | 4.0 | **significant** |

  Per-run quality: off = {0.13, 0.12, 0.12}; on = {0.13, 0.22, 0.29}.
  Unlike gemma (teaching gain washed out by noise, NO factual cost), qwen
  shows a directional **trade-off**: guidance lifts teaching quality
  (+0.097) but costs factual accuracy (−0.051) and adds hallucinations /
  illegal moves. **Honest significance (df-aware Welch t, two-sided 95%):**
  at n=3 the critical t is ~4.30 (df≈2–3), so the *only* result that
  clears the bar is the **illegal-move rise** (t=2.83, df=4, t*=2.78,
  significant). Teaching gain, factual regression, and hallucination rise
  are all **suggestive** — directionally consistent and matching the
  single-run finding, but n=3 cannot certify them at 95%. So the read is:
  qwen *probably* trades factual accuracy for teaching (and *definitely*
  proposes more illegal moves), but only more repeats can promote the
  trade-off from "suggestive" to "significant". Req 5.2 (factual
  non-regression) is at best in question for qwen, not cleanly passed.

  **Instrument now df-aware (2026-06-17) — caveat resolved.**
  `eval_aggregate.py` uses a Welch t-test with a two-sided 95% critical-t
  lookup by Welch–Satterthwaite df (table df 1–20, 1.96 beyond), replacing
  the old flat `|t|>=2` rule that over-called small-n results. The labels
  above are the corrected, df-aware verdicts (an earlier draft of this
  note used the flat rule and wrongly marked factual/quality/hallucinations
  "significant"). Remaining limitation is just sample size: at n=3 the bar
  is high by design, so **more repeats** (or a less-noisy judge) are what
  turn a real effect significant.

  **Cross-model synthesis (3 models, noise-controlled where measured):**
  no model yet shows a *clean* significant teaching win with no factual
  cost. hermes3:8b — guidance flat/negative (too weak to use it).
  gemma4:12b-it-qat — teaching gain within judge noise (unproven) but
  factual non-regression holds (safe). qwen3:14b — teaching gain
  (borderline) but a real factual/safety regression (benefit at a cost).

  **Tightening the guidance intro text — TRIED, BACKFIRED (2026-06-17).**
  Hypothesis: adding an anti-fabrication clause to the injected coach
  block ("apply a theme only if the analysis shows it; never invent a
  move/tactic to fit a theme; else teach the idea in general terms")
  would cut qwen's factual regression while keeping the teaching gain.
  Tested with a fresh qwen3:14b 3× ON re-run (tightened prompt) against
  the unchanged OFF baseline and the original ON runs. It made *everything
  worse*: vs the original guidance, factual 0.233→0.148 (t=−13.7, sig),
  coverage 0.272→0.148 (sig), teaching quality **0.217→0.108 (halved**,
  t=−2.3), word count 141→133 (t=−47.6, sig — the model hedged and
  disengaged); hallucinations only marginally down (1.33→1.0, ns) and
  illegal moves slightly up. The three runs were tightly consistent
  (factual 0.15/0.15/0.15), so it's a real effect, not noise. **Conclusion:
  more grounding *instructions* are the wrong lever — piling caution onto
  the prompt makes a capable model write shorter, more hedged, LESS
  grounded coaching, not more. Reverted (commit reverts
  `090542d`).** Better next levers to try (validate live before merging):
  sharpen *selection* (cap 1–2, most-specific-first) so less guidance text
  competes with the engine facts; improve the *content* grounding of
  individual entries' `how_to_apply` (concrete-but-conditional phrasing)
  rather than a blanket prompt warning; or accept that guidance is a
  teaching-vs-factual trade-off and gate it by model capability. And the
  judge remains the dominant noise source — shrink it (more repeats /
  multi-judge) before chasing small prompt deltas.

  **Sharpening selection (cap 1) — TRIED, no teaching gain (2026-06-18).**
  The other lever from the prompt-tightening note: fewer, most-specific
  entries. Ran gemma4:12b-it-qat 3× ON at `--guidance-max 1` vs the OFF
  baseline and the cap-3 ON runs (rubric.v2, 9 positions, sonnet judge):
  | metric | OFF | cap-1 ON | cap-3 ON |
  |---|---|---|---|
  | factual (L1) | 0.296 | **0.352** | 0.333 |
  | teaching quality (L2) | 0.276 | 0.250 | **0.417** |
  | hallucinations / illegal | 0/0 | 0/0 | 0/0 |

  cap-1 vs OFF: factual *up* +0.056 (deterministic), teaching −0.027 (ns) —
  flat. cap-1 vs cap-3: factual ~tied, teaching −0.168 (t=2.03, suggestive)
  — cap-1 teaches *less* than cap-3. **Read: cap-1 is the SAFEST setting
  (best factual of all conditions, zero hallucinations/illegal) but buys NO
  teaching gain — quality sits at baseline.** The (noisy) teaching signal
  lives in the broader cap-3 selection, not cap-1; sharpening trades
  teaching away for safety — the mirror image of the prompt-tightening
  result.

  **Overall conclusion after both levers (2026-06-18).** Neither "less
  guidance via tighter prompt" (backfired) nor "less guidance via cap-1
  selection" (flat teaching) improves the teaching axis. Where a teaching
  gain appears (gemma cap-3, qwen cap-3) it is within judge noise or comes
  with a factual cost. The blocker is NOT the selection cap or the prompt
  wording — it is that **the teaching effect is small and the judge is too
  noisy at n=3 × 9 positions to resolve it.** Stop tuning knobs; the
  high-value next steps are (a) a **less-noisy judge** (multi-judge panel
  and/or more repeats to shrink the SEM) and (b) a **bigger benchmark**
  (20–40 positions) so each mean rests on more signal. Until then the
  honest status of the pedagogy layer is: *safe* (no factual/illegal cost
  at cap 1, and cap-1 even nudges factual up) but its *teaching benefit is
  unproven*.

  (1) Note "most-specific-first" selection is already implemented in the
  `Selector` (plan > pattern > principle, relevance desc), and the cap is
  a runtime flag (`eval_run.py --guidance-max 1|2`), so the "sharpen
  selection" lever needs no code — just runs at cap 1–2.

  **qwen3:14b A/B (2026-06-15) — FIRST POSITIVE SIGNAL (capability
  matters).** Same setup, model under test = qwen3:14b:
  | metric | off | on |
  |---|---|---|
  | factual (L1) | 0.30 | 0.24 |
  | coverage | 0.30 | 0.28 |
  | hallucinations | 0 | 2 |
  | teaching quality (L2) | 0.14 | **0.31** |
  | pass rate | 0% | 11% |

  Teaching quality **more than doubled** (0.14→0.31, +0.17; two positions
  hit 1.00 / 0.90) — a swing big enough to likely be real signal. Cross
  model: guidance was flat/negative for hermes3:8b (0.09→0.07) but
  substantially helped qwen3:14b (0.14→0.31), supporting the hypothesis
  that **guidance only helps a model strong enough to use it** (an 8B is
  too weak). Counterweight: it also made qwen3:14b a worse fact-checker —
  factual 0.30→0.24, hallucinations 0→2 — so Req 5.2 (factual
  non-regression) did NOT hold; teaching more led it to assert more, some
  wrong. Real trade-off, still single-run / 9-position / judge-noise.
  Open challenge: find a *low-budget* model that benefits (qwen3:14b works,
  an 8B does not — trying gemma3:12b next). Next: more models across the
  capability range, repeat runs, and address the factual regression
  (tighten grounding in the guidance text or the coach prompt).

  **gemma4:12b-it-qat A/B (2026-06-16) — BEST RESULT, teaching gain with
  NO factual cost.** Same setup (19-entry resource, 9 positions,
  claude-sonnet-4.6 judge, rubric.v2), model under test =
  gemma4:12b-it-qat (a quantized 12B):
  | metric | off | on |
  |---|---|---|
  | factual (L1) | 0.30 | **0.33** |
  | coverage | 0.30 | **0.33** |
  | hallucinations | 0 | 0 |
  | illegal moves | 0 | 0 |
  | teaching quality (L2) | 0.26 | **0.45** |
  | pass rate | 0% | 11% |

  Teaching quality rose **+0.19 (0.26→0.45)** — the biggest gain of any
  model — and unlike qwen3:14b it came with **no factual regression**:
  factual *rose* 0.30→0.33, coverage rose 0.30→0.33, and **0
  hallucinations / 0 illegal moves in both passes**. So Req 5.2 (factual
  non-regression) holds here. This is the standout "low-budget model that
  benefits cleanly" candidate — quantized 12B, ~7s latency, cheapest of
  the winners. Cross-model picture now: guidance is flat/negative for the
  8B (hermes3:8b 0.09→0.07), helps qwen3:14b but with a factual cost
  (0.14→0.31, hall 0→2), and helps gemma4:12b-it-qat the most with NO
  cost (0.26→0.45, hall 0). Capability-dependence confirmed across three
  models; gemma is the cleanest. Still single-run / 9-position /
  judge-noise — repeat runs are the next rigor step. Candidate for the
  default coaching model (config bump pending).

- **Who calibrates teaching quality?** Layer 3 assumes a human who can
  rate coaching. The product owner is the *student*, not a chess expert,
  so they can't be that human for the teaching axis. Calibration needs
  chess authority (strong player / instructional canon / frontier model
  as proxy). True-north validation is **student outcomes** (does the
  player improve), not expert prose-rating — a much bigger build, ties
  to progress tracking.

- **Pairwise `--pairwise` CLI flag — PROMOTED to the next step** (see
  “Eval sensitivity & validity” above). The pairwise judging library
  (`pairwise_compare`, randomized+recorded order, Property 6) is built
  and tested, but not exposed as an `eval_run.py` CLI mode. No longer
  “optional”: it is the chosen fix for change-detection noise — wire it,
  then re-run the gemma guidance A/B as a pairwise win-rate.
  (Tracked as tasks.md 6.3 `[~]`.)

- **Hallucination detector misses relational falsehoods.** It catches
  "piece on square X" placement claims, but not false claims like
  "you've developed both bishops" when none are developed (seen live
  from hermes3:8b). Another class it misses: **piece-type
  misidentification** — during BUG-011 verification, qwen3:8b described
  the hanging e5 *pawn* as a "queen" (and in another run contradicted
  itself about whose queen attacks it). The engine data was correct;
  the model mislabeled it. A third live instance (2026-06-19, qwen3:14b,
  guidance on / template_only off): after `1.e4 e6 2.Nf3 Nf6 3.Nc3 Nc6
  4.Bb5 Be7`, the coach narrated Black's `...Be7` as a **White** move
  ("supports White's e4 pawn", "White's kingside castle") and claimed the
  e7 bishop pressures "the long diagonal" (it doesn't) — a wrong-side /
  perspective falsehood plus an invented geometric claim. The engine data
  was correct; the model's prose got the color and geometry wrong. Notably
  this is exactly the weakness the **profiler flagged for qwen3:14b before
  it was seen live** (factual 0.26, hallucinations>0 → it recommended
  `template_only: true`) — a clean validation that the capability profile
  predicts real runtime behavior. **Partial root-cause + fix (same day):**
  the wrong-side flip traced to the one prompt that never got the BUG-011
  perspective fix — `ENGINE_MOVE_EXPLANATION_PROMPT` (web play-mode
  engine-move explanation) handed the model only a FEN, no plain-language
  side-to-move line. Added `_format_perspective(fen_before)` to that prompt
  (+ regression test); so the *wrong-side* class from this path is now
  prompt-fixed. The *residual* factual rate (0.26) was measured on the
  already-perspective-fixed rich prompt, so it's the model's floor, not a
  prompt gap — the honest split is: side-flip = prompt-induced (fixed),
  general factual shakiness = inherent to qwen3:14b. The judge's `grounded`
  criterion is the backstop; extending the objective check to catch
  development/possession and piece-type claims is a future improvement.
  These are LLM-output quality issues (not code bugs) — the value is in the
  eval harness measuring their *rate*, not in chasing single anecdotes.

- **The engine as verifier — grounding strategy (consolidated).** One
  asset ties together several scattered ideas: the engine + python-chess are
  a **deterministic verifier** of factual claims (whose move it is, what's on
  each square, what's legal, the eval). Most domains lack this and must pay a
  second LLM to critique; chess hands it to us almost free. The strategy is
  to spend that one verifier in three places:

  1. **Measure (today).** The hallucination detector + judge `grounded`
     criterion already check claims against ground truth — but only as
     measurement, and with gaps (see "Hallucination detector misses
     relational falsehoods" above: it misses development/possession and
     piece-type claims).
  2. **Offline — prompt ablation (PROPOSED).** A benchmark score is always
     model×prompt, never the model alone, so one factual number can't say
     whether a weakness is the model or the prompt. Lean addition to the
     profiler's `factual` dimension: run the same model + same positions
     through a small named set of prompt variants (`baseline` FEN-only,
     `perspective`, `strict-grounding`, and the mandatory `production` prompt
     the live app actually ships), score each with the verifier, and report
     the **spread** (best−worst). Big spread → prompt-sensitive, invest in
     prompting before swapping the model; flat spread → model floor, swap it.
     Keep N at 2-3 (judge cost multiplies). Discipline this enforces: **the
     benchmark must exercise the same prompts production uses** — the Be7
     flip happened because the live engine-explanation path ran an unpatched
     prompt the profiler never tested (it measured the fixed rich prompt).
  3. **Online — validation/repair loop (PROPOSED).** Let the model write →
     machine-check its claims against the verifier → repair once if wrong.
     This is **model-agnostic** (no per-model prompt matrix to maintain),
     which fits the project's swappable-model premise better than prompt
     tuning. It reframes the existing knobs as a spectrum: `template_only`
     = the crudest loop (don't trust the model, bypass it); prompt
     engineering = get it right in one shot; the repair loop = the
     sophisticated middle. Cost: extra inferences per answer.

  **How offline and online connect:** ablation and the loop are the
  design-time and run-time spend of the *same* verifier. A loop is also a
  data generator — its repair logs show what the prompt keeps getting wrong
  (e.g. repeated wrong-side catches → "add the side-to-move line", exactly
  the fix already made by hand), which feeds offline prompt improvement. So
  the **hybrid** is the endgame: mine loop failures offline to tighten the
  static prompt so the loop fires less often — one-shot handles the common
  case, the loop only mops up the residue. Loops can't *directly* improve a
  prompt, but their output is the richest raw material for doing so.

  **Shipped (2026-06-19) — first concrete application:**
  `src/chess_coach/verify.py` `filter_illegal_threats(report)` drops
  engine-supplied `Threat`s whose move is illegal for the owning side
  (pins / in-check ignored), validated with python-chess; wired into
  `CoachingEngine.get_position_report` so quick-mode templates and the LLM
  both get cleaned data. This is the rules-tier verifier checking the
  *engine* (not just the LLM). Caught the live `Nc3 can capture Qe4` /
  `f6 can capture g7` bug from the Qe4+ position. **Still open:** (a) the
  proper root-cause fix is in the Blunder repo (its threat detector should
  be legality-aware); (b) tactics (`TacticalMotif`: discovered-attack /
  back-rank lines) are NOT filtered — they carry no single move and the
  "in-PV" ones describe the variation, not the current position; (c) the
  filter is not applied to `ComparisonReport` (it has no `threats` dict
  today, so no gap, but watch it if that changes).

- **Blunder coaching threat/tactic detection (root-cause) — DONE
  (2026-06-19, blunder@491ec6c).** The defensive filter only hid the symptom
  on the chess-coach side; these are now fixed at the source in
  `PositionAnalyzer.cpp` (with `TestPositionAnalyzer.cpp`, 5 cases):
  1. **Legality-unaware threats — fixed.** `find_threats` now builds the legal
     move set via `MoveGenerator::add_all_moves(board, side)` and only emits
     capture/check threats whose move is legal, so pinned-piece captures and
     captures that ignore an existing check are dropped at the source.
  2. **Malformed discovered-attack text — fixed.** The PV scan skipped the
     just-moved slider as its own "revealer" (`s_sq == to_sq` guard), killing
     "Bc3 moves to reveal Bc3".
  3. **Mislabeled motifs — fixed.** Back-rank is only labeled when a
     rook/queen actually lands on the king's back rank (diagonal checks no
     longer mislabeled); pawn pins to a non-king piece and pawn-backed skewers
     are filtered as noise (kills `Qg5 pins d2 to Bc1` / `pins g2 to Ng1`).
  4. **`squares` contract — fixed both sides.** `discovered_attack` now emits
     `squares = [revealed_attacker, target, mover]` (documented per-type in
     `docs/coaching-protocol.md`), and chess-coach `_extract_arrows` draws the
     revealed attack line `attacker → target` only (no bogus `attacker → mover`
     arrow). So the live overlay after `1.e4 e6 2.Nc3 Qg5` is `c1 → g5`, not
     `c1 → d2` / `c1 → d4`.

  The chess-coach defensive filter (`verify.filter_illegal_threats`) stays as
  belt-and-suspenders for any engine that doesn't speak the fixed protocol.

- **Engine-as-oracle quality at depth 8.** Ground truth is the engine
  report; at depth 8 it can disagree with opening theory (e.g. it
  judged the four-knights Italian as Black-better by grabbing e4).
  Acceptable by design (oracle = engine), but deepening the engine or
  raising depth/multipv would improve annotation quality.

- **Judge robustness (design open questions).** Single judge vs a
  2-judge panel with disagreement surfacing (cost vs robustness);
  seed-set size for calibration (starting at 20); the coverage check
  can be fooled by an incidental square mention — the judge's
  `grounded` criterion is the v1 backstop.

- **Live Layer 2 validation with a true frontier judge.** Any live
  judge run so far would use EC2 qwen3:14b (a local 14B that "thinks"),
  which isn't a frontier model and risks self-preference when judging
  qwen-family output. Revisit with a real frontier endpoint (FITT
  gateway `fitt-smart`, or a direct Anthropic/Bedrock key).

- **How is the automated Layer-2 judge actually served?** The judge
  needs a *callable* frontier endpoint; the in-session "Kiro is the
  judge" mode is session-bound and can't be automated (a human rater
  has the same limitation — neither is an unattended endpoint). So
  "Kiro/human as judge" is really a **Layer-3 calibration / validation**
  role (the trusted gold rater that `calibrate.py` measures the cheap
  automated judge against), not the Layer-2 automation engine. Options
  for the automated endpoint, none wired yet:
  - **FITT gateway `fitt-smart`** — but FITT currently has no Claude /
    frontier-cloud binding on that alias, so today it'd resolve to a
    local model, not a true frontier judge.
  - **`kiro-cli`** — drive a frontier model non-interactively as the
    judge backend. **Shipped and validated:** `CliProvider`
    (`--judge-provider cli`) with
    `--judge-command "kiro-cli chat --no-interactive --model claude-sonnet-4.6 {prompt}"`.
    Note kiro-cli takes the prompt as the positional arg (the `{prompt}`
    token), not stdin; output lands on stdout, the credits/time footer
    on stderr (discarded). Validated against the 3 saved hermes3:8b
    responses under rubric.v2: it agreed with the in-session Opus judge
    on all three verdicts (all poor, grounded fails everywhere; kr_vs_k
    identical at 0.03) and was *stricter and better-grounded* on
    `after_1f6` (0.03 vs 0.20 — it flagged the "implies White is in
    danger when engine says +55" contradiction). **Full run done:** the
    automated judge ran the whole 9-position benchmark unattended
    (hermes3:8b, sonnet-4.6, rubric.v2) — factual mean 0.17, quality
    mean 0.08, 0% pass; Layer 2 tracks Layer 1, gates held. The
    automated Layer-2 judge is now operational end-to-end. Next: seed
    Layer-3 calibration from agreement/divergence, and judge stronger
    models under test.
  - **Direct frontier API key** (Anthropic / Bedrock / OpenAI) behind
    the existing `OpenAICompatProvider` — simplest if a key is
    available.
  Decide the endpoint before investing in `rubric.v2` / scaled judging.

- **Benchmark size.** Only 10 seed positions today. Grow toward
  20-40 across phases/levels once the annotation guard (Task 9) makes
  authoring safe.

## Shared "reliable LLM access" library (cross-project)

- **Extract a neutral `llm-access` library shared by chess-coach and
  FITT.** Both projects independently grew the same problem: talking to
  local/remote LLMs *reliably* — split timeouts (liveness ping vs
  inference read), a dispatch-outcome taxonomy, retry-once + fallback,
  reachability probing, reasoning/`<think>` handling. FITT solved it
  inside its gateway; chess-coach is growing the same logic in
  `src/chess_coach/llm/`. Rather than chess-coach depending on FITT
  (wrong direction — FITT is a heavyweight always-on service, chess-coach
  is a single-user/offline app), extract the common core into a third,
  neutral package both depend on.

  - **Shape:** a *library* (in-process), not a service. chess-coach uses
    it directly; FITT's gateway is built *on top of* it (gateway keeps
    its server, alias routing, auth, memory, tools, dashboard, cost).
  - **In scope:** provider protocol (generate/stream/reachability) with
    thin Ollama + OpenAI-compatible backends; split connect/probe vs
    read/inference timeouts; `DispatchOutcome` taxonomy + classifier
    (already drafted dependency-free in `llm/outcome.py`); retry-once +
    fallback endpoint/model; optional reasoning stripping.
  - **Out of scope (stays per-app):** FITT's routing/aliases, Bearer
    auth, memory, tools/MCP, approvals, dashboard, cost, and the HTTP
    server; chess-coach's chess prompts, coaching templates, eval rubric.
  - **Timing:** extract on the *second* real implementation, not the
    first. FITT is impl #1; chess-coach's cheap-fixes work is impl #2.
    Build the pieces here extraction-ready (no chess/FITT specifics),
    prove the shape against both, then lift into a standalone repo
    (e.g. `qam4/llm-access`) and have both consume it. FITT may keep
    LiteLLM as one backend behind the same protocol.

## Environment / tooling

_(Cleared — the repo migrated from tox to [uv](https://docs.astral.sh/uv/).
`uv sync` builds one `.venv` with runtime + dev deps, so the previously
broken `.venv` and the `rich`-less typecheck env are both resolved;
`uv run mypy src` is clean. CI now runs on uv too.)_
