# Requirements Document

## Introduction

chess-coach is built on top of an LLM that the project does not control and
that **will change** — a new Ollama model, a swapped default, a quantization,
a remote endpoint. We cannot know in advance how a given model will behave on
the coaching task. This session proved the point the hard way: by hand we
discovered that `gemma4:12b-it-qat` can't make use of the pedagogy guidance
while `qwen3:14b` significantly can, that models misread moves given as raw
UCI, and that some models hallucinate when grounding is thin. Each of those
was a manual detective exercise that ended in a config decision.

This feature turns that manual detective work into a **repeatable, automated
profiler**: point it at a model, run the few checks that actually decide a
config setting, and get back a short per-dimension report plus a recommended
config block. It reuses the eval harness that already exists
(`scripts/eval_run.py` factual scoring and the move-feedback pairwise A/B);
the profiler is a thin layer that runs those, reads the numbers, and maps them
to configuration suggestions.

The design borrows the hard-won shape of FITT's model-capability work
(`gateway/src/gateway/capability_profile.py`, `docs/choosing-a-model.md`) but
deliberately keeps only the parts that earn their keep here. We are NOT
building baselines, diffing, or a declared-vs-measured data model in v1.

### Scope

- **In scope (v1):** an on-demand `profile` command that measures a model on a
  small, fixed set of coaching dimensions, prints the per-dimension facts, and
  prints a recommended config block the operator can paste in.
- **Out of scope (later, if missed):** storing profiles and **diffing** a new
  profile against a known-good baseline (FITT's regression-catcher); a
  declared-facts catalog layer; auto-applying the recommendation to config.

## Guiding principles (adopted from FITT, kept because they are cheap)

1. **Facts, not verdicts.** Report raw numbers (`factual=0.30`, `p50=7.2s`) and
   let the operator judge them against what the model is *for*. Do not hardcode
   "slow = bad" or collapse a model to a single tier.
2. **Capability and cost stay separate.** A dimension's quality score and its
   latency are reported side by side, never blended into one number.
3. **Operator-in-the-loop.** The profiler *recommends* config; it never writes
   or auto-applies it. A noisy, sample-limited measurement must not silently
   steer live behaviour.
4. **Dimensions are a menu, not a schema.** A profile is a *list* of dimension
   results, so adding a dimension later is appending an entry, not a redesign.
5. **Model-agnostic.** Nothing in the profiler branches on a model name.

## Glossary

- **Profiler**: The system this feature delivers — runs the dimension checks
  for one model and produces a Capability_Profile plus a Config_Recommendation.
- **Capability_Profile**: The result of one profiling run — a list of
  Dimension_Results for a single model, with a timestamp.
- **Dimension_Result**: One measured coaching dimension for the model: a name,
  a quality measure (or pass/fail), a latency measure where relevant, the
  sample size, and free-text notes.
- **Config_Recommendation**: The suggested config settings derived from the
  Dimension_Results (e.g. `guidance: on`, `template_only: false`), with a
  one-line reason each. Advisory only.

## Requirements

### Requirement 1 — Profile a model on demand

**User Story:** As the operator choosing or swapping the coaching model, I want
to run one command that profiles a model, so that I get evidence-based config
settings instead of guessing.

#### Acceptance Criteria

1. WHEN the operator runs the profiler against a model identifier and endpoint,
   THE Profiler SHALL run the configured dimension checks and produce one
   Capability_Profile.
2. THE Profiler SHALL reuse the existing eval harness components for the
   measured dimensions rather than reimplementing scoring.
3. WHEN a dimension check cannot run because the model is unreachable, THE
   Profiler SHALL stop after the reachability dimension and report the model as
   unusable, rather than emitting misleading downstream results.
4. THE Capability_Profile SHALL record the model identifier and a timestamp.

### Requirement 2 — Reachability / coachability gate (cheapest first)

**User Story:** As the operator, I want the cheapest check to run first and
fail fast, so that a bad candidate does not waste a full profiling run.

#### Acceptance Criteria

1. THE Profiler SHALL first verify the model endpoint is reachable and the
   model is loaded, distinguishing "endpoint unreachable" from "model not
   loaded".
2. WHEN reachable, THE Profiler SHALL confirm the model can produce a non-empty
   grounded coaching generation before running the more expensive dimensions.
3. IF reachability or basic generation fails, THEN THE Profiler SHALL emit a
   Dimension_Result marking it failed and SHALL NOT run the remaining
   dimensions.

### Requirement 3 — Factual grounding dimension

**User Story:** As the operator, I want to know whether a model hallucinates on
coaching, so that I can decide whether to trust the LLM or fall back to
templates.

#### Acceptance Criteria

1. THE Profiler SHALL measure factual grounding by running the existing
   objective/factual eval over a fixed set of positions and recording the mean
   factual score and the hallucination/illegal-move counts.
2. THE factual Dimension_Result SHALL report the raw score and counts as facts;
   it SHALL NOT collapse them to a pass/fail without surfacing the numbers.
3. WHEN the factual score is below a configurable threshold OR hallucinations
   are present, THE Config_Recommendation SHALL suggest `template_only: true`
   (prefer the deterministic template path) with the measured reason.

### Requirement 4 — Guidance-uptake dimension

**User Story:** As the operator, I want to know whether the pedagogy guidance
actually improves a given model's teaching, so that I can turn guidance on only
where it helps.

#### Acceptance Criteria

1. THE Profiler SHALL measure guidance uptake by running the move-feedback
   pairwise A/B (guidance off vs on) and recording the on-win-rate and its
   significance.
2. WHEN guidance ON wins materially more than off (above a configurable
   win-rate threshold), THE Config_Recommendation SHALL suggest `guidance: on`;
   otherwise it SHALL suggest `guidance: off`, each with the measured reason.
3. THE guidance Dimension_Result SHALL report the win-rate and the
   decisive/total counts as facts.

### Requirement 5 — Latency dimension

**User Story:** As the operator, I want to know how fast a model responds when
warm, so that I can judge interactive (play) vs. analysis suitability myself.

#### Acceptance Criteria

1. THE Profiler SHALL measure per-call latency on a warm model and report at
   least a representative central value (e.g. p50) over the sampled calls.
2. THE latency Dimension_Result SHALL be reported as a fact alongside, never
   blended into, the quality dimensions.
3. THE Profiler SHALL NOT assign a pass/fail verdict to latency.

### Requirement 6 — Report and config recommendation

**User Story:** As the operator, I want a short readable report plus a config
block I can paste in, so that acting on the profile is trivial and I stay in
control.

#### Acceptance Criteria

1. THE Profiler SHALL print a human-readable per-dimension report showing each
   Dimension_Result's facts.
2. THE Profiler SHALL print a Config_Recommendation as a config snippet with a
   one-line reason per suggested setting.
3. THE Profiler SHALL NOT modify any config file; applying the recommendation
   is a manual operator action.
4. THE Profiler SHALL write the Capability_Profile to an output file so the run
   is recorded.

### Requirement 7 — Extensible, pure core

**User Story:** As a developer, I want adding a new dimension to be cheap and
the core to be testable without a live model, so that the profiler does not rot.

#### Acceptance Criteria

1. THE Capability_Profile and its rendering SHALL treat dimensions as a list,
   so adding a dimension is appending a Dimension_Result without changing the
   data model.
2. THE data model, the threshold→recommendation mapping, and the rendering
   SHALL be a pure layer, unit-testable with constructed Dimension_Results and
   no live model or network.
3. THE live producer (running the evals, reading the numbers) SHALL be a thin
   layer on top of the pure core.
