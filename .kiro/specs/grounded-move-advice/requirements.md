# Requirements Document

Grounded move advice — the coach may name concrete moves, but only
engine-confirmed sound ones, and an objective checker verifies the output.

## Introduction

The coach's job (VISION) is a **bridge**: a named theme (*what to focus
on*) plus **a concrete, sound way to do it here** (*the move or plan*).
Live runs proved the second half is where we hallucinate: after adding
explicit piece placement (`describe_placement`), the coach stopped
inventing pieces but still suggested `Nf6-e4` — a **legal but unsound**
move that drops the knight. That is not a placement error; it is a
**soundness** error, and it comes from the LLM inventing a concrete move
to fit a theme, with nothing checking whether the engine endorses it.

This feature closes that hole from both ends:

- **Input side.** The engine is the sole source of any concrete move's
  soundness. We widen the engine's candidate menu (more `multipv` lines,
  compact: first move + eval + theme), tag each move **sound vs blunder**
  from its eval-drop-from-best, and constrain the prompt so the coach may
  name concrete moves **only** from the sound part of that menu (or stay
  at the plan level). The knowledge bank supplies the *theme and how to
  think*, paired to the chosen move's engine theme — it never supplies a
  concrete move for the live position (it cannot: that is calculation,
  which is the engine's job).
- **Output side.** A deterministic **fidelity checker** reads the
  finished coaching text and counts claims that contradict the board or
  the rules: a named move that is illegal or engine-tagged unsound, a
  "piece on square" claim the board denies, a "developed/undeveloped"
  claim the placement denies, a move named "from" an empty square. This
  is the safety net for anything the prompt constraint misses, and it is
  an objective Layer-1 A/B metric (no judge).

Non-negotiables (product owner, this session):
- **The engine is the sole arbiter of a named move's soundness.** No move
  reaches the student validated by anything other than the engine. The
  LLM never invents a concrete move; the knowledge bank never supplies
  one for the live position.
- **No hybrid, no half-ship.** Both halves land: the input-side
  constraint AND the output-side checker. A constrained prompt with no
  output net, or a checker with an unconstrained prompt, is not done.
- **Bounded menu, not the full move list.** A curated, tagged menu of a
  handful of candidates — not every legal move — for cost, small-model
  prompt clarity, and to stay a teacher (VISION: "not a position analyst
  / engine GUI").
- **No workarounds.** Every soundness threshold, theme mapping, and
  checker pattern is a named, tested, documented rule; the checker is
  precision-first with documented, bounded recall — never a silent
  guess.

## Glossary

- **Candidate menu** — the engine's top-N lines for the side to move,
  rendered compactly as `first move (SAN) + eval_cp + theme`. Sorted
  best-first by the engine (index 0 = best).
- **Eval-drop-from-best** — for candidate `i`,
  `top_lines[0].eval_cp - top_lines[i].eval_cp` (≥ 0). The engine sorts
  lines best-first for the side to move and the move-comparator /
  critical-moment logic already use this same difference, so no
  perspective juggling is introduced.
- **Soundness tag** — a client label on each candidate derived from its
  eval-drop, reusing the existing `Coach.classify_move` thresholds:
  `best` (the top line), `sound` (drop ≤ 50 cp), `dubious`
  (51–100 cp), `blunder` (> 100 cp).
- **Named move** — a move token the coach's *output text* mentions
  (SAN like `Nd5`, `O-O`, or coordinate forms like `f6-d5` / "f6 to
  d5").
- **Theme** — the engine's per-line short label
  (`piece development`, `king safety, castling`, `material win`,
  `central pawn break`, `king attack`, `general play`) from
  `label_line_theme`. Engine-owned (Glossary of client-side-coaching-text
  spec: a short label, rendered as-is).
- **Fidelity checker** — a pure client function that scans coaching text
  against the board + rules + the tagged menu and returns structured
  **violations**.
- **Violation** — one detected contradiction, categorized
  (`illegal_move`, `unsound_move`, `placement`, `development`,
  `empty_source`).

## Requirements

### Requirement 1: Widened, structured candidate menu

**User Story:** As a coach, I want a bounded menu of the engine's best
moves with their evals and themes, so I can teach from a real set of
sound options instead of one best move.

#### Acceptance Criteria

1. THE engine candidate count (`multipv`) SHALL be a configurable knob
   with a documented default raised from 3 to 5; the value SHALL flow
   through `Coach` to `get_position_report`.
2. THE menu SHALL be rendered compactly as, per candidate, its **first
   move in SAN**, its `eval_cp`, and its engine `theme` — NOT the full
   deep line (per the owner: "just the first move and some score").
3. THE menu SHALL read only structured fields (`PVLine.moves[0]`,
   `PVLine.eval_cp`, `PVLine.theme`) and the board (for SAN) — never any
   engine `description` prose (consistent with the client-side-coaching
   -text single-source rule).
4. IF the engine returns fewer lines than requested (few legal moves,
   forced position), THE menu SHALL render exactly what is available and
   the soundness tagging SHALL still hold.

### Requirement 2: Soundness tagging (client policy)

**User Story:** As a coach, I want each candidate marked sound or a
blunder, so I know which moves I may recommend and which to warn against.

#### Acceptance Criteria

1. THE client SHALL tag each candidate `best` / `sound` / `dubious` /
   `blunder` from its eval-drop-from-best, reusing the existing
   `Coach.classify_move` thresholds as the single source of the
   boundaries (no second copy of the numbers).
2. THE tagging SHALL be a pure, deterministic function of the menu's
   `eval_cp` values; the top line is always `best`.
3. THE tagging SHALL be total: any candidate list (including length 0/1,
   equal evals, mate-ish large magnitudes) yields tags without raising.

### Requirement 3: Prompt constraint — the coach names only sound moves

**User Story:** As a student, I want any specific move my coach names to
be sound, so I am never taught a losing move.

#### Acceptance Criteria

1. THE rich coaching prompt AND the Socratic prompt AND the move-
   evaluation prompt SHALL present the tagged menu and instruct the model
   that, when it names a concrete move, it SHALL choose ONLY from the
   `best`/`sound` candidates.
2. THE prompt SHALL explicitly permit **plan-level** advice (e.g. "get
   castled", "improve your worst piece") when no single move is the
   point, and SHALL forbid inventing a move not in the menu.
3. THE existing grounding rules (only engine data; never place a piece
   the data denies) SHALL be retained and never weakened (parallels
   client-side-coaching-text Req 3.4).
4. THE constraint SHALL be gated by a config switch (default on) so A/B
   runs can compare constrained vs unconstrained prompts.

### Requirement 4: Theme ↔ knowledge-bank pairing

**User Story:** As a student, I want the *why* behind the recommended
move tied to a principle I can reuse, so the move teaches, not just wins.

#### Acceptance Criteria

1. THE system SHALL map the engine `theme` of the chosen (`best`/`sound`)
   move to the knowledge bank via a named, documented theme→feature
   mapping, and surface the matching entry's `focus` + `how_to_apply`
   through the existing guidance block.
2. THE mapping SHALL be data/policy, not a per-case patch; an unmapped
   theme SHALL fall back to the existing feature-based guidance selection
   and SHALL NOT block or error.
3. THE knowledge bank SHALL NOT be a source of a concrete move for the
   live position; it supplies only the theme/focus/how-to-think (VISION
   bridge end 1).

### Requirement 5: Output fidelity checker (deterministic)

**User Story:** As a maintainer, I want an objective count of coaching
claims that contradict the board or rules, so hallucinations are caught
and measured without a human or a judge.

#### Acceptance Criteria

1. THE system SHALL provide a pure function that, given coaching text + a
   `PositionReport` (with its tagged menu) + the board, returns a
   structured list of violations, each categorized:
   - `illegal_move` — a named move not legal in the position;
   - `unsound_move` — a named move that is legal but tagged
     `dubious`/`blunder` (or absent from the menu and, when checkable,
     failing the soundness threshold);
   - `placement` — a "piece on/at square" claim the board denies;
   - `development` — a "developed/undeveloped/still on … " claim the
     placement denies;
   - `empty_source` — a move named "from `<square>`" where the square is
     empty or holds a different piece than claimed.
2. THE checker SHALL be **precision-first**: it flags only high-
   confidence, pattern-matched contradictions and documents that recall
   is bounded (it is not a proof of correctness, it is a floor). It SHALL
   NOT raise on any input and SHALL return an empty list for text with no
   detectable claim.
3. THE checker SHALL be pure (no engine, no network, no LLM); it uses
   only the report, its precomputed tagged menu, and the board.
4. THE checker SHALL extend, not replace, the existing hallucination
   detector; overlapping capability SHALL be consolidated, not
   duplicated.

### Requirement 6: Measurement / A/B

**User Story:** As the owner, I want to see whether the menu+constraint
actually reduces unsound/hallucinated advice, on both a small model and
qwen3:14b at production temperature.

#### Acceptance Criteria

1. THE fidelity checker SHALL be wired as an objective (Layer-1) eval
   metric reporting the violation rate per category over a benchmark run.
2. THE eval harness SHALL support toggling the constraint (Req 3.4) and
   the menu width (Req 1.1) so a run can compare conditions.
3. A documented A/B SHALL be run across the benchmark for: constraint
   off vs on, on the small model AND qwen3:14b, at production temperature
   0.7; results recorded in BACKLOG/eval notes (not committed config).

### Requirement 7: Configuration

**User Story:** As an operator, I want the new behavior controlled by
config with safe defaults, so it is reproducible and reversible.

#### Acceptance Criteria

1. `multipv` width, the constraint on/off switch, and (if surfaced) the
   soundness thresholds SHALL be config-driven with documented defaults;
   thresholds default to the current `classify_move` values.
2. `config.yaml` (the owner's runtime switches: model, guidance) SHALL
   remain **unstaged** — it is a separate concern per the commit
   checklist.

### Requirement 8: Quality gates and proofs

**User Story:** As a maintainer, I want the feature to land green and
provably correct on its core logic.

#### Acceptance Criteria

1. `uv run pytest`, `uv run mypy src` (strict), `uv run ruff check src
   tests`, `uv run ruff format --check src tests` SHALL all pass.
2. Property tests (Hypothesis ≥ 100) SHALL cover soundness-tagging
   totality + determinism (Req 2.3) and checker totality (never raises,
   Req 5.2).
3. Curated unit tests SHALL pin the checker's precision on hand-built
   cases including the live `Nf6-e4` regression (unsound move flagged)
   and a correct-advice case (no false positive).
