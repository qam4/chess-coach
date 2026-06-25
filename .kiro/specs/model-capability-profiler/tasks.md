# Implementation Plan

Build the pure core first (fully testable, no live model), then the thin
producer that reuses the existing eval harness, then wire output. Cheapest-
first so a bad model fails fast. Property/unit tests woven in per task.

Conventions: Python 3.11, `src/` layout, `uv run pytest` / `uv run mypy src`
(strict) / `uv run ruff check src tests` + `ruff format`. Offline/local; no new
runtime dependencies. Reuse existing eval components — do not reimplement
scoring.

## Tasks

- [x] 1. Pure core: data model + JSON persistence
  - [x] 1.1 Create `src/chess_coach/eval/profile.py` with frozen dataclasses
        `DimensionResult`, `CapabilityProfile`, `ConfigSuggestion`,
        `ConfigRecommendation`, `ProfileThresholds`. Dimensions are a `list`
        (Req 7.1). Keep `metrics` (quality facts) and `latency_s` (cost)
        separate fields (Req 5.2, principle 2).
  - [x] 1.2 Add `profile_to_dict` / `from_dict` round-tripping for
        `CapabilityProfile` so a run can be written to and re-read from JSON.
  - [x] 1.3 Unit tests: dataclass construction + JSON round-trip equality.
  - _Requirements: 1.4, 5.2, 7.1, 7.2_

- [x] 2. Pure core: threshold → recommendation mapping
  - [x] 2.1 Implement `recommend(profile, thresholds) -> ConfigRecommendation`:
        factual `< factual_min` OR hallucinations `> 0` ⇒
        `coaching.template_only: true` (else false); guidance win-rate
        `>= guidance_win_rate_min` ⇒ `coaching.guidance: on` (else off);
        latency ⇒ NO suggestion (fact only); reachability fail ⇒ a single
        "model unusable" suggestion. Each suggestion carries a reason citing
        the measured number.
  - [x] 2.2 Unit tests for every branch: low factual → template_only;
        hallucinations present → template_only; win-rate above/below threshold
        → guidance on/off; latency never yields a suggestion (Req 5.3);
        reachability-fail short-circuit.
  - _Requirements: 3.3, 4.2, 5.3, 7.2_

- [x] 3. Pure core: rendering
  - [x] 3.1 Implement `render_profile` (per-dimension facts: name, status,
        metrics, latency side-by-side) and `render_recommendation` (config
        snippet + one-line reason per setting).
  - [x] 3.2 Unit tests: rendered report contains each dimension's facts;
        recommendation renders as a pasteable config block with reasons.
  - _Requirements: 6.1, 6.2_

- [x] 4. Refactor move-feedback pairwise into a reusable function
  - [x] 4.1 Extract the per-scenario generate→judge→majority loop in
        `scripts/eval_move_feedback_pairwise.py` into an importable function
        (e.g. `run_move_feedback_pairwise(...) -> PairwiseSummary`) so both the
        existing script and the profiler call the same code (no duplication).
  - [x] 4.2 Confirm the existing pairwise tests still pass; add a focused test
        for the extracted function with a stub judge + mocked engine/model.
  - _Requirements: 1.2, 4.1_

- [x] 5. Producer: dimension runners (thin, reuse harness)
  - [x] 5.1 `reachability`: `OllamaProvider.check_status` (unreachable vs
        not-loaded) + one smoke `generate`; emit a `DimensionResult`; on
        failure, short-circuit the run (Req 2.3).
  - [x] 5.2 `factual`: run the existing objective/factual eval over a fixed
        position set; record mean factual + hallucination/illegal counts into a
        `DimensionResult`.
  - [x] 5.3 `guidance`: call the extracted move-feedback pairwise function;
        record on-win-rate + decisive/total + significance.
  - [x] 5.4 `latency`: time N warm `generate` calls (warm first); record p50 as
        an `info` dimension.
  - _Requirements: 2.1, 2.2, 3.1, 4.1, 4.3, 5.1_

- [x] 6. Producer entry point + output
  - [x] 6.1 Create `scripts/profile_model.py`: args (model, base-url, judge
        config mirroring the pairwise script, thresholds with defaults, out
        path). Run dimensions cheapest-first, assemble `CapabilityProfile`,
        call `recommend`.
  - [x] 6.2 Print `render_profile` then `render_recommendation`; write
        `output/profile_<model>.json`. Do NOT modify any config file (Req 6.3).
  - [x] 6.3 Light integration test: mocked unreachable model → run stops after
        reachability and reports unusable (no downstream dimensions).
  - _Requirements: 1.1, 1.3, 6.1, 6.2, 6.3, 6.4_

- [ ] 7. Docs + final checks
  - [ ] 7.1 Document the profiler in `docs/` (what it measures, how to run it
        under kiro-monitor, how to read the report, that the recommendation is
        advisory). Note the deferred baseline/diff and declared-facts ideas.
  - [ ] 7.2 Full green: `uv run pytest`, `uv run mypy src`, `uv run ruff check
        src tests` + `ruff format --check`. Update BACKLOG (mark the profiler
        built; note deferrals).
  - _Requirements: all (validation)_

## Notes

- The pure core (tasks 1–3) is the primary test surface and has no live-model
  dependency; the producer (5–6) reuses already-tested eval code.
- Run order is the gate order: reachability → factual → guidance (expensive,
  ~30 min) → latency. The profiler is a kiro-monitor-friendly script, not a
  blocking CLI command.
- Deferred (append-only when missed): stored baselines + profile diffing;
  declared-facts catalog dimensions; instruction-following dimension; a
  `chess-coach profile` CLI wrapper.
