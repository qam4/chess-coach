# Requirements Document

Correct Coaching Inputs for the LLM (single composition source of truth).

## Introduction

The deliverable is **correct inputs to the LLM coaching path**. The LLM
is the product goal; the template renderer is a secondary consumer and a
diagnostic. For the LLM to coach well, two things must hold: the engine's
**facts must be correct**, and the client must **present them to the LLM
properly**.

Investigating the template path surfaced the real problem in the LLM
prompt builder (`prompts.py`): of the engine-fact sections it feeds the
model, **four are already composed from structured fields** (pawn
structure, hanging pieces, piece-safety/threat-map, top lines) while
**three pass the engine's prose `description` through verbatim**
(tactical motifs, threats, king safety). That split is the root cause of
every wording problem we hit (double labels, "in PV" jargon, redundant
motif variants, endgame king-safety noise): those defects reach the LLM
only through the three prose-passthrough sections.

This feature removes that inconsistency **completely**. The engine emits
structured facts + a small enumerated set of short labels; the client
composes **every** coaching sentence from the structured facts through a
**single source of truth**, consumed identically by the LLM prompt and
the template. No engine prose is consumed anywhere. No fact is recovered
by regex over prose. No fact the client needs is recomputed from the FEN
(which would duplicate engine logic) — if the client needs a fact, the
engine provides it as structured data.

Non-negotiables (product owner, this session):
- **No hybrid, no half-migration.** Either every full sentence is
  client-composed, or the feature is not done (proven by a sentinel
  test).
- **No workarounds / short-term hacks.** Every client decision is a
  named, tested rule; every engine gap is closed with a **structured**
  protocol field, never a prose parse or a client recomputation of
  engine logic.
- **No inconsistency.** One composer produces every fact-derived
  sentence; both the prompt and the template consume it and differ only
  in layout/wrapping.

## Glossary

- **Fact source** — the engine. Emits structured data (`type`,
  `squares`, `pieces`, `in_pv`, `source_square`, `target_squares`,
  `uci_move`, structured king-safety fields, pawn/threat-map/eval
  structures) that is correct and complete enough to compose from.
- **Short label** — an enumerated, non-sentence engine tag the protocol
  design assigns to the engine: `theme`, `best_move_idea`,
  `critical_reason`. Out of scope while they remain labels.
- **Prose field** — a full-sentence engine string: `tactics[]`,
  `threats[]`, `missed_tactics[]`, `king_safety.*` `description`. To be
  demoted to debug-only and never consumed.
- **Composer** — `coaching_phrases`, the single client module that turns
  structured facts into canonical coaching sentences.
- **Consumer** — a surface that renders composed sentences: the LLM
  prompt builder (primary) and the template renderer (secondary). A
  consumer arranges/wraps sentences for its medium; it never re-derives
  or re-words facts.

## Requirements

### Requirement 1: Single composition source of truth

**User Story:** As a developer, I want exactly one place that turns
engine facts into coaching sentences, so the LLM and the template can
never diverge and wording is iterated in one file.

#### Acceptance Criteria

1. THE system SHALL provide `coaching_phrases` with pure functions that
   compose the canonical sentence for every engine-fact **prose**
   category: tactics, threats, king safety, hanging pieces, pawn
   structure, and the eval assessment. The threat-map is a structured
   table rendered per-medium (counts for the LLM, tensions for the UI),
   not a single composed sentence, and reads no engine prose.
2. BOTH consumers (the LLM prompt builder and the template renderer)
   SHALL obtain fact-derived sentences ONLY from `coaching_phrases`.
3. NO consumer SHALL re-derive or re-word a fact locally; a consumer
   MAY only arrange, wrap, or add medium-specific layout (e.g. section
   headers for the prompt, `CoachingSection` objects for the template).
4. THE composer SHALL be pure (no engine, no network, no LLM),
   deterministic, and derive side and piece names from the board (FEN) +
   structured squares.

### Requirement 2: No engine prose consumed anywhere

**User Story:** As the product owner, I want a hard guarantee the engine
`description` prose never reaches the LLM or the UI, so migration is
provably complete.

#### Acceptance Criteria

