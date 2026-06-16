# Backlog

Things we discussed but deliberately deferred. The rule: if we talk
about doing something and don't do it now, it lands here with enough
context to pick up later. Distinct from:

- **IDEAS.md** — open-ended feature ideas / research directions.
- **BUGS.md** — known defects.
- **`.kiro/specs/*/tasks.md`** — committed, scoped work for an active feature.

This file is for "real, agreed, not-yet-scheduled" follow-ups.

## Coaching-eval harness

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

- **Who calibrates teaching quality?** Layer 3 assumes a human who can
  rate coaching. The product owner is the *student*, not a chess expert,
  so they can't be that human for the teaching axis. Calibration needs
  chess authority (strong player / instructional canon / frontier model
  as proxy). True-north validation is **student outcomes** (does the
  player improve), not expert prose-rating — a much bigger build, ties
  to progress tracking.

- **Pairwise `--pairwise` CLI flag.** The pairwise judging library
  (`pairwise_compare`, randomized+recorded order, Property 6) is built
  and tested, but not exposed as an `eval_run.py` CLI mode. Optional
  per the design; wire it when we actually want A-vs-B model runs.
  (Tracked as tasks.md 6.3 `[~]`.)

- **Hallucination detector misses relational falsehoods.** It catches
  "piece on square X" placement claims, but not false claims like
  "you've developed both bishops" when none are developed (seen live
  from hermes3:8b). The judge's `grounded` criterion is the backstop;
  extending the objective check to catch development/possession claims
  is a future improvement.

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
