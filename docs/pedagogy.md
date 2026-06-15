# The pedagogy layer

The pedagogy layer grounds the **"what to focus on"** end of the teaching
bridge. Per [`VISION.md`](../VISION.md), every piece of coaching joins a named
principle/theme to a concrete, engine-sound action *here*. The engine
(Blunder's coaching protocol) already grounds the *action* end — is the move
sound? The pedagogy layer grounds the *teaching* end — what is worth teaching,
and how — from curated chess authority instead of the LLM's own chess sense.

Spec: `.kiro/specs/pedagogy-layer/`. Source: `src/chess_coach/pedagogy/`.

## How it fits together

```
engine PositionReport ──> extract_features ─┐
FEN ──> eco_context (ECO) ───────────────────┼─> Selector ─> selected guidance
data/pedagogy/knowledge.yaml ─> load + guard ┘                    │
                                                  ┌───────────────┴───────────────┐
                                          coach prompt                      judge prompt
                                   (build_rich_coaching_prompt)        (teaches_principle standard)
```

The **same** selection feeds both prompts (one Selector, one resource), so the
judge grades `teaches_principle` against the very guidance the coach was given.

## The knowledge resource

Curated guidance lives in **`data/pedagogy/knowledge.yaml`** — data, not code,
so it grows without code changes. Each entry is a `GuidanceEntry`:

| field | meaning |
|-------|---------|
| `id` | unique identifier |
| `type` | `principle`, `pattern`, or `plan` |
| `theme` | the named idea (e.g. "center control") |
| `focus` | student-facing "what to focus on" |
| `how_to_apply` | student-facing "how to apply it here" |
| `levels` | subset of `{beginner, intermediate, advanced}` |
| `features` | Position_Features that select it (principle/pattern) |
| `eco_codes` | opening contexts that select it (plan) |
| `citation` | the source authority (required) |
| `example` | optional `{fen, move}` — checked legal + engine-sound |

The seed includes the five foundational opening principles (center control,
development, king safety, piece protection, piece coordination) as a labeled
anchor, plus breadth across the canon's theme families (safety, tactics, pawn
structure, endgame, ECO-keyed plans). `data/pedagogy/schema.md` documents the
fields, the defined `Position_Feature` names, and the theme families for
authors. The feature vocabulary itself is code-defined and closed
(`FEATURE_VOCAB` in `pedagogy/features.py`).

## Authoring a new entry

1. Add an entry to `data/pedagogy/knowledge.yaml` (no code change).
2. Reference only `Position_Feature` names from `FEATURE_VOCAB` (see
   `schema.md`) and well-formed ECO codes (`A00`–`E99`).
3. Give it a specific `citation` (source + locus).
4. If you add an `example`, make sure the move is legal and sound.
5. Validate before relying on it (next section).

## Validating the resource

```bash
# Schema + referential integrity + example legality (no engine, no LLM):
uv run python scripts/pedagogy_check.py

# Also verify each example move is engine-sound (needs a coaching engine):
uv run python scripts/pedagogy_check.py --with-engine
```

The guard validates each entry independently — a bad entry is rejected with
its id and reason while the rest are still admitted — mirroring the benchmark
annotation guard. It exits non-zero on any rejection.

## Selection

For a position the Selector returns the entries that fit, deterministically:

1. **feature match** — every recorded `Position_Feature` is present;
2. **ECO match** — plans whose ECO codes include the position's opening;
3. **level filter** — entries appropriate for the student's level;
4. **fallback** — the level-appropriate foundational principles when nothing
   matches;
5. **rank & cap** — most specific first, ties broken by id, capped.

## Measuring impact (eval A/B)

The pedagogy layer is wired into the eval harness behind a toggle, so you can
measure whether grounding "what to teach" improves coaching without hurting
factual soundness:

```bash
# Baseline (no guidance):
uv run python scripts/eval_run.py --models hermes3:8b --base-url http://localhost:11435 \
    --judge-provider cli --judge-model claude-sonnet-4.6 \
    --judge-command "kiro-cli chat --no-interactive --model claude-sonnet-4.6 {prompt}" \
    --rubric data/eval/rubric.v2.yaml --guidance off --out output/eval_off

# With the pedagogy layer:
uv run python scripts/eval_run.py --models hermes3:8b --base-url http://localhost:11435 \
    --judge-provider cli --judge-model claude-sonnet-4.6 \
    --judge-command "kiro-cli chat --no-interactive --model claude-sonnet-4.6 {prompt}" \
    --rubric data/eval/rubric.v2.yaml --guidance on --out output/eval_on
```

Compare the two runs over the identical benchmark set: Layer 1 factual accuracy
should not regress (`aggregate_quality` excludes any unscored response), and the
Layer 2 teaching-quality delta (`quality_delta`) shows the layer's
contribution. See [`evaluation.md`](evaluation.md) for the harness itself.

## What this is not (yet)

Progress tracking and level-adaptive teaching (the later steps of the VISION
arc) build on this layer but are out of scope here — the student's level is an
input the layer honors, not a profile it maintains.