1. NO client code path (prompt builder, template, insights, and — by
   scope extension — the eval judge's `format_engine_report`) SHALL read
   `tactics[].description`, `threats[].description`,
   `missed_tactics[].description`, or `king_safety.*.description`.
2. A sentinel test SHALL set every engine `description` to a unique
   marker and assert the marker appears in NO built prompt and NO
   template output. This test is the definition-of-done gate.

### Requirement 3: LLM prompt path composes the three passthrough sections

**User Story:** As a student, I want the model grounded in correct,
consistent facts, so its coaching is trustworthy.

#### Acceptance Criteria

1. `prompts.py` (rich coaching prompt AND move-evaluation prompt) SHALL
   render Tactical Motifs, Threats, and King Safety from
   `coaching_phrases`, not from engine `description`.
2. THE on-board vs in-PV distinction SHALL be preserved as a clear
   phrase derived from the `in_pv` flag (on-board = available now; in-PV
   = arises in the engine's best line) — never the raw token "in PV".
3. THE three newly-composed sections SHALL be produced by the same
   composer calls the template uses (Req 1.2 parity).

### Requirement 4: Threat moves from structured data, never regex

**User Story:** As a developer, I want the threat move read from a field,
so we never parse prose to recover facts.

#### Acceptance Criteria

1. `verify.filter_illegal_threats` SHALL recover the threat move from
   `threat.uci_move`; the `_VIA_RE` / `_UCI_RE` regex helpers SHALL be
   removed.
2. Move-bearing threats (check, capture) SHALL carry `uci_move`
   (verified: the engine already sets it). Relational threats (fork, pin,
   skewer) describe an existing board relationship rather than a move,
   correctly carry no `uci_move`, and are retained by the filter (there is
   nothing to prove illegal). No engine change is required to remove the
   regex.
3. IF a threat lacks `uci_move`, the composer SHALL degrade to a
   move-less sentence and the gap SHALL be fixed at the engine — never by
   parsing prose.
4. THE existing legality verification (`filter_illegal_threats`) SHALL be
   retained and SHALL run before composition, so the composer only
   phrases facts that survived it (composed sentences are ground-truth by
   construction). Verifying the LLM's generated OUTPUT (prompt ablation,
   write→check→repair loop) is explicitly OUT OF SCOPE and remains the
   separate consolidated BACKLOG item.

### Requirement 5: King safety from structured engine fields

**User Story:** As a student, I want king-safety coaching that is correct
and composable, without the client re-implementing the engine.

#### Acceptance Criteria

1. THE engine (Blunder) SHALL expose structured king-safety fields
   sufficient to compose the assessment: at minimum `king_square`,
   `castled`, `castling_rights`, `missing_shield_files`, and
   `open_file_near_king`.
2. THE `KingSafety` model SHALL carry those fields (validation +
   `from_dict`/`to_dict`); `score` is retained; `description` becomes
   debug-only.
3. THE composer SHALL build the king-safety sentence from those
   structured fields; it SHALL NOT recompute king safety from the FEN and
   SHALL NOT read `description`.

### Requirement 6: Engine owns facts; client owns presentation policy

**User Story:** As a developer, I want a clean authority boundary, so
there are no ambiguous or duplicated decisions.

#### Acceptance Criteria

1. THE engine SHALL be the sole authority on facts (what is true about
   the position).
2. THE client SHALL be the sole authority on presentation policy, each
   expressed as a named, documented, tested rule (never a per-case
   patch): motif de-duplication keyed on structured motif identity
   (preferring the on-board variant), suppression of a threat that
   restates a shown tactic, coaching-relevance filtering (e.g. suppress
   king-safety commentary in low-material endgames per the
   coaching-philosophy relevance tiers), and section ordering.
3. NO presentation rule SHALL depend on engine prose or on re-deriving
   engine facts.

### Requirement 7: Short labels stay engine-owned; sentences do not

**User Story:** As a developer, I want a firm line on labels vs
sentences, so the boundary is unambiguous.

#### Acceptance Criteria

1. `theme`, `best_move_idea`, and `critical_reason` SHALL remain
   engine-owned short labels, rendered as-is, and are out of scope.
2. IF any of those is found to be a full sentence rather than a short
   label, it SHALL be reclassified as a prose field and composed by the
   client — no full sentence is ever passed through from the engine.

### Requirement 8: Engine description demoted, not deleted; WIP reverted

**User Story:** As a developer, I want the protocol intact for debugging
without the client depending on it, and no dead wording churn.

#### Acceptance Criteria

1. THE engine SHALL keep emitting `description`, documented as
   debug/non-authoritative; no protocol version break is required.
2. THE uncommitted engine wording changes (tactic side labels, "in PV"
   removal) SHALL be reverted, since `description` is no longer consumed;
   only structural/legality/`uci_move`/king-safety-field changes remain
   on the engine side.

### Requirement 9: Quality gates and proofs

**User Story:** As a maintainer, I want the migration to land green,
tested, and provably consistent.

#### Acceptance Criteria

1. `uv run pytest`, `uv run mypy src` (strict), `uv run ruff check src
   tests`, `uv run ruff format --check` SHALL all pass.
2. Property tests (Hypothesis ≥100) SHALL cover composer totality (never
   raise / never empty over the full type enums) and determinism.
3. A parity test SHALL assert the prompt path and the template path
   render the same fact via the same composer output.
4. The sentinel test (Req 2.2) SHALL pass.
