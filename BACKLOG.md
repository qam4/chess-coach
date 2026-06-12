# Backlog

Things we discussed but deliberately deferred. The rule: if we talk
about doing something and don't do it now, it lands here with enough
context to pick up later. Distinct from:

- **IDEAS.md** — open-ended feature ideas / research directions.
- **BUGS.md** — known defects.
- **`.kiro/specs/*/tasks.md`** — committed, scoped work for an active feature.

This file is for "real, agreed, not-yet-scheduled" follow-ups.

## Coaching-eval harness

- **Teaching-oriented `rubric.v2` (north-star alignment).** `rubric.v1`
  is analyst-era: it rewards position triage, and its "use only engine
  data" grounding can *penalize* correct teaching (opening plans, named
  principles, transferable ideas) because that knowledge isn't in the
  engine report. Per `VISION.md`, good coaching is a *bridge*: name the
  principle/theme + a concrete sound action. A v2 rubric should reward
  that bridge — but only once we have a way to keep the "what to focus
  on" half grounded (see pedagogy layer below), so the judge isn't just
  trusting the model's chess.

  **Empirical findings (in-session frontier-judge validation,
  hermes3:8b, 3 positions, Kiro/Claude as judge):** the L1↔L2 gap was
  stark — factual mean 0.17 vs quality 0.54 — confirming v1 is lenient
  toward fluent but position-blind text. Three concrete v1 defects to
  fix in v2:
  - **The `grounded` loophole.** A position-blind, generic response
    (`after_1f6`: "castle / king safety") scored 0.62 because saying
    nothing specific means nothing contradicts the engine, so it banks
    `grounded`(+2) + `actionable` + `level_fit` + `constructive`. Safe
    boilerplate is rewarded. Fix: gate quality on Layer-1 factual /
    coverage, or make `grounded` require a *substantive grounded claim*,
    not merely the absence of a false one.
  - **Hallucination tolerance.** A response with two clear board
    falsehoods (`italian_four_knights`: king "on g1, in the center";
    invented "two pawns on e5 doubled") still scored 0.75, because
    failing `grounded` costs only 2/8 while the other five criteria
    passed. Fix: a hard contradiction should cap/curve the whole score
    (multiplicative, like Layer 1's `factual_score`), not cost a flat
    fraction.
  - **`actionable` rewards any concrete move.** The same response
    passed `actionable` for "castle" even though it ignores the hanging
    e4 it just identified. Fix: tie `actionable` to acting on the
    *key idea*, not to mentioning any move.

- **Pedagogy / curriculum layer (the other scaffold).** The engine
  grounds *what's true about the position*; nothing yet grounds *what's
  worth teaching and how* (the five principles, named patterns, opening
  plans). This is the missing scaffold for end 1 of the teaching bridge
  AND the standard a teaching-eval would grade against. Likely shape: a
  curated knowledge resource (principles keyed to position features,
  plans keyed to ECO codes) injected into both the coach prompt and the
  judge prompt. Connects to IDEAS.md "Structured Learning Path".

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
  - **`kiro-cli`** — drive a frontier model non-interactively from a
    script as the judge backend. Most promising path to automation
    without a paid API key; needs a thin adapter that shapes its I/O to
    the `LLMProvider.generate` contract (prompt in, text out).
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
