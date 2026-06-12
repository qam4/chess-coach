# Requirements Document

## Introduction

chess-coach currently evaluates coaching quality by keyword presence
(`eval_coaching.py`, `eval_models.py`): a response "passes" if it
contains words like "center" or "develop". This measures vocabulary,
not correctness — it cannot tell a true statement from a false one,
and it penalizes good explanations that use different words. The
factual checks that *can* tell true from false (`check_piece_hallucinations`,
`check_move_validity` in `probe_llm_chess.py`) exist but are
human-review-only and never feed a score.

This feature builds a real evaluation harness in three layers:

1. **Objective, engine-grounded checks** — verify the model's claims
   against the engine's structured report (the oracle). Hallucination
   rate, illegal-move rate, key-fact coverage, eval-direction
   correctness. Fully automated, no model judgment, no cost.
2. **Frontier LLM-as-judge** — a strong model scores coaching quality
   (prioritization, pedagogy, level-appropriateness) against a fixed
   rubric, grounded in the engine report so the judge never relies on
   its own fallible board reading. Run on demand.
3. **Human calibration** — a one-time human-rated seed set anchors the
   rubric and validates that the judge agrees with human judgment.

The result turns "how much does the LLM know about chess and coaching"
into two trustworthy numbers per model: a **factual-accuracy score**
(objective) and a **coaching-quality score** (judged, calibrated).

## Glossary

- **Eval_Harness**: The overall system that runs models against a
  benchmark and produces scores.
- **Benchmark_Position**: An annotated test position — FEN, skill
  level, phase, and the ground-truth coaching points a correct
  response should cover.
- **Engine_Report**: The `PositionReport` / `ComparisonReport` from the
  Blunder coaching engine — the authoritative ground truth for a
  position (eval breakdown, hanging pieces, threats, tactics, top
  lines).
- **Objective_Check**: A deterministic check of a coaching response
  against the Engine_Report or board state. No LLM, no human.
- **Factual_Accuracy_Score**: Aggregate of Objective_Check results for
  a response (hallucinations, illegal moves, coverage, eval direction).
- **Judge**: A frontier LLM that scores coaching quality against the
  Judge_Rubric, given the Engine_Report as ground truth.
- **Judge_Rubric**: The fixed set of criteria the Judge applies
  (key-idea identification, causal explanation, actionable advice,
  level-appropriateness, grounding, tone).
- **Coaching_Quality_Score**: Aggregate of Judge verdicts for a
  response.
- **Seed_Set**: A small set of responses rated by a human, used to
  calibrate the Judge and author the Judge_Rubric.
- **Judge_Agreement**: The measured concordance between Judge scores
  and human Seed_Set ratings.
- **Scoreboard**: The cross-model, cross-position summary of
  Factual_Accuracy_Score and Coaching_Quality_Score.

## Requirements

### Requirement 1: Annotated benchmark position set

**User Story:** As a developer evaluating chess-coach, I want a set of
positions annotated with the coaching points a correct response should
cover, so that scoring can measure whether the model found what
matters rather than whether it used certain words.

#### Acceptance Criteria

1. THE Eval_Harness SHALL define a set of Benchmark_Positions, each with
   a FEN, skill level, game phase, and a list of ground-truth coaching
   points.
2. EACH Benchmark_Position SHALL record the coaching points as
   structured, checkable assertions where possible (e.g.
   `hanging_piece: e4`, `eval_direction: white_better`,
   `phase: endgame`) rather than free text.
3. THE Eval_Harness SHALL cover opening, middlegame, and endgame phases
   and beginner, intermediate, and advanced levels across the set.
4. THE Benchmark_Positions SHALL be stored as data (not embedded in a
   single script) so the set can grow without code changes.
5. WHERE a position has a known engine report, THE Eval_Harness SHALL
   allow the ground-truth coaching points to be derived from or checked
   against that report.

### Requirement 2: Objective engine-grounded checks (Layer 1)

**User Story:** As a developer, I want every coaching response checked
against the engine's ground truth automatically, so that factual
errors are caught without a human or a judge model.

#### Acceptance Criteria

1. THE Eval_Harness SHALL detect piece-placement hallucinations in a
   coaching response by verifying "piece on square" claims against the
   board state.
2. THE Eval_Harness SHALL detect illegal moves mentioned in a coaching
   response against the legal moves of the position.
3. THE Eval_Harness SHALL detect eval-direction errors — a response
   that claims one side is better when the Engine_Report says the
   opposite.
4. THE Eval_Harness SHALL measure key-fact coverage — whether the
   response mentions the checkable ground-truth coaching points for the
   position (e.g. the actual hanging piece the engine found).
5. THE Eval_Harness SHALL compute a Factual_Accuracy_Score per response
   from the Objective_Check results.
6. THE Objective_Checks SHALL run without any LLM judge or human input.

### Requirement 3: Frontier LLM-as-judge (Layer 2)

