# Backlog

Things we discussed but deliberately deferred. The rule: if we talk
about doing something and don't do it now, it lands here with enough
context to pick up later. Distinct from:

- **IDEAS.md** — open-ended feature ideas / research directions.
- **BUGS.md** — known defects.
- **`.kiro/specs/*/tasks.md`** — committed, scoped work for an active feature.

This file is for "real, agreed, not-yet-scheduled" follow-ups.

## Recently shipped

- **Grounded move advice — SHIPPED (2026-07-28).** Spec
  `.kiro/specs/grounded-move-advice/`. The coach now names concrete moves
  only from an engine-verified, soundness-tagged candidate menu. Input
  side: `coaching_phrases.build_move_menu` turns the engine's `top_lines`
  into `MenuMove`s tagged `best`/`sound`/`dubious`/`blunder` from
  eval-drop-from-best (thresholds shared with `Coach.classify_move`), the
  rich prompt renders that compact menu (SAN + eval + tag + theme) in place
  of raw "Top Engine Lines", and a gated `MOVE_SOURCING_RULE` (default on
  via `coaching.constrain_moves`) forbids naming a move that is not
  `best`/`sound`. Output side: `verify.check_coaching_fidelity` +
  `check_text_fidelity` return categorized `Violation`s (illegal /
  unsound / placement / development / empty_source), precision-first and
  total; the eval harness's `objective.py` detector was consolidated onto
  it (one implementation). SAN is used everywhere the coach names a move.
  A live run on the Italian position confirmed the fix: the coach
  recommended `O-O` (sound), no phantom `Nxe4`, no invented pieces.
  `top_moves` (multipv) default raised 3→5. Task 7: the fidelity checker
  is wired as a Layer-1 diagnostic (`ObjectiveResult.fidelity_counts`,
  `off!` scoreboard column, `eval_run --constrain-moves/--no-constrain-moves`
  A/B toggle) that does NOT feed `factual_score`.

  **Adherence metric (the right one).** A named move cannot be judged
  objectively unsound unless it is scored (we don't score every legal
  move). But the coach is *told* to recommend only listed `best`/`sound`
  moves, so any named move outside that set is a violation of the rule we
  set: `off_menu` (legal, not listed — the real `Nxe4` case, which the
  engine ranks below the top-5) or `unsound_move` (listed but tagged
  dubious/blunder). The scoreboard's `off!` = their sum. This needs no
  engine re-scoring and directly measures constraint adherence.

  **A/B (2026-07-29, 10-position benchmark incl. `italian_nxe4_trap`,
  temp 0.7, Layer 1):**

  | model | constraint | off-menu | illegal | factual |
  |-------|-----------|:---:|:---:|:---:|
  | qwen3:8b  | off | 1 | 0 | 0.27 |
  | qwen3:8b  | on  | 1 | 1 | 0.33 |
  | qwen3:14b | off | 3 | 1 | 0.23 |
  | qwen3:14b | on  | 0 | 0 | 0.27 |

  **Verdict: the constraint works on the capable model.** qwen3:14b's
  off-menu recommendations dropped 3 → 0 (and illegal 1 → 0) with the
  constraint on; qwen3:8b was unchanged (1 → 1, even added an illegal) —
  it does not reliably follow the instruction, matching the broader
  finding that guidance helps capable reasoning models, not small ones.
  `factual_score` stayed comparable across conditions, as designed (the
  adherence metric is diagnostic, not part of the score).

- **`off!` warn-context guard (done 2026-07-29).** The checker now
  suppresses `off_menu`/`unsound_move` when a strong warning cue ("avoid",
  "don't play", "instead of", "tempted to play", …) appears just before
  the named move — naming a bad move *to warn against it* is allowed by
  the prompt. Conservative/precision-first: a warning phrased AFTER the
  move ("Nxe4 loses a piece") is not detected and is still counted (a
  documented, minor over-count). Illegality is never suppressed.

- **More temptation positions (done 2026-07-29).** Added
  `italian_nxe4_trap` (Nxe4 off-menu/unlisted → `off_menu`) and
  `scotch_nxe4_trap` (Nxe4 a listed blunder → `unsound_move`), covering
  both violation kinds. Confirmed hard: on these two, unconstrained
  qwen3:14b made an illegal move that the constraint fixed. More traps
  could sharpen the A/B further but the metric has clear signal.

- **Engine gap — per-line theme is hardcoded empty (found 2026-07-28).**
  Blunder's `CoachJson.cpp::serialize_top_lines` emits `"theme": ""` for
  every multipv line and never calls the existing (dead)
  `PositionAnalyzer::label_line_theme`, which would return a real label
  (worst case `"general play"`). Effect: the coach's candidate-menu theme
  column is blank and the grounded-move-advice theme→knowledge bias
  (Req 4) no-ops in production — it degrades gracefully to feature/ECO
  guidance selection, which already works. Low priority: the fix is a
  small, additive Blunder change (thread the root board from `r.fen` into
  `serialize_top_lines`, call `label_line_theme(board, pv.moves)`) plus a
  rebuild + its test suite. Deferred because guidance selection does not
  depend on it.

- **Client-side coaching-text composition — SHIPPED (2026-07-02).**
  Spec `.kiro/specs/client-side-coaching-text/`. The engine's prose
  `description` fields (tactics / threats / king-safety) are no longer
  rendered or fed to any LLM; all coaching sentences are composed from
  the engine's *structured* facts by a single source of truth,
  `src/chess_coach/coaching_phrases.py`, consumed identically by the
  coaching prompt, the templates, `insights`, and — by scope extension —
  the eval judge's `format_engine_report`. Proven by a sentinel test
  (`tests/test_no_prose_leak.py`: every `description` = a marker ⇒ absent
  from every rendered surface) plus a coach/judge parity test. Along the
  way: `verify.filter_illegal_threats` now reads the structured
  `uci_move` (regex over prose deleted); Blunder gained structured
  king-safety fields (`king_square`, `castling_status`,
  `missing_shield_files`, `open_file_near_king`, `pawn_storm`) so the
  client composes king-safety without reading prose or re-deriving engine
  logic; the on-board vs in-PV distinction is now a clear phrase, not the
  "in PV" token. `description` is retained as engine debug output only.
  **Deferred / none outstanding:** the threat-map stays a per-medium
  structured table (LLM counts vs UI tensions) by design — not a prose
  category. Short labels (`theme`, `best_move_idea`, `critical_reason`)
  remain engine-owned.

## Grounded position description for the coach (decided 2026-07-02)

