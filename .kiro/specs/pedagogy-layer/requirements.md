# Requirements Document

## Introduction

Per [`VISION.md`](../../../VISION.md), every piece of coaching is a *bridge*
with two ends: (1) **what to focus on** — a named theme or principle the
student should apply — and (2) **a concrete, engine-sound way to apply it
here**, at the student's level. Today the engine (Blunder's coaching
protocol) grounds end 2: it answers whether a suggested action is sound.
Nothing grounds end 1. The "what to teach" — the principles, named patterns,
and standard plans — is currently supplied by the LLM from its own chess
sense, which is exactly what the project does not want to blindly trust:
small models hallucinate, and the eval harness's `teaches_principle`
criterion (see [`coaching-eval/design.md`](../coaching-eval/design.md) and
[`rubric.v2.yaml`](../../../data/eval/rubric.v2.yaml)) currently grades that
half against the judge's own chess knowledge rather than a real standard.

This feature builds the **pedagogy layer**: a curated knowledge resource that
grounds *what is worth teaching and how*. It holds the foundational
principles (center control, development, king safety, piece protection, piece
coordination), named tactical and positional patterns, and standard plans
keyed to opening / ECO contexts. The same resource is injected into **both**
ends of the teaching pipeline: the coach prompt (so the teaching voice names
the right principle and bridges it to the engine-sound action — see
`build_rich_coaching_prompt` in `src/chess_coach/prompts.py`) and the judge
prompt (so the eval harness grades `teaches_principle` against a real
standard, not the judge's chess sense).

The test for every requirement below is the VISION test: *does it move a
stuck student closer to knowing what to do and getting better?* Quality is
not judged by the product owner's chess taste — they are the student, not the
expert. It comes from the engine (end 2 soundness), chess authority (the
curated resource), and ultimately student outcomes.

### Scope and dependencies

- **In scope:** the knowledge resource (structure, authoring, correctness),
  how guidance is selected for a position, how it grounds the coach prompt,
  how it grounds the judge's `teaches_principle` criterion, and how the impact
  is measured through the existing eval harness.
- **Out of scope (later arc steps):** progress tracking (VISION "The arc this
  unlocks" step 2) and level-adaptive teaching (step 3) both depend on this
  layer but are not built here. The student's level is an input the layer
  honors; building a per-student profile or adapting over time is deferred.
- **Source material:** the foundational principles and named patterns connect
  to [`IDEAS.md`](../../../IDEAS.md) "Structured Learning Path", which is a
  separate curriculum / learning-path product, not this feature.

## Glossary

- **Pedagogy_Layer**: The overall system this feature delivers — the curated
  knowledge resource plus the components that select guidance for a position
  and inject it into the coach and judge prompts.
- **Knowledge_Resource**: The curated, local, version-controlled data artifact
  holding all Guidance_Entries. The authority for "what is worth teaching".
- **Guidance_Entry**: A single curated record in the Knowledge_Resource. One
  of three types: Principle, Pattern, or Plan.
- **Principle**: A transferable foundational idea (e.g. center control,
  development, king safety, piece protection, piece coordination).
- **Pattern**: A named tactical or positional motif (e.g. fork, back-rank
  weakness, weak square, outpost) or a named endgame technique.
- **Plan**: A standard middlegame or opening plan associated with one or more
  opening / ECO contexts.
- **Position_Feature**: A checkable characteristic of a position that keys
  Guidance_Entry selection (e.g. game phase, an undefended piece, an open
  file, a passed pawn, an exposed king).
- **ECO_Code**: An Encyclopaedia of Chess Openings code (or opening name)
  identifying the opening context of a position.
- **Selector**: The component that, given a position, returns the relevant
  Guidance_Entries from the Knowledge_Resource.
- **Student**: The target user — knows opening principles in the abstract but
  gets stuck on how to apply them to the board in front of them. Has a coaching
  Level of beginner, intermediate, or advanced.
- **Level**: The student's coaching target level (beginner, intermediate, or
  advanced), an existing concept in the coaching pipeline.
- **Coach_Prompt**: The prompt sent to the coaching LLM voice, built by the
  rich coaching prompt builders in `src/chess_coach/prompts.py`.
- **Judge_Prompt**: The prompt sent to the frontier judge in the eval harness.
- **Teaches_Principle_Criterion**: The eval harness rubric criterion
  (`teaches_principle` in `rubric.v2.yaml`) that grades whether a coaching
  response names a transferable principle AND applies it soundly in the
  position.
- **Eval_Harness**: The existing coaching evaluation harness (Layer 1 factual
  accuracy, Layer 2 judged teaching quality) described in
  [`coaching-eval/design.md`](../coaching-eval/design.md).
- **Annotation_Guard**: The validation step that rejects ungrounded or
  malformed Guidance_Entries before they are used, mirroring the benchmark
  annotation guard from the coaching-eval spec.

## Requirements

### Requirement 1: Curated knowledge resource

**User Story:** As a developer, I want a curated, structured resource of
principles, patterns, and plans, so that "what to teach" comes from chess
authority rather than from the LLM's own chess sense.

#### Acceptance Criteria

1. THE Knowledge_Resource SHALL store Guidance_Entries as local data files
   separate from application code, such that adding, removing, or modifying a
   Guidance_Entry requires no change to application code.
2. EACH Guidance_Entry SHALL record an identifier unique within the
   Knowledge_Resource, exactly one type from {Principle, Pattern, Plan}, a
   named theme, a student-facing statement of what to focus on, and a
   student-facing statement of how to apply it.
3. THE Knowledge_Resource SHALL include, at minimum, the five foundational
   opening Principles (center control, development, king safety, piece
   protection, and piece coordination) as a labeled starting anchor, AND SHALL
   be extensible with additional Principle, Pattern, and Plan entries across
   themes and game phases without code change (per Requirement 1.1).
4. EACH Guidance_Entry SHALL record one or more Levels drawn from the set
   {beginner, intermediate, advanced} for which the guidance is appropriate.
5. WHERE a Guidance_Entry is a Plan, THE entry SHALL record one or more
   ECO_Codes or opening contexts to which the Plan applies.
6. WHERE a Guidance_Entry is a Principle or Pattern, THE entry SHALL record one
   or more Position_Features that key the entry's selection.
7. EACH Guidance_Entry SHALL record a non-empty citation to its source
   authority, so that guidance is traceable to instructional canon rather than
   invented.
8. IF a Guidance_Entry is missing a required field, or records a type or Level
   value outside the defined sets, THEN THE Knowledge_Resource SHALL reject the
   entry and report the offending entry and the reason.
9. IF two Guidance_Entries share the same identifier, THEN THE
   Knowledge_Resource SHALL reject the duplicate and report the conflicting
   identifier.

### Requirement 2: Selecting guidance for a position

**User Story:** As a student stuck on how to apply principles to the board in
front of me, I want the coach to pick the principles, patterns, and plans that
actually fit this position, so that I focus on what matters here.

#### Acceptance Criteria

1. WHEN a position is presented to the Pedagogy_Layer, THE Selector SHALL
   return every Guidance_Entry all of whose recorded Position_Features are
   present in the position, and SHALL NOT return any Guidance_Entry whose
   recorded Position_Features are not all present.
2. WHERE an ECO_Code or opening context is known for the position, THE Selector
   SHALL include each Plan entry whose recorded ECO_Codes (per Requirement 1.5)
   include that ECO_Code.
3. THE Selector SHALL limit the returned Guidance_Entries to no more than a
   configured maximum, which is an integer greater than or equal to 1.
4. WHEN more Guidance_Entries match than the configured maximum, THE Selector
   SHALL return the top entries ordered by relevance, breaking ties by a
   deterministic stable order (e.g. ascending identifier).
5. IF no Guidance_Entry matches the position's Position_Features, THEN THE
   Selector SHALL return the foundational Principle entries whose recorded
   Levels include the Student's Level as a fallback.
6. WHEN the Selector is invoked repeatedly with identical inputs (position,
   Knowledge_Resource, Student's Level, and configured maximum), THE Selector
   SHALL return the same Guidance_Entries in the same order on every
   invocation.
7. THE Selector SHALL return only Guidance_Entries that exist in the
   Knowledge_Resource, and never any entry absent from it.
8. IF the presented position is malformed or invalid, THEN THE Selector SHALL
   return no Guidance_Entries and report an error indication.

### Requirement 3: Grounding the coach prompt

**User Story:** As a student, I want the coaching voice to name the right
principle and connect it to a concrete, sound move here, so that the advice
bridges what I know in the abstract to the board in front of me.

#### Acceptance Criteria

1. WHEN the coach builds a Coach_Prompt for a position, THE Pedagogy_Layer
   SHALL inject into the Coach_Prompt every Guidance_Entry chosen by the
   Selector for that position.
2. WHEN guidance is injected, THE Coach_Prompt SHALL include, for each injected
   Guidance_Entry, both its named theme text and its how-to-apply statement
   text, so the Coach_Prompt carries both ends of the teaching bridge.
3. WHEN guidance is injected, THE Pedagogy_Layer SHALL exclude any
   Guidance_Entry whose recorded Levels do not include the Student's current
   Level.
4. WHEN guidance is injected, THE Coach_Prompt SHALL retain the existing engine
   grounding instructions, so the engine remains the authority on whether the
   concrete action is sound.
5. WHILE the coaching pipeline runs in template-only mode (no LLM voice), THE
   Pedagogy_Layer SHALL supply the selected Guidance_Entries to the template
   coaching path.
6. IF the Selector provides zero Guidance_Entries for the position, THEN THE
   Coach_Prompt SHALL be built with the engine grounding instructions retained
   and no injected guidance.
7. IF no Guidance_Entry survives Level filtering, THEN THE Coach_Prompt SHALL
   be built with the engine grounding instructions retained and no injected
   guidance.

### Requirement 4: Grounding the judge

**User Story:** As a developer measuring coaching quality, I want the judge to
grade "teaches the right principle" against the curated resource, so that the
teaching half is grounded in a real standard instead of the judge's own chess
sense.

#### Acceptance Criteria

1. WHEN the Eval_Harness builds a Judge_Prompt for a position, THE
   Pedagogy_Layer SHALL provide the identical set of Selector-chosen
   Guidance_Entries that the Coach_Prompt received for that same position.
2. THE Judge_Prompt SHALL present the provided Guidance_Entries as the sole
   standard for evaluating the Teaches_Principle_Criterion.
3. WHEN grading the Teaches_Principle_Criterion, THE Judge SHALL evaluate the
   coaching response only against the provided Guidance_Entries and SHALL NOT
   rely on chess knowledge outside those Guidance_Entries.
4. IF a coaching response teaches a principle that is absent from or
   contradicts the provided Guidance_Entries, THEN THE Judge SHALL fail the
   response on the Teaches_Principle_Criterion and indicate the unsupported or
   contradicting principle.
5. THE Pedagogy_Layer SHALL use exactly one Selector and exactly one
   Knowledge_Resource as the single source of guidance for both the
   Coach_Prompt and the Judge_Prompt.
6. IF no Guidance_Entries are available for the position when the Eval_Harness
   builds the Judge_Prompt, THEN THE Pedagogy_Layer SHALL omit the
   Teaches_Principle_Criterion from that Judge_Prompt and record that the
   criterion was not graded for that position.

### Requirement 5: Validating impact through the eval harness

**User Story:** As a developer, I want the pedagogy layer's effect measured by
the existing two-layer harness, so that I can show it improves teaching
without degrading factual soundness.

#### Acceptance Criteria

1. WHEN the Eval_Harness evaluates a coaching response produced with the
   Pedagogy_Layer active, THE Eval_Harness SHALL produce a Layer 1
   factual-accuracy score for the concrete action and a Layer 2
   teaching-quality score for that response.
2. WHEN guidance injection is enabled, THE Eval_Harness SHALL, over the
   identical set of coaching scenarios used in a run with guidance injection
   disabled, produce an aggregate Layer 1 factual-accuracy score that is
   greater than or equal to the aggregate Layer 1 factual-accuracy score of the
   disabled run, so that grounding "what to teach" introduces no new factual
   errors in "how to do it".
3. WHEN the Eval_Harness evaluates a coaching response, THE Eval_Harness SHALL
   report the Layer 2 Teaches_Principle_Criterion result (pass or fail) for
   that response.
4. WHEN an evaluation run completes, THE Eval_Harness SHALL output the
   aggregate Layer 2 teaching-quality score with the Pedagogy_Layer enabled,
   the aggregate Layer 2 teaching-quality score with the Pedagogy_Layer
   disabled over the identical set of coaching scenarios, and the numeric
   difference between the two scores.
5. IF the Eval_Harness cannot produce a Layer 1 factual-accuracy score or a
   Layer 2 teaching-quality score for an evaluated coaching response, THEN THE
   Eval_Harness SHALL exclude that response from the aggregate scores and
   report an error indication identifying the affected response.

### Requirement 6: Authoring and maintenance correctness

**User Story:** As a developer maintaining the resource, I want every guidance
entry validated before use, so that the resource never introduces ungrounded
or wrong "what to teach" guidance — the same lesson as the benchmark
annotation guard.

#### Acceptance Criteria

1. WHEN the Annotation_Guard validates a Guidance_Entry, THE Annotation_Guard
   SHALL admit or reject the entry, and only an admitted entry SHALL be
   available to the Selector.
2. THE Annotation_Guard SHALL verify that each Guidance_Entry's referenced
   Position_Features and ECO_Codes are drawn from the defined sets in the
   resource schema, and SHALL reject any entry referencing a value absent from
   those sets.
3. WHERE a Guidance_Entry includes a concrete example position, THE
   Annotation_Guard SHALL verify that the example's recommended action is legal
   under the rules of chess for that position.
4. WHERE a Guidance_Entry includes a concrete example position, THE
   Annotation_Guard SHALL verify that the example's recommended action is
   engine-sound — that the engine does not classify the action as losing or a
   blunder — using the engine as the source of truth.
5. THE Annotation_Guard SHALL verify that each Guidance_Entry includes the
   required fields defined in Requirement 1 (identifier, type, theme,
   what-to-focus-on, how-to-apply, applicable Levels, and source citation),
   each present and non-empty, and SHALL reject any entry that does not.
6. IF a Guidance_Entry fails validation, THEN THE Annotation_Guard SHALL reject
   only that entry, withhold it from the Selector, continue validating the
   remaining entries, and report the offending entry's identifier and the
   reason.
7. THE Annotation_Guard SHALL complete validation using only the engine and the
   resource schema as the sources of truth, and SHALL NOT call any external
   LLM judge.

### Requirement 7: Offline, local operation

**User Story:** As a single user of an offline-capable app, I want the pedagogy
layer to work without any external service, so that coaching stays available
the way the rest of chess-coach is.

#### Acceptance Criteria

1. THE Knowledge_Resource SHALL be a curated artifact stored on the local file
   system that requires no runtime dependency on any external, remote, or
   network-based service.
2. WHEN the Selector chooses guidance for a position, THE Pedagogy_Layer SHALL
   complete the selection using only the local Knowledge_Resource and the local
   engine, and SHALL NOT issue any outbound network request.
3. WHEN the Selector chooses guidance for a position, THE Pedagogy_Layer SHALL
   return the selected guidance within 5 seconds.
4. WHILE no network connectivity is available, THE Pedagogy_Layer SHALL load
   the Knowledge_Resource and select guidance for a position with identical
   behavior to operation while connectivity is available.
5. IF the Knowledge_Resource cannot be loaded because it is missing or corrupt,
   THEN THE Pedagogy_Layer SHALL return an error indicating the
   Knowledge_Resource is unavailable, SHALL NOT attempt to retrieve it from any
   external service, and SHALL leave any prior loaded state unchanged.
