# Tasks

Implementation order keeps the harness runnable at every step and
front-loads the layers that need no frontier tokens (benchmark →
Layer 1 → runnable scoreboard → seed generation), then wires the
judge (Layer 2) and calibration (Layer 3).

## Task 1: Benchmark data model + loader

- [x] 1.1 Create `src/chess_coach/eval/__init__.py` and
      `src/chess_coach/eval/benchmark.py` with `GroundTruthPoint` and
      `BenchmarkPosition` dataclasses (frozen).
- [x] 1.2 Implement `load_benchmark(path)` reading `data/eval/positions.yaml`
      with fail-fast validation (clear error on the offending entry).
- [x] 1.3 Author `data/eval/positions.yaml` — seed it from the existing
      `POSITION_TESTS`/`MOVE_TESTS` in `eval_coaching.py`, converting
      `expect_keywords` into structured `GroundTruthPoint`s where
      possible (hanging_piece, eval_direction, phase). Cover
      opening/middlegame/endgame × beginner/intermediate/advanced.
- [x] 1.4 Unit test: loader parses the sample, rejects a malformed entry.
- Requirements: 1.1, 1.2, 1.3, 1.4, 1.5

## Task 2: Layer 1 — objective checks

- [x] 2.1 Create `src/chess_coach/eval/objective.py`. Move
      `check_piece_hallucinations` and `check_move_validity` here from
      `probe_llm_chess.py`; re-import them in the probe so it keeps
      working (no duplication).
- [x] 2.2 Add `check_eval_direction(response, report)` — does the
      response's stated advantage match the sign of `report.eval_cp`?
- [x] 2.3 Add `check_coverage(response, position)` — fraction of the
      position's checkable `GroundTruthPoint`s referenced in the text.
- [x] 2.4 Implement `evaluate_objective(response, report, position) ->
      ObjectiveResult` with the weighted `factual_score` (hallucination
      and illegal-move hard caps below pass threshold).
- [x] 2.5 Tests: P1 (hallucination caps score), P2 (runs with no LLM),
      coverage edge cases (all hit / none hit / empty points).
- Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 7.3

## Task 3: Scoring + scoreboard + run recording

- [x] 3.1 Create `src/chess_coach/eval/scoring.py` with `ResponseEval`
      aggregation and a `Scoreboard` (per-model factual + quality
      summaries).
- [x] 3.2 Implement run-config capture (models, judge model, rubric
      version, benchmark version, timestamp) and a `persist_results()`
      that writes full per-position/per-model JSON + a human-readable
      summary.
- [x] 3.3 Tests: P7 (run config persisted), scoreboard aggregation
      (all-pass, all-fail).
- Requirements: 6.2, 6.3, 6.4

## Task 4: `eval_run.py` orchestrator — Layer 1 path

- [x] 4.1 Create `scripts/eval_run.py`: load benchmark, start
      `CoachingEngine`, for each model build the rich prompt via the
      existing prompt builders and the `LLMProvider` abstraction,
      generate the response.
- [x] 4.2 Run Layer 1 on every response; aggregate to a `Scoreboard`;
      persist. Multi-model in one invocation (local + remote endpoints).
- [x] 4.3 Handle per-position generation failures (record score 0,
      continue) and engine-unavailable (abort with clear message).
      Added a fast `coaching_available` guard so a non-coaching engine
      aborts instantly instead of timing out per position.
- [x] 4.4 `--models`, `--positions`, `--out` flags (plus `--base-url`,
      `--engine-timeout`, `--depth`, `--benchmark`). No judge yet —
      this is the fast, free regression path.
- [~] 4.5 Smoke test: validated end-to-end via a stub-engine +
      stub-provider integration test (`tests/test_eval_run.py`). A
      *live* engine run is blocked on this dev box — the local Windows
      Blunder build reports `coaching_available=False`; needs the
      coaching-capable Linux/EC2 build. Author to run there.
- Requirements: 6.1, 6.5, 7.1, 7.2, 7.4

## Task 5: Layer 2 — judge rubric + prompt + parser

- [x] 5.1 Author `data/eval/rubric.v1.yaml` — the six criteria
      (key_idea, explains_why, actionable, level_fit, grounded,
      constructive) with descriptions and weights.
- [x] 5.2 Create `src/chess_coach/eval/judge.py`:
      `build_judge_prompt(response, report, position, rubric)` —
      includes engine report as ground truth, the grounding
      instruction (do not use own chess analysis), the rubric, and the
      JSON output contract.
- [x] 5.3 Implement `parse_verdict(text, rubric) -> JudgeVerdict` —
      tolerant of trailing prose around the JSON (common frontier
      quirk); raises a clear error if a criterion is missing.
- [x] 5.4 Implement `judge_response(...)` using the `LLMProvider`
      abstraction at temperature 0; retry once on parse failure; record
      judge model + rubric version. `grounded` fails iff
      `contradictions` non-empty.
- [x] 5.5 Tests: P3 (prompt contains report + grounding), P4 (parse
      complete-or-error, incl. trailing prose), P5 (grounded ↔
      contradictions).