- **The coach MUST be given an explicit piece-placement description — a
  required input, not optional.** Live finding: `chess-coach explain` on
  the Italian (1.e4 e5 2.Nf3 Nc6 3.Bc4 Bc5 4.d3 Nf6 5.Nc3), qwen3:14b,
  guidance on, produced warm, correctly-toned coaching that was
  **factually wrong about the board**: it told Black "your knights and
  bishops are still on the back rank — move your knight from b8 to a6 or
  c5", when Black's minors are already developed (Nc6, Nf6, Bc5), b8 is
  empty, c5 is Black's own bishop, and a6 is the rim.

  **Root cause:** the *only* complete piece-placement in the prompt is the
  FEN string, and LLMs — especially small ones — do not reliably decode
  FEN into a board (supported by LM chess state-tracking work, e.g.
  arXiv:2102.13249: explicit board state helps most at smaller scale;
  arXiv:2411.06655 on LLM chess reasoning limits). So the model does not
  actually know where the pieces are; it pattern-matches on the opening
  name + the injected "development" theme and invents pieces. The strict
  "never place a piece unless the data confirms it" rule can't help — there
  is no positive placement data to obey.

  **Decision:** render placement ourselves from `python-chess` (we already
  hold the `chess.Board`) as a compact, explicit, plain-language block —
  never rely on the model reading FEN. A verified concreteness check
  produced ~5 lines per position, e.g.:
  `Black: K e8, Q d8, R a8 h8, B c5 c8, N c6 f6, P a7 b7 c7 d7 e5 f7 g7 h7`
  + `developed: Nf6 Nc6 Bc5 | still home: Bc8`. Cheap and complete, so
  completeness is nearly free; keep the prompt lean by trimming
  lower-value bulk (the ~36-half-move deep top-lines) rather than
  withholding placement.

  **What the block includes (agreed):** piece locations + developed/home
  summary is the core. Side-to-move is already stated. Castling comes
  through `king_safety.castling_status` (don't duplicate raw `KQkq`).
  En passant only when a real e.p. capture exists. Halfmove clock only for
  future endgame-technique coaching; fullmove number optional (phase is
  better derived from material/ECO). The coach never needs to *compute*
  legality — the engine already supplies legal/best moves and threats.

  **Open (decide by measurement, not decree):**
  1. **Format** — piece-list vs ASCII 8×8 grid vs rank-by-rank. Piece-list
     favoured on compactness; pick via A/B.
  2. **Who reasons** — LLM reasons from the grounded block, OR the
     deterministic layer (composer, which already has the board) selects
     the 1–2 correct points and the LLM only *voices* them (IDEAS "Layer 1
     facts → Layer 2 voice"). The latter fits small models best.

  **How to measure the effect (objective — no judge needed for this
  defect):** placement/legality is deterministically checkable against
  `python-chess`. Metric = *placement-fidelity violations* per response:
  claims that contradict the real board or rules (piece not on the claimed
  square; "undeveloped" when developed; a suggested move that is illegal /
  from an empty square / onto one's own piece). A/B on one variable —
  {FEN-only baseline} vs {+ placement block} (× small model and qwen3:14b),
  same benchmark positions, compare violation counts. This is the
  prompt-ablation lever + the output-side of "engine as verifier"; extends
  the existing hallucination detector (which today catches "piece on X" but
  misses development/possession — see that item below). Overall *teaching*
  quality stays the pairwise-judge job. First read: re-run the Italian
  position above with the block added and confirm the Nb8-class errors drop
  to zero.

  **Also captured (product-owner's example teaching moments, not to lose)
  — concrete contextual advice the current resource does NOT cover:**
  capturing the most valuable piece with the least valuable one
  (recapture / exchange value), *when to exchange* (trade down when ahead,
  keep pieces when attacking), and *when to push a pawn and which one*
  (create/advance a passer, use a majority — beyond the existing
  endgame "square of the pawn" entry). These need (a) knowledge entries
  from the canon and (b) engine-computed features to key them (material
  lead + trade-available, pawn majority, recapture choice) — part of the
  "grow the resource" + "richer engine features" levers.

  **SHIPPED (2026-08-05).** All three teaching moments are now in the
  resource, keyed to three new board-derived `Position_Feature`s (added to
  the closed `FEATURE_VOCAB`, extracted deterministically from the board in
  `features.py`, same discipline as `open_file`/`exposed_king`):
  `favorable_capture` (a material-winning capture exists — higher-value or
  undefended victim) → entry `principle.capture_value`; `material_lead` (side
  to move up ≥ 2 pawns) → `principle.exchange_when_ahead` (trade pieces not
  pawns when ahead; keep pieces when attacking/behind); `pawn_majority` (a
  flank a–c/f–h pawn majority) → `principle.pawn_majority_push` (advance the
  majority, push the candidate first). Verified end-to-end: each triggering
  position selects exactly its new entry (features → selector → guidance).
  **A/B VALIDATED (2026-08-05).** Built a capture/material-heavy move-feedback
  benchmark (`data/eval/move_feedback_material.yaml`, 10 scenarios: 4 capture,
  3 exchange, 3 pawn-majority; each verified to fire its intended feature) and
  ran the move-feedback pairwise A/B (guidance off vs on, qwen3:14b, sonnet
  judge via kiro-cli, 3 votes/pair). **Result: ON 9, OFF 1, on win-rate 90%,
  two-sided sign test p=0.021 — significant.** The judge rationales confirm
  real teaching: ON won by naming the concrete principle and staying grounded
  (e.g. "capture with the least valuable piece" = `capture_value` verbatim;
  "queen trade and simplification toward the endgame" = `exchange_when_ahead`),
  while OFF drifted into vague/positional advice, invented a king-attack
  narrative, or made a piece-type error ("wins a pawn" when the capture won a
  knight — the BUG-015 class). So the new content measurably helps exactly the
  moves the game test found the coach weak on. Caveats: small n (10); the K+P
  majority positions are sparse enough that `phase:endgame` also fires, so the
  judge sometimes credited "king activity" over the majority principle — a
  piece-richer majority set would isolate that lesson; the one OFF win was ON
  adding a less-relevant king-safety aside. The `favorable_capture` trigger is
  a heuristic (no full static-exchange eval); the engine lines in the prompt
  remain the oracle for the actual move. Follow-up: a larger, more
  game-realistic scenario set (and isolate the majority lesson).

## Coaching-eval harness

- **End-to-end game-coaching eval — SHIPPED (2026-07-30),
  `.kiro/specs/game-coaching-eval/`.** The current benchmark judges the
  coach on isolated, curated positions — the "position analyst" mode
  VISION does NOT want, and it never exercises the reactive move-feedback
  path over a real game arc. Idea (product owner): drive a **whole game**
  and check the coaching across it. Design agreed this session:
  - **Players = Blunder at chosen Elo** (`UCI_LimitStrength`/`UCI_Elo`,
    already wired via `Coach.play_elo`). The *student* side plays weak
    enough to make real, coachable mistakes (~1350 default, configurable);
    the opponent at a chosen level. The **coach's analysis engine stays
    full-strength** — same binary, three roles (student-weak, opponent,
    coach-oracle-strong).
  - **Coach = the existing local-LLM `Coach.evaluate_move`** on each
    student move (the move-feedback path). Reuses the shipped pipeline.
  - **Judge = kiro-cli frontier** (`CliProvider`, `--judge-provider cli`,
    already shipped/validated) scoring each coaching output vs engine
    ground truth (reuse the move-feedback rubric). Whole-game context lets
    it assess what per-position judging can't: did it catch the turning
    points (`critical_moment`), stay consistent, avoid repetition. Using a
    frontier model to judge the local LLM is accepted (a proxy, honest
    ceiling per "Who calibrates teaching quality?"), valuable as an E2E
    test that surfaces integration + quality issues.
  - **New parts:** a **game-trajectory driver** (play a full game between
    two leveled Blunders, capture the per-student-move trajectory:
    position, move, engine best/eval/classification, active features,
    coach output) + game-level aggregation/report. Everything else is
    reuse. Run via kiro-monitor (~20–40 coached moves/game). Shape: a
    `scripts/` driver + pure `eval/` core, like the other eval tools.
  - **v1 = per-move judging** (reuses the shipped judge); **v2 = a
    game-level pass** for consistency / turning-points / non-repetition.
  - **Synergy:** the trajectory it produces is exactly what the cross-game
    tracker (below) consumes — this harness is also the tracker's test
    fixture and first data source.
  - **Shipped:** pure core `eval/game_coaching.py` (`play_game` /
    `aggregate` / `TurnRecord` / `GameTrajectory`, unit+property tested),
    judge-free driver `scripts/eval_game_coaching.py` (objective fidelity
    per turn), and the **pairwise** driver
    `scripts/eval_game_coaching_pairwise.py` — a played game's student moves
    become move-feedback scenarios fed to the existing validated
    `run_move_feedback_pairwise` (guidance off vs on), judged by the
    frontier kiro-cli. Three Blunder roles kept distinct (student-weak /
    opponent / full-strength coach oracle).
  - **First live result (2026-07-30):** qwen3:14b, 2 games @ student 1350 /
    opponent 1500 Elo, 40 coaching scenarios, sonnet judge via kiro-cli,
    guidance OFF vs ON. **ON 21, OFF 12, 7 ties → 64% win-rate of decisive,
    two-sided sign test p=0.163 (not significant).** Directionally positive
    and consistent with the curated move-feedback finding (qwen3:14b 75%,
    p=0.041); weaker here because game trajectories include many quiet good
    moves where guidance barely matters. The instrument works end-to-end;
    more games (bigger n) would firm up significance. Next: more games /
    models; a game-level judging pass (consistency / turning-points);
    generalize the A/B beyond guidance (e.g. constrain-moves).
  - **Two modes — and single/absolute is the right one for bug-finding
    (insight 2026-07-30).** A/B (pairwise) reveals *differences* between two
    configs and is the low-noise tool for change-detection; but a bug
    present in BOTH arms hides as a "tie", so A/B is the wrong instrument
    for "is the coach bugged?". The three bugs below leaked out of the A/B
    run only incidentally (ties / the losing side's flaw). A **single mode**
    — run ONE coach config over a game, frontier model audits each move
    against the engine ground truth and emits a findings report — surfaces
    defects directly, no second version needed. NOT built yet (the v1 A/B is
    what shipped); single mode is the natural next addition when we want the
    test to self-report bugs rather than hand-mine A/B rationales.
  - **Bugs + gaps this test surfaced (its real payoff).** Mining the 40
    judge rationales (not the tally) exposed concrete coaching defects the
    curated position benchmarks never caught — logged as BUG-013 (coach
    invents ungrounded follow-up lines), BUG-014 (coach second-guesses a
    move that was already the engine's best), BUG-015 (piece-type/geometry
    misID in prose). Two teaching-quality gaps toward the north star also
    showed up empirically: (a) **filler / condescending praise dilutes the
    lesson** — the judge repeatedly preferred the concise "one principle +
    one concrete action" version over cheerleading; and (b) **the coach is
    weak exactly on material-winning/tactical moves** — on good captures
    like `fxg5` *both* off and on "named no concrete principle or actionable
    follow-up", because the knowledge bank still lacks capture-value /
    recapture / when-to-exchange entries (the content gap already noted
    under "Grounded position description"). So the game test both validated
    the instrument AND handed us a prioritized fix list.

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

  **Input-side precondition now specced (2026-07-01):** the client-side
  composition of coaching sentences from structured facts — which makes
  the *inputs* to the LLM ground-truth by construction — is captured in
  `.kiro/specs/client-side-coaching-text/`. That spec owns the rules-tier
  verifier on the engine's own facts (keeping `filter_illegal_threats`,
  dropping its regex for `uci_move`) and explicitly EXCLUDES the
  output-side verifier (prompt ablation + write→check→repair loop), which
  remains this item. The two are complementary: correct inputs shrink what
  the repair loop must catch; they do not replace it.

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

## Progress tracking — cross-game (VISION Step 2)

- **Cross-game player progress tracker — AGREED follow-on (2026-07-30).**
  VISION's Step 2 ("the arc this unlocks") and the honest path toward
  true-north (student improvement over time). Refined framing from the
  product owner this session: this is **longitudinal across games**, NOT
  in-game. The in-game move feedback already exists (`evaluate_move`); the
  tracker is the store + cross-game aggregation + trend + targeting.
  - **Mechanism (from IDEAS "Player Strength Profile"):** for each student
    move, attribute it to the dimension(s) the position exercises
    (material awareness, piece activity, pawn structure, king safety,
    trading, endgame technique, opening principles, tactical vision), score
    whether the move aligned with the engine *in positions where that
    dimension mattered*, and aggregate per-dimension across all the
    student's games into a profile + **trend over time**, then target
    coaching at the weakest dimension.
  - **New parts vs today:** (a) **dimension attribution** — map (position
    features + what the best move addresses) → dimension, reusing the
    engine features + `theme_map`; (b) **persistence** — a per-user local
    store (JSON/SQLite; VISION: local-only, nothing leaves the machine),
    since play today is stateless; (c) **surfacing** — a CLI/web dashboard
    of per-dimension ratings + trend.
  - **Consumes the game-trajectory substrate** from the E2E eval above, so
    build that first: the eval's simulated games are the tracker's first
    data + a way to validate the dimension model before wiring persistence
    and UI for a real user. Ties to IDEAS "Structured Learning Path" and
    the (later) level-adaptive teaching, VISION Step 3.

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


## Coach report card — single-mode holistic review (2026-08-05)

Built a **single-mode** review (not A/B) to answer "is the coach the teacher
VISION describes?": `scripts/eval_coach_review.py` + pure core
`src/chess_coach/eval/coach_review.py`. It plays one real game, coaches every
student move with the shipping config (guidance on, qwen3:14b) timing each
generation, appends curated endgame/tactic positions for phase coverage, then a
frontier reviewer (sonnet via kiro-cli) gives ONE verdict: a 0–10 score against
the bridge standard + honest critique + phase-fit. (Run artifacts under
`output/` are gitignored, so the findings are recorded here.)

**First run (1 game @ 1350/1500, 44 coached turns incl. 18 endgame): SCORE
3.5/10 — "a position commentator that pads with chess-sounding phrases, not a
teacher."** The instrument works; the verdict is a to-do list:

1. **Principle (bridge end 1) is generic and recycled.** "Develop your pieces /
   control the center / is my king safe?" recurs on ~16+ plies regardless of
   context — same abstraction whether the student hung a bishop, played the
   best move, or pushed a pawn in the endgame.
2. **Concrete plan (bridge end 2) often missing or wrong on the moves that
   matter most.** The biggest blunders got the weakest explanations — no "if
   Kd1, Black plays … and wins the rook", just structural platitudes.
3. **Praise on best moves is filler + near-duplicate text.** ~11 best-move
   turns got "Great job — it's the best move!" + the same principle; several
   endgame turns were word-for-word identical.
4. **Phase blindness (confirms the product-owner's hunch that opening ≠
   endgame).** Opening vocabulary ("develop your pieces") used in the endgame;
   rook-and-king technique (the actual endgame here) never named. The reviewer's
   recommendation: opening → name the specific opening principle at stake;
   middlegame → concrete tactical calculation; endgame → named techniques
   (opposition, rook behind the passer, Lucena/Philidor).
5. **Verbosity/padding** — motivational sign-offs, ~2 sentences of content in a
   5–6 sentence answer.
6. Latency is fine (~5.8s mean/turn; a 32s ply-0 warmup skews the mean).

**Highest-leverage change (the reviewer's, and the natural "consolidate the
coaching" next step):** make the coach name ONE named, *phase-specific*
principle per turn and show how the engine-best move instantiates it *in this
position*, and ban the generic "develop your pieces / is my king safe?" fallback
unless the position specifically calls for it. Trim the filler sign-offs. This
is a coaching-prompt (and possibly pedagogy-content) change, to be designed
next; the report card is now the instrument to measure whether it moves the
3.5.

Also fixed: the review driver reconfigures stdout to UTF-8 so the final console
print of the review can't crash on cp1252 (the UTF-8 `review.md` was always
written; only the terminal echo failed — same class as BUG-012, in the script).


### Coach report card — lever 1 (remove the always-on principles crib) — 2026-08-05

First measured coaching change under the report card. **Lever 1 (one lever, for
clean attribution): removed the static "CHESS PRINCIPLES" crib list from
`SYSTEM_PROMPT_V2`** (opening-centric, injected on every turn — the suspected
driver of recycled generic advice and phase-blindness). Re-ran the report card
at the SAME seed (7) → identical game (44 turns, same phase/quality mix), so a
clean before/after.

| metric | baseline | crib removed |
|---|---|---|
| judge score | 3.5 | 4.2 |
| off_menu | 8 | 8 |
| unsound_move | 4 | 5 |
| placement | 1 | 1 |

**Read:** the judge's holistic score rose +0.7 (less pure genericness), but the
**deterministic fabrication counts are flat** — removing the crib did not touch
off-menu/unsound. Caveats: n=1 per condition, so +0.7 is directional (the flat
deterministic counts are the trustworthy part); no regression, low risk (the
guidance layer supplies principles), so lever 1 is kept.

**The measurement re-prioritized the roadmap.** With genericness reduced, the
judge's #1 concern shifted to **fabricated/ungrounded causal analysis** ("Bc4
allows Black to capture on d4" — invented; "a3 supports d4" — wrong square;
"a2 isolated" as a3's reason — guessed), calling it "the single most damaging
problem … a coach that confabulates is worse than no coach." This **meets the
BUG-017 revisit trigger** (flagged often: ~5 cited instances + 13 deterministic
off_menu/unsound). So BUG-017 is un-parked and becomes lever 2: constrain the
coach strictly to engine-stated facts (eval drop, specific squares, concrete
consequences) and forbid inventing causal chains it cannot verify — measured
the same way (report card, same seed) before/after.

### Pedagogy — instantiated facts on the position path, and the attachment rate — 2026-08-11

Follow-through on report-card item 4 ("instantiate each guidance theme with the
board fact that fired it"). Item 4 barely moved principle-connection on the
move-feedback path because the model preferred the move-anchored clause from
item 3. The stated hypothesis was that instantiation should matter MORE on the
**position-coaching** path (`chess-coach explain`), which has no move to anchor
to. Wiring it there is a one-liner, since `build_rich_coaching_prompt` already
holds the `PositionReport`.

**Two measurement dead ends, both worth recording so they are not repeated.**

1. Scoring the position path with `is_specific` / `connects_principle` gave
   **6/6 vs 5/6 — a saturated metric**. Those two were built for move feedback,
   where the student's and engine's move squares are *discounted*; the position
   path has no such move, so any square mention passes, and a full position
   explanation always puts a theme word near a square. A saturated metric cannot
   answer the question, so the run was thrown away rather than reported.
2. Rescoring on "does the composed fact reach the output" then **skipped 4 of 5
   positions**, because no *selected* entry carried a fact at all.

**That second dead end was the real finding, and it is a coverage bug, not a
prose problem.** Measured offline over 10 positions with the engine only (no
LLM, following the item-3 discipline of measuring coverage before spending a
run): **only 10 of 30 selected entries (33%) could be instantiated**, and just
6 of 10 positions carried a single fact. Every opening position scored 0/3.

**Root cause, verified rather than guessed.** Entries tie on relevance (each
matches exactly one present feature) and the tie-break — type, then `id` — is
blind to whether a fact exists. So in a position with a live threat, the
abstract `center control` beat `answer the threat first`, which would have
rendered "HERE: there is a live threat against f7".

First attempt folded the fact bias into the existing `preferred_features` hook
and only reached 18/30. Instrumenting the misses showed why, and it was a
**collision between two soft biases**: the engine's PV theme
`"piece development"` maps to the broad `phase:opening` feature, so the
move-theme bias handed the same +1 to all three abstract opening entries and
cancelled the fact bias out. Fixed properly by giving instantiability its own
rank term in `_sort_key`, above the theme bonus and below relevance — being
instantiable is a stronger teaching signal than matching the move's theme.

| | attachment (selected entries) | positions with >=1 fact |
|---|---|---|
| before | 10/30 (33%) | 6/10 |
| fact bias folded into `preferred_features` | 18/30 (60%) | 8/10 |
| fact bias as its own rank term | **23/30 (77%)** | **10/10** |

Still a tie-break only: it never admits or drops an entry, and a genuinely more
relevant entry still wins (both properties have regression tests). The remaining
7 of 30 are positions where fewer than three eligible entries can carry a fact —
a genuine content-coverage limit, not a ranking one.

**Next:** the LLM A/B on the position path is only now worth running, since
before the fix most positions had no fact to test.

### Measurement corrections found by reading the coach's actual output — 2026-08-11

Two defects, both found by inspecting prose rather than by a failing test.

**1. `_SQUARE_RE` was blind to SAN, so both headline metrics were wrong.**
`\b[a-h][1-8]\b` matches nothing in `Ra8#`, `Rxc8#`, `Nf3` or `cxd5`. So
`connects_principle` under-counted (a square named in SAN was invisible) and
`is_specific` over-counted (its discount set, built from the move SANs, was empty
for every piece move, so echoing the move back scored as specific). Recomputed
from the saved transcripts — no LLM, no engine:

| run | specificity | principle-connection |
|---|---|---|
| v17 | 27% -> 34% | 34% -> 82% |
| v18 | 66% -> 52% | 64% -> 84% |
| v19 | 66% -> 52% | 66% -> 91% |

Item 3's specificity gain was overstated (34->52%, not 27->66%), and **item 4 did
help after all** (principle-connection 84->91%, not the 64->66% we dismissed as
noise). The two levers do different jobs, matching their mechanisms: item 3 is a
specificity lever, item 4 a principle-connection one. Principle-connection at 91%
is well past the 80% bar the architecture review set for "the limiting factor
moves to the model", so its reasoning from 64% needs rereading; specificity at
52% is the genuinely low number, which keeps Change A (compose the missing
best-move clauses) as the top item.

The pattern is validated against the move generator rather than by eyeball, which
is where the first two attempts failed. Over 128,411 legal-move SANs from 60
random games: `\b[a-h][1-8]\b` missed **76.1%** (every piece move); a tighter
lookbehind fix still missed **1.1%** (disambiguated moves — `Nbd7`, `Rae1+`,
`Rgg1`, `R1e2`, forms that really do appear in the coach's output); the shipped
`(?<![a-h][1-8])[a-h][1-8]`, whose single rule is "not the second half of a
coordinate pair", misses **none** and adds no false positives over 41k characters
of real responses. A unit test now asserts the property over every legal move in
a position.

**2. The `threat_present` fact was side-ambiguous and caused false statements.**
It read "there is a live threat against c8" with no owner, and the model read it
as a danger to the student every time: in a position where the student had mate
in one, the coach wrote "your king is vulnerable if you don't act". The report
keys threats by the side making them, so the fact now says "you threaten c8" or
"the opponent threatens c8", preferring the student's own threat as the
actionable one. Regression tests for both directions.

Both are the same failure mode as the `ReviewStats.from_dict` bug: a harness or a
composed field that is quietly wrong is worse than one that is missing, because
it sends the next decision in the wrong direction.

### Metrics audit — principle-connection is saturated; specificity split — 2026-08-11

Prompted by the right question: are these metrics real, or just word matching?
Audited on the 44-turn v19 transcript rather than argued about.

**`principle_connection_rate` is deleted.** All 44 responses contain one of its 22
keywords (which include "material", "capture", "exchange", "threat", "center" —
unavoidable in chess prose), and 95% contain a square, so 95% was the metric's
actual ceiling; it reported 91%, meaning the 120-character proximity window
discriminated almost nothing. A deliberately abstract response passed: "Nf3 is a
good move. In general, development matters a lot in the opening." — exactly the
failure it was built to catch. Nothing was wrong with the code; the idea was wrong.

It was deleted rather than kept with a caveat, because a caveat does not stop the
number being printed, quoted into a review prompt, and cited later by someone who
did not read the caveat — which is precisely how the 64% figure came to anchor an
architecture review. **Consequence: the earlier claim that item 4 improved
principle-connection (84 -> 91%) is withdrawn.** Item 4 is kept on mechanism and
fidelity; its effect on teaching quality is unmeasured, not disproven.

**`specificity_rate` is replaced** by two numbers measured against the prompt the
coach received, because as one number it could rise for a good reason or a bad one:
`composed_fact_rate` (the coach named a square we gave it — the architecture
working as designed) and `unsourced_square_rate` (it named one we never supplied —
where fabrication would show up).

| run | composed_fact_rate | unsourced_square_rate |
|---|---|---|
| v16 | 27% | 2% |
| v17 | 30% | 5% |
| v18 (item 3) | 52% | 5% |
| v19 (item 4) | 52% | 2% |

Item 3's win holds up on the honest metric, and fabrication risk stayed flat — the
gain came from voicing supplied facts.

**Two standing rules, now recorded in code and in the report card.** These rates
are not targets: every one can be improved by padding output with square names,
which would make the coaching worse. And if a measurement cannot fail, delete it
rather than annotate it. Levers are accepted on the fidelity counts (which parse
moves against the real position, so they can say the coach was wrong), direct
reading of the output, and the frontier review's prose critique — which is the real
check on teaching quality precisely because keyword matching against LLM prose
cannot be.

### Coach report card v21 — after the engine fix (2026-08-11)

First run against the fixed engine (BUG-019). The coach now receives real engine
lines on every turn: **19 of 44 prompts had an empty "Top Engine Lines" section,
now 0; rendered lines went 25 -> 131.** Judge score 4.5/10 (noise, per the
measurement philosophy). **Fidelity did not improve**: 5 real violations in both
v20 and v21 (each run also had one phantom `illegal_move`, both since fixed in the
checker). Composition shifted — one fewer `off_menu`, one new `piece_type`, where
the coach invented a capture of its own knight on c3. Five times the grounded
content bought no measured accuracy. Whether it helps teaching is not answerable
from one run.

**Read the review's #1 finding with care.** It leads with "catastrophic
square-naming failure (66% re-use, 0% novel)" and makes it the headline
recommendation — but that is our own `unsourced_square_rate` of 0%, which is the
architecture *working*: we compose facts, the coach voices them. The stats block
labelled the number without saying which direction was good, so the reviewer
inferred a defect. The labelling is fixed. The reasoning built on it should not be
adopted: "let the model name squares it was not given" is the opposite of every
lever that has worked.

The *salvageable* part of that finding is real, though: it cites plies 26, 38, 44,
56 and 58 where the position has concrete nameable threats and the coach talks in
generalities. That is not a model failure, it is **missing composition** — we
supply move-level facts and almost no position-level ones. Which points at the
same place Change A does.

**Action items, in the order I would take them:**

1. **Verify the four fidelity errors the reviewer found by reading that our
   checker missed.** It cites ply 12 ("you captured the opponent's knight on e3"
   — `dxe3` takes a pawn), ply 18 ("the opponent threatened f4" — invented), ply
   32 (a "fork opportunity" unconnected to what `exd4` does), ply 68 ("you
   captured the undefended rook on f4" — the student played `Kxf4`). If ply 12 is
   right, our `piece_type` check has a hole, since that is exactly what it exists
   to catch. Some may be reviewer error — verify each against the board before
   changing anything.
2. **Measure repetition.** The reviewer flagged it twice and independently
   counted it: the closing question is one of three templates, and "can I attack
   an undefended piece?" appears at plies 8, 20, 22, 24, 30, 36, 38, 44, 46, 48,
   50, 68 — roughly half the game. Ten "good move" responses are functionally
   identical. We have no metric for this at all, and unlike the prose metrics it
   is genuinely deterministic and hard to game: n-gram overlap between a turn's
   feedback and the previous turns'. Cheap, and it can fail.
3. **Compose position-level facts, not just move-level ones** (this is Change A
   generalised). Change A extended the *best move* description from 70% to 89%
   coverage. The gap the reviewer points at is different: what is true about the
   POSITION that the student should notice — a hanging piece, a passed pawn, a
   weak square — independent of any move. `feature_facts` already does a little
   of this for the guidance block; it should feed the move-feedback path too.
4. **Phase-specific content.** Raised in every review so far, and now with
   concrete asks: name the opening from ECO ("this is the Italian Game — you are
   targeting f7"), name endgame technique (rook behind the passed pawn, cutting
   off the king, back-rank mate at ply 1003 where the coach said "open file").
   All composable from the board plus data we already ship.
5. **Vary the closing hook by mistake type** — a direct consequence of item 2. Do
   it after 2, so there is a number that can show whether it worked.

Deliberately NOT doing: adding more pedagogy YAML (the previous review's advice,
and the entries already fire on nearly every turn), or asking the model to name
squares it was not given.

### Repetition is now measured (action item 2 from the v21 review) — 2026-08-11

Two deterministic metrics in the report card, no model involved:

- `recycled_phrase_rate` — repeated **wording**: the share of a turn's five-word
  phrases that appeared in an earlier turn. 21-27% across five runs.
- `lesson_concentration_rate` — repeated **meaning**: the share of turns whose
  closing sentence uses one of the three most common content words in the game.
  **82% (v17) -> 57% (v20) -> 68% (v21).**

The second is the one that matters and it was the fourth design. Full account in
`docs/coach-report-card.md`; short version: measuring repeated wording missed the
complaint entirely (the model rewords while teaching the same lesson, overlap with
the reviewer's cited plies 3/12), counting distinct closing sentences saturated at
95-100% and was deleted, and picking the single dominant term overlapped 0/12.
Lesson concentration reproduces the reviewer's hand count and moves across runs.

**Why this was worth doing first:** it is the only metric we have that both moves
and can fail, and it was validated against a count we did not derive ourselves.
Every previous prose metric either saturated or could not be falsified.

**Next, in order:**

1. **Vary the closing hook by mistake type** (item 5, now unblocked). There is a
   number that can show whether it works: `lesson_concentration_rate` should fall
   without `recycled_phrase_rate` rising, and with fidelity flat. Compose the hook
   from the move-effect category rather than letting the model pick a maxim.
2. **Verify the four fidelity errors the reviewer found by reading** that our
   checker missed — especially ply 12, "you captured the opponent's knight on e3"
   where `dxe3` takes a pawn. That is what `piece_type` exists to catch, so if the
   reviewer is right we have a hole in it.
3. **Compose position-level facts**, not just move-level ones — the salvageable
   half of the review's headline finding.
4. **Phase-specific content** (ECO opening names, endgame technique). Raised in
   every review so far.

### Re-judged v21 with the corrected stats block — 2026-08-11

Same transcript, byte-identical coach output, only the metrics block changed. See
the ledger at the top of `docs/coach-report-card.md`.

- The previous review's **weakness #1 became strength #2**. "Catastrophic
  square-naming failure (0% novel)" is now "the 66% board-fact voicing and 0%
  invented squares are exactly right... the floor the product needs, and it
  holds." The complaint was entirely our unlabelled metric. Acting on it would
  have meant letting the model name squares we never gave it.
- **Lesson repetition is now the #1 weakness**, and the reviewer confirms our
  68% figure with its own hand count (undefended piece x10, king safety x12, open
  file x8). A metric we built and a reviewer with no hand in building it agree.
- Score unchanged at 4.5/10.
- It names the **endgame as the biggest phase gap**: "in the endgame your king
  becomes a fighting piece" appears zero times across 18 endgame turns.

**Next: compose the closing hook (ledger row 19).**

The reviewer's own fix is "track the last N principles and prohibit repetition in
the prompt". Take the tracking, drop the prohibition — a negative constraint is
ledger row 2, the lever category that has never worked on this model. Instead
derive the hook from the move-effect category already computed for the clause, so
variety comes from the data.

Accept/reject criteria, decided before running:
- `lesson_concentration_rate` falls from 68% — the point of the change;
- `recycled_phrase_rate` does not rise above ~25% — otherwise we have traded
  repeated meaning for repeated wording;
- fidelity violations stay at 5 or fewer and `unsourced_square_rate` stays under
  5% — accuracy is not for sale;
- then read the output, and only then re-judge.

**After that**, in order: verify the four fidelity errors the reviewer found by
reading that our checker missed (ply 12 "captured the knight on e3" where `dxe3`
takes a pawn is the important one — that is what `piece_type` exists to catch);
compose position-level facts; phase-specific content starting with the endgame,
which is both the biggest phase by turn count and the weakest.

### Composed closing lesson (v22), phase-gating (v23), and switching the judge — 2026-08-12

Ledger rows 19-21 in `docs/coach-report-card.md`.

**v22 — compose the closing lesson from the move's verified effect.** Kept. The
wrong-hook defect is gone: three turns closed with "next time you see a fork
opportunity" about moves that fork nothing, now zero, and no closing sentence
repeats more than twice. `lesson_concentration_rate` 68% -> 66%, which under-reports
the change — it counts shared content words, and the new hooks differ in lesson
while sharing words like "safe" and "square". Fidelity flat at 5.

**v23 — phase-gate the lesson.** Kept (costs nothing, no fidelity cost) but it did
NOT land. In the prompt it works: distinct lessons 11 -> 18, top-3 coverage 57% ->
30%. In the output it does not: only 2 of 18 endgame turns mention a passed pawn,
none mention promotion or the king as a fighting piece, and the judge independently
reports "not one turn mentions king activity as a fighting piece… the framework
doesn't change, only the square names do".

**The lesson from that pair, which is the useful part:** handing the model a FACT
gets voiced faithfully (66% composed-fact rate, 0% invented squares). Handing it a
LESSON gets paraphrased back into its own vocabulary. Facts survive the model,
abstractions do not — the same result as the pedagogy YAML, arriving again in a new
place. So the next attempt at the endgame gap should compose endgame *facts* (this
pawn is passed, this rook is behind it, the enemy king is N squares from it), not
better endgame prose.

**Judge switched to `claude-opus-5`** (was claude-sonnet-4.6) in both review
scripts, with the command now derived from the model so the two cannot disagree.
Sonnet was wrong on 5 of 5 per-ply factual claims when checked against the board;
opus-5 was right on 2 of 2 and found two defects our checker misses.

**Next, in order:**

1. **Ply 28 incoherence**: "your opponent plays e3, winning material because your
   pawn on e3 is undefended" — e3 holds OUR pawn. Find out where that comes from
   (the refutation reply composition is the suspect) and whether the checker can
   catch a claim that the opponent moves onto our own occupied square.
2. **Comparative centrality**: the `king_activity` clause says "closer to the
   centre" from from-square vs to-square, which is misleading when the student's
   own move was MORE central (ply 1002). Either compare against the student's move
   or drop the comparative wording.
3. **Stop leaking harness bookkeeping into coaching.** "The evaluation spread shows
   it was a key decision", "the best move was also your move" on five turns. That
   is eval plumbing in the slot where a chess reason belongs, and it comes from our
   own critical-moment section.
4. **Endgame facts, not endgame prose** (see the lesson above).

### The two per-ply defects, the endgame inversion, and a checker hole — 2026-08-13

Ledger rows 22-25 in `docs/coach-report-card.md`. Items 1 and 2 of the previous
list are done; item 3 is still open and item 4 is unchanged.

**Ply 28 (item 1) — done.** The prompt said "the opponent threatens e3" and the
model read the bare square as a destination, producing a sentence where the
opponent moves onto a square our own pawn occupies. `_describe_target` now resolves
the square against the board and writes "your pawn on e3", with a "the f3 square"
fallback when the square is genuinely empty. Verified in v24.

**Ply 1002 (item 2) — done, but only half the problem was ours.** `_move_effect`
takes the student's move now and suppresses the king-walk clause unless the
alternative really is more central. The clause is gone from the prompt; the model
then wrote "closer to the center" from its own vocabulary with nothing supplied.
Same shape as the phase-gated lesson: withholding an abstraction does not stop the
model reaching for it. Only supplying a competing FACT will.

**The endgame inversion — the structural fix of this round.** The judge's phase
note was that the endgame had the most turns, the worst pedagogy, and it was
backwards: plies 52, 60, 1000, 1002 all hunted for a "safer square" for the king
and ply 76 called a centralized king "exposed". Cause was ours:
`principle.exposed_king` had no phase condition. `GuidanceEntry` gained an optional
`excludes_features` (last, defaulted — as a required field it broke 26 tests),
honoured on all three selection paths (features, ECO, empty-selection fallback) and
validated by the guard against the same closed vocabulary as inclusions. Verified
per-ply, not in aggregate: present in the v24 prompt for all five flagged plies,
absent from all five now, replaced by `passed_pawn_endgame` /
`endgame_king_activity` / `open_file`.

This is a mechanism, not a one-off: any entry that is right in one phase and wrong
in another can now say so.

**Ply 36 — the fidelity checker had a hole shaped like an adjective.** The coach
wrote "capturing the undefended bishop on b4" when `bxc4` took a knight, and
`piece_type` recorded nothing, because `_CAPTURE_CLAIM_RE` needed the piece noun
directly after the article. Up to two intervening words are allowed now. Worth
noting why the gap mattered more than it looked: "undefended" is a word **our own
composer emits constantly** and the coach echoes it, so the blind spot sat exactly
where errors are most likely. The two-word bound keeps it precision-first — "takes
control of the bishop's diagonal" is still not a capture claim — and both
directions are pinned by tests.

**Next, in order:**

1. **Stop leaking harness bookkeeping into coaching** (unchanged from last round).
   "The evaluation spread shows it was a key decision", "the best move was also
   your move" on plies 12, 18, 24, 32, 50 — eval plumbing in the slot where a chess
   reason belongs, from our own critical-moment section.
2. **Endgame facts, not endgame prose**: this pawn is passed, this rook is behind
   it, the enemy king is N squares away. Now that the wrong guidance is excluded
   there is a hole to fill, and the exclusion alone does not teach anything.
3. **The coach does not notice the game is over.** Ply 1003 is `Ra8#` and the
   closing hook asks "does this move buy me time to develop or attack elsewhere?".
   Mate needs its own branch, ahead of every other lesson.
4. **No cumulative diagnosis.** The judge's strongest structural point: the
   student's repeated, game-losing flaw (leaving the c4 bishop loose; walking the
   king) is never named, and "you are a queen up — trade pieces and get the king
   safe" is never said. That is a cross-turn feature we do not have.
5. **Unify the two text parsers** — `verify.py` uses a regex plus
   `board.parse_san`; `coach_review.py` uses a weaker regex. They have drifted once
   already.

### v25 — three sources of one complaint, and two checker false positives — 2026-08-13

Ledger rows 26-27 in `docs/coach-report-card.md`. Score 4.2 -> 4.3 (noise).

**Done this round.** The endgame guidance exclusion worked (16 of 18 endgame plies
-> 0), but the judge repeated the complaint because two other sources were
untouched: the engine's `best_move_idea` label ("king safety — repositioning the
king", on 8 endgame turns, unchanged between v24 and v25) and a hardcoded
"ask yourself: is my king safe?" example in our own PEDAGOGY block, present on
every turn. Both fixed. No substitute label — on 6 of the 8 turns a verified clause
already existed, so the fact stays and only the wrong frame goes.

Also fixed two fidelity false positives: `Be6` used to name the bishop standing on
e6 (our own composer's notation) was read as a move, and a capture claim about the
OPPONENT was judged against the victim of the move WE named.

**Next, in priority order.**

1. **Cross-turn memory — the judge's own highest-leverage recommendation, and the
   biggest thing on this list.** Every lesson today is chosen from the current ply
   alone, so the coach has no idea what it has already taught or what the student
   keeps getting wrong. Concretely, in the v25 game: it recommended a3 against the
   b4 bishop on plies 38, 44, 46 and 48 without ever escalating or noting the
   student was not seeing it; it never connected Ng5 (ply 6) to losing that knight
   (ply 20), or Nxc4 (ply 14) to the identical Nxc4 blunder at ply 34; and it never
   said the one thing that would have saved the game — "you are a queen up from ply
   18, so trade pieces and get the king safe".

   The judge's claim is that this single change also breaks the 57% lesson
   concentration by construction, since a lesson already given becomes ineligible.
   That makes it the first change that would attack repetition at the cause instead
   of measuring it.

   Shape (not designed yet): the coaching call needs a rolling summary of the game
   so far — lessons already delivered, the student's recurring error categories, and
   the running material balance — and lesson selection needs to read it. The
   game-coaching harness already produces exactly this trajectory per turn, so the
   data exists; what is missing is a per-turn *state* threaded into prompt
   construction, plus a decision about what belongs in it (compact facts, per the
   standing finding that facts get voiced and abstractions get paraphrased away).

   **v26 sharpened this into a concrete design.** The judge asked for the same thing
   twice, the second time specifically: a session-level record of lessons already
   delivered plus the student's repeated error, fed into every prompt, with a **hard
   rule that a lesson closed in the last N turns cannot be reused**. Its evidence
   this time was king safety flagged independently at plies 6, 16, 26, 34 and 40,
   never once as "this is the fourth time; the root cause is that you never
   castled". Note that the eligibility rule is a *fact* about the session, not an
   abstraction, so it is the kind of input this model has consistently honoured.

2. **Stop leaking harness bookkeeping into coaching** (carried over). "The
   evaluation spread shows it was a key decision", "the best move was also your
   move" on plies 12, 18, 24, 32, 50 — eval plumbing in the slot where a chess
   reason belongs, from our own critical-moment section. The judge's cheap second
   pick: when the student's move drops ~0cp, endorse it and stop offering a "better"
   move. In v25 that happened on 8 turns and produced vacuous differentiators
   ("Ra4 slightly improves rook activity" when both rooks are on the a-file).
3. **Fabricated refutations are undetected.** At ply 60 the coach claimed the
   opponent could capture a knight on c3; after the student's move Black had no
   legal capture at all. A check is possible — the claim is about the position AFTER
   the student's move, which we can construct — but it needs the post-move board
   threaded into the checker, which today only sees `fen_before`.
4. **Endgame facts, not endgame prose** (carried over). Now more pressing: plies
   1000 and 1002 lose their achievement line entirely because nothing verified is
   available, so there is a hole where the wrong frame used to be.
5. **The coach does not notice the game is over** (carried over). Ply 1003 is `Ra8#`
   and the closing hook asks whether the move buys time to develop.
6. **Unify the two text parsers** (carried over) — `verify.py` uses regex plus
   `board.parse_san`; `coach_review.py` uses a weaker regex.

### The standard itself was audited, blind — 2026-08-13

Full analysis: `docs/coaching-standard-audit.md`. Raw derivations:
`docs/audit/blind-derivation-{a,b}.md`.

Prompted by two owner questions: does the judge ever explain its score, and is the
north star scorable at all? The score had sat at 3.5-4.5 for fifteen changes,
including 4.5 for a lever we reverted as ineffective. Root causes found: the review
task defines only the *endpoints* of the 0-10 scale, so the judge re-anchors the
middle every run (the same defect that made absolute scoring useless in the guidance
A/Bs, fixed there by going pairwise and never fixed here); and the standard is a
composite scored by a single number, so a gain in one part averages away.

The rubric was derived by asking `claude-opus-5` twice, blind to VISION and to the
transcript, via two different framings. Categories came back stable and
rank-consistent, with sources named separately from opinion. **Reordering the action
list below accordingly.**

**Next, in priority order.**

1. **Stop manufacturing fault on moves that were fine.** The blind audit puts this in
   the *harmful* tier and among the three properties it refuses to trade off:
   "manufactures fault on genuinely good moves, including the student's best of the
   game — training them to distrust the instincts you most want reinforced." Measured
   on v26: 21 of 44 turns had a drop under 20cp and **10 of those still stage a
   comparison** — ply 0 `Nf3` at 0cp told `Nc3` is "even better development"; ply 54
   `Rae1+` at 0cp told `Rge1+` "slightly refines rook placement"; ply 1001 `Ra5+` at
   6cp told `Ra4` "better controls the file" when both rooks are on the a-file. The
   report-card judge raised this twice as its cheap secondary pick; an independent
   blind derivation calls it harmful. Cheapest item on this list and the highest
   priority.

   Includes the harness-bookkeeping leak, which is the same defect: "the best move
   was also your move, and the evaluation spread shows it was a key decision" on
   plies 12, 18, 24 — eval plumbing occupying the slot where a chess reason belongs.

2. **Decide whether the north star's end 1 changes — a product decision, not an
   implementation one.** VISION defines end 1 as "a named theme/principle … the words
   the student may already know in the abstract". That is verbatim the audit's **6/10**
   anchor ("invokes a correct general principle but unconditionalized … no trigger
   for when to do it"). Its 8/10 requires the *condition* attached. Same for its
   Diagnosis category, whose 6/10 is "stops at the board level: describes the error
   without naming the thinking failure behind it" — which is precisely what our
   composer produces, deliberately and well.

   So the plateau may be structural: we have been optimising against a definition
   that caps near 6. Two candidate responses — accept the ceiling and say so in
   VISION, or aim at process-level diagnosis (name the *thinking* mistake, not the
   board fact). The second is a substantial change of direction and needs a decision
   before any code.

3. **Rebuild the report-card review task on the derived rubric.** Per-category scores
   with the audit's anchors, fidelity and stance as gates rather than averaged terms
   (a fluent coach that says false things must not score like a dull honest one), and
   per category "what holds this at X, and what would it cost to clear". Then
   re-judge the **existing v26 transcript** under both old and new asks so the series
   has a bridge point and no coach re-run is needed. Prepared but not run.

4. **Give the judge the history it has never had.** Every review so far has seen one
   transcript plus stats — never the ledger, the pattern findings ("facts get voiced,
   abstractions get paraphrased away"; "negative constraints have no measurable
   effect on this model"; "an empty slot is worse than no slot"), the architecture, or
   the model/latency constraints. It has cost us: it once recommended forbidding
   repetition in the prompt, a dead end lever 2 had already closed. Blindness was for
   deriving the standard only; for everything else the judge should get more.

5. **Sharpen the cue, not the shape.** Correction to an earlier assumption: all 44
   turns already use the audit's cue->check form (`next time you see X, ask yourself
   Y`), 30 distinct cues — structurally right. The weakness is cue quality: "next
   time you see a capture" (5x), "an undefended piece" (5x), "a threatened piece" (3x)
   are near-tautological triggers versus the audit's 8/10 example, which names where
   the pattern bites.

6. **Cross-turn memory** — was #1, now third-ish. It survives the audit (accumulation
   across the game is B's #2 property and A's Stream Behaviour), but it is the most
   expensive item and the score evidence is against a large payoff: concentration
   already fell 82% -> 45% with no score movement. Design notes retained in the
   previous entry.

7. **Restraint: stop coaching every move.** Both framings say so independently — "a
   coach that says something substantial forty times has said nothing forty times",
   and restraint on quiet moves is a scorable feature. Today we coach every move with
   a drop over 50cp and the harness coaches all 44. Overlaps item 1 but is a broader
   change (silence as a valid output) and needs its own decision.

8. **Check for forward leakage** (audit property P5, untested here). A coach that
   answers the *live* position produces a student who scores well with the tool and no
   better without it. Our feedback is retrospective by construction, so this is
   probably fine — but it has not been measured.

9. **Endgame facts, not endgame prose** (carried over). Plies 1000/1002 now have no
   achievement line at all, so there is a hole where the wrong frame used to be.
10. **Fabricated refutations are undetected** (carried over). v26 ply 60 claimed the
    opponent could capture a knight when Black had no legal capture at all. Needs the
    post-move board threaded into the checker, which today sees only `fen_before`.
11. **The coach does not notice the game is over** (carried over). Ply 1003 is `Ra8#`.
12. **Unify the two text parsers** (carried over).

### Rubric v2 landed, and it reordered the list again — 2026-08-14

Ledger rows 30-33 in `docs/coach-report-card.md`. Raw reviews in
`docs/audit/rejudge-v26-{v1,v2}.md`.

Audit action items 1 and 3 are **done**: the harmful comparison on moves that were
fine and the eval-bookkeeping leak shipped in `74823fc`, and the per-category rubric
with gates shipped with `scripts/eval_coach_rejudge.py`, which re-judges a saved
transcript with no coach, engine or tunnel — so the judge's *ask* can now be A/B'd
independently of the coach's output.

First result, on the identical v26 transcript: old ask 4.5/10, rubric v2 **2/10**,
pre-gate weighted 4.3. The two agree on quality; the gate is the new information.

**Next, in priority order (the judge's own ordering, with its cost estimates).**

1. **Wire fidelity into the send path.** SMALL-MEDIUM. Verify every claim of the
   form "your/their <piece> on <square>", every capture object, and the check/mate
   label against the board at that ply; on violation regenerate once, then fall back
   to a composed sentence. We already run these checks — `off_menu`, `piece_type`,
   `placement`, `unsound_move` — and only report them to a scoreboard. The judge's
   argument for putting this first: "nothing else you do to this coach can score
   above 2/10 while ply 36 is possible", and the ceiling it unlocks is the 4.3
   already earned.

   Design question to settle first: regenerate-then-fallback changes the shipping
   path, not just the eval harness, and adds a second LLM call on the failing turns
   (latency). Decide whether the fallback is the existing template or a narrower
   composed sentence.

2. **Give the composer the student's failure cause as a first-class field.** MEDIUM.
   Today the prompt orients around the engine's best move, so the model explains why
   THAT move is good and reverse-engineers a lesson from it — the hanging knight at
   ply 20 produced a lesson about attacking b4. Supply what was left undefended,
   which defender moved away, and what the moved piece had been doing; require the
   takeaway to come from that field. The judge notes the engine data is largely
   present already, so this is a composer + prompt change rather than new analysis.

   **This is also backlog item "north star end 1" made concrete** — it is the move
   from board-level description (the audit's 6/10 anchor for Diagnosis) to
   process-level cause (its 8). Doing it answers the product question by
   demonstration rather than by decree, which is the cheaper way round.

3. **Cross-turn memory, now split by cost.** Was #1 under the old ask, then sixth,
   now third and decomposed: a silence rule for moves at or under ~30cp drop and an
   n-gram block on near-duplicate closings are SMALL and fix plies 74/78 (word-for-
   word identical) and 56/58; the recurring-error tally that lets it say "third time
   this bishop has been the cost" is MEDIUM.

4. **Stop attributing intent the coach cannot know.** "aimed to develop your king's
   bishop" (ply 38), "aimed to challenge Black's position" (44), "was a good attempt
   to secure your king" (58). The judge's observation is that the fabrications
   cluster exactly where the model fills a slot it has no data for — the same
   mechanism as the empty achievement slot. Probably SMALL.

5. **Drop the second and third idea in mistake turns.** Plies 22, 34, 42, 60 stack
   the refutation plus a positional aside. Keep the refutation. SMALL.

6. **Check the curated positions use the same code path.** The judge inferred from
   the ply numbering that 1000-1003 come through different code — correct, they are
   the appended curated positions. Confirm they get identical composer output.

7. **Praise as content, not tone.** Thirteen turns open with "Great move —". The
   audit lists it as a defect: at 80 words a compliment costs a fifth of the message
   and buys the variety of feedback the evidence says does not work.

8. **Re-judge the v26 successor under both rubrics** once items 1-2 land, so the v1
   series stays comparable while v2 becomes the working instrument.

Carried over, unchanged in priority: endgame facts rather than endgame prose;
fabricated refutations undetected (v26 ply 60 claimed a capture Black could not
make); the coach not noticing mate at ply 1003; unifying the two text parsers.
