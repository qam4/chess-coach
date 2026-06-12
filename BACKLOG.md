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

- **Benchmark size.** Only 10 seed positions today. Grow toward
  20-40 across phases/levels once the annotation guard (Task 9) makes
  authoring safe.

## Environment / tooling

- **Broken repo `.venv`.** The checked-out `.venv/` has no pip and no
  test deps; work is happening in the tox `py3` env (with an editable
  install added for the new `eval` package). Clean up or document the
  intended dev-env setup.

- **`typecheck` tox env is missing `rich`.** Running `mypy src` in the
  tox typecheck env reports `import-not-found` for `rich.console` /
  `rich.panel` in `cli.py`, which cascades into a spurious "unused
  type: ignore" at `cli.py:374`. Pre-existing, not a code defect —
  add `rich` to the typecheck env's deps (or mypy overrides) so the
  whole-package `mypy src` is clean. The eval package itself is
  rich-free and type-checks clean.