- Requirements: 3.1–3.7, 4.1, 4.2, 4.3, 4.4, 7.4

## Task 6: Wire Layer 2 into the run + pairwise mode

- [x] 6.1 Add `--judge-model` (+ `--judge-provider`, `--judge-base-url`,
      `--judge-api-key`) to `eval_run.py`. When set, run the judge per
      response and fill `ResponseEval.judge`. Extended
      `OpenAICompatProvider` with optional Bearer auth so the judge can
      reach the FITT gateway / frontier APIs.
- [x] 6.2 Judge endpoint unreachable / unparseable → record Layer 2 as
      unavailable for that response (judge stays None); Layer 1 scores
      still stand. Never aborts the run.
- [~] 6.3 Pairwise: `pairwise_compare` (randomized + recorded slot
      order), `build_pairwise_prompt`, `parse_pairwise` implemented and
      tested (Property 6). The `--pairwise` *CLI flag* on `eval_run` is
      deferred — design marks pairwise optional; the library + property
      test are in place for when it's wired.
- [x] 6.4 Extend the scoreboard with `CoachingQualityScore` columns
      (already present: `qual` column, `quality_mean`).
- [x] 6.5 Tests: P6 (pairwise order randomized + recorded), integration
      run with a **mock judge** (canned JSON) — judge sets verdicts,
      judge failure leaves Layer 1 intact, judge skips generation
      failures. Plus judge-auth header tests.
- Requirements: 3.8, 6.2, 6.5

## Task 7: Layer 3 — human calibration

- [x] 7.1 Create `scripts/eval_calibrate.py`. `generate` subcommand:
      reads a judged `results.json` and emits a markdown review
      artifact (engine findings + coaching text + rubric checklist per
      response) plus a ratings template. Pure post-processing — no
      engine/LLM calls (judging already happened in the eval run).
- [x] 7.2 `agreement` subcommand reads human ratings from a YAML
      sidecar (`load_seed_ratings`), keyed by `position::model`.
- [x] 7.3 `agreement` extracts the judge's per-criterion verdicts from
      results.json, computes per-criterion + overall agreement, and
      flags (exit non-zero) when below the 80% threshold.
- [x] 7.4 Tests: agreement computation (perfect → 100%, total
      disagreement → 0%, known one-criterion divergence → expected,
      configurable threshold, shared-keys-only, no-overlap), ratings
      I/O + template round-trip. Validated live end-to-end: judged run
      (hermes3:8b coached, qwen3:14b judge) → `generate` produced the
      review + template.
- Requirements: 5.1, 5.2, 5.3, 5.4

## Task 9: Benchmark annotation guard (harden the benchmark)

Motivation: during the first live run, 3 of 10 seed positions had
annotations that contradicted the engine oracle (wrong eval
direction, wrong hanging square) and were scoring correct models as
wrong — a direct Requirement 1.5 violation. As the benchmark grows,
hand-authored annotations will drift from the engine again. This
task makes the drift mechanically detectable.

- [x] 9.1 `scripts/eval_check_annotations.py`: for every
      `BenchmarkPosition`, fetch the engine report and compare the
      structured annotations against it —
      `eval_direction` vs the sign of `eval_cp` (with the equal band),
      `hanging_piece` square vs the report's hanging pieces,
      `tactic` type vs the report's tactics. Print a per-position
      PASS/MISMATCH report; exit non-zero if any mismatch. Logic lives
      in `src/chess_coach/eval/annotations.py` (pure + testable).
- [x] 9.2 Treat `free`/`phase` points as un-checkable (skip) — only
      the engine-verifiable kinds are compared.
- [x] 9.3 Tests with a stub report: a matching annotation passes, a
      flipped eval_direction / wrong hanging square / wrong tactic is
      flagged. Verified live: all 9 benchmark positions agree.
- [ ] 9.4 (Optional) wire as a `--check-annotations` preflight in
      `eval_run.py` that warns before a scored run.
- Requirements: 1.5

## Task 8: Documentation + cleanup

- [x] 8.1 Add a `docs/evaluation.md` describing the three layers, how to
      run each, and how to add a benchmark position.
- [x] 8.2 Point README dev section + IDEAS.md at the new harness; mark
      `eval_coaching.py` / `eval_models.py` as superseded (deprecation
      note in each docstring).
- [x] 8.3 Full check: `pytest` (297 pass), `mypy src/chess_coach/eval`
      clean, `ruff check src tests` + `ruff format --check` clean.
      (Note: whole-package `mypy src` shows pre-existing `rich`
      import-not-found in `cli.py` from the typecheck env missing the
      `rich` dep — logged in BACKLOG.md, not a harness defect.)

## Definition of done

- Layer 1 produces a factual-accuracy scoreboard across models with no
  frontier tokens.
- Layer 2 produces a coaching-quality score grounded in the engine
  report, against a versioned rubric, via a pluggable endpoint.
- Layer 3 reports judge-vs-human agreement on a seed set.
- All property tests (P1–P7) pass at ≥100 iterations; unit +
  integration (mock judge) green.
- `pytest`, `mypy`, `ruff` clean.