**User Story:** As a developer, I want a strong model to score coaching
quality against a fixed rubric while being grounded in the engine
data, so that the subjective "is this good coaching" dimension is
measured consistently and at scale without the judge inventing chess
facts.

#### Acceptance Criteria

1. THE Judge SHALL receive the Engine_Report for the position as
   authoritative ground truth in its prompt.
2. THE Judge SHALL be instructed to grade the coaching response against
   the Engine_Report and to flag any response claim that contradicts
   the Engine_Report.
3. THE Judge SHALL be instructed NOT to rely on its own chess analysis
   for factual claims — only the provided Engine_Report.
4. THE Judge SHALL score the response against each criterion in the
   Judge_Rubric and return a structured (machine-parseable) verdict per
   criterion plus a short rationale.
5. THE Judge SHALL run at a deterministic temperature (0) for
   reproducibility.
6. THE Eval_Harness SHALL record the judge model identifier and the
   Judge_Rubric version alongside every Coaching_Quality_Score.
7. THE Judge endpoint SHALL be pluggable — usable against any
   OpenAI-compatible frontier endpoint (direct API, the FITT gateway's
   frontier alias, or an MCP/CLI bridge) without changing the harness
   logic.
8. WHERE pairwise comparison is used (model A vs model B on the same
   position), THE Eval_Harness SHALL randomize presentation order to
   mitigate position bias.

### Requirement 4: Judge rubric

**User Story:** As a developer, I want the judge to apply a fixed,
explicit rubric, so that scores are consistent across runs and
diffable when I change a prompt.

#### Acceptance Criteria

1. THE Judge_Rubric SHALL express each criterion as a binary or
   anchored check (e.g. "names at least one key idea: yes/no") rather
   than an open-ended numeric rating.
2. THE Judge_Rubric SHALL include criteria for: identifying the key
   idea(s), explaining why it matters, giving actionable advice,
   level-appropriateness (no engine jargon for beginners), grounding
   (no contradictions with the Engine_Report), and constructive tone.
3. THE Judge_Rubric SHALL be versioned, and the version SHALL be
   recorded in results.
4. THE Coaching_Quality_Score SHALL be computable deterministically
   from the per-criterion verdicts.

### Requirement 5: Human calibration (Layer 3)

**User Story:** As a developer, I want to rate a small seed set by hand
and confirm the judge agrees with me, so that I can trust the judge's
scores on positions I haven't reviewed.

#### Acceptance Criteria

1. THE Eval_Harness SHALL produce a human-reviewable artifact (the
   generated coaching responses plus the Engine_Report) for a Seed_Set
   of positions.
2. THE Eval_Harness SHALL allow a human to record per-response ratings
   for the Seed_Set against the Judge_Rubric criteria.
3. THE Eval_Harness SHALL compute Judge_Agreement — the concordance
   between Judge verdicts and human ratings on the Seed_Set.
4. WHEN Judge_Agreement is below a documented threshold, THE harness
   SHALL surface this so the rubric or judge can be revised before
   trusting automated scores.

### Requirement 6: Multi-model scoreboard and reproducibility

**User Story:** As a developer, I want to run the benchmark across
multiple models and compare their factual accuracy and coaching
quality side by side, so that I can choose a model and detect
regressions after prompt changes.

#### Acceptance Criteria

1. THE Eval_Harness SHALL run the benchmark across multiple models in
   one invocation (local Ollama and remote endpoints).
2. THE Eval_Harness SHALL produce a Scoreboard summarizing
   Factual_Accuracy_Score and Coaching_Quality_Score per model.
3. THE Eval_Harness SHALL persist full results (per position, per
   model: response, objective checks, judge verdict) to disk for later
   inspection.
4. THE Eval_Harness SHALL record the run configuration — models, judge
   model, rubric version, benchmark version, timestamp — with the
   results.
5. THE Eval_Harness SHALL be runnable with Layer 1 only (no judge, no
   cost) for fast regression checks, and with Layer 1 + Layer 2 for a
   full quality run.

### Requirement 7: Reuse existing infrastructure

**User Story:** As a developer, I want the harness to build on the
existing engine, provider, and checker code, so that I am not
maintaining two parallel implementations.

#### Acceptance Criteria

1. THE Eval_Harness SHALL obtain Engine_Reports via the existing
   `CoachingEngine` interface.
2. THE Eval_Harness SHALL generate coaching responses via the existing
   prompt builders (`build_rich_coaching_prompt`,
   `build_rich_move_evaluation_prompt`) and LLM provider abstraction.
3. THE Eval_Harness SHALL reuse the existing factual checkers
   (`check_piece_hallucinations`, `check_move_validity`), extending
   them rather than duplicating them.
4. THE Judge SHALL be reachable through the existing `LLMProvider`
   abstraction (the `openai_compat` provider) so no new HTTP client is
   introduced.
