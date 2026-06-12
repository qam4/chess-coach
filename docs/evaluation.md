# Evaluating chess-coach

How good is the coaching, and which model should produce it? The eval
harness answers that with two numbers per model:

- **Factual accuracy** — are the coach's claims *true*? Checked
  objectively against the engine (the oracle): hallucinated pieces,
  illegal moves, wrong who's-better calls, and whether it mentioned
  the key facts the engine found. No LLM, no cost.
- **Coaching quality** — is it *good teaching*? Scored by a frontier
  LLM judge against a fixed rubric, grounded in the engine report so
  the judge can't freelance chess facts.

Spec: `.kiro/specs/coaching-eval/`. Source: `src/chess_coach/eval/`.

## The three layers

| Layer | What | Cost | Command |
|-------|------|------|---------|
| 1. Objective | Engine-grounded fact checks → factual score | free | `eval_run.py` (always) |
| 2. Judge | Frontier LLM scores coaching quality vs rubric | tokens, on demand | `eval_run.py --judge-model ...` |
| 3. Calibration | Confirm the judge agrees with a human | one-time | `eval_calibrate.py` |

The objective layer is absolute: it surfaces a model's competency on
its own, no reference model required. The judge supplements it on the
subjective "is this good coaching" axis.

## Prerequisites

- A **coaching-capable Blunder build** (responds to `coach ping` /
  `coach eval`). The dev build path is in `config.yaml` under
  `engine.path`. If the engine reports `coaching_available=False` the
  harness aborts with a clear message.
- An **Ollama endpoint** for the model(s) under test (local
  `http://localhost:11434`, or a tunnel — see the EC2 runbook).

## Layer 1 — factual scoreboard (free)

```bash
# Default model from config, all benchmark positions:
python scripts/eval_run.py

# Specific models, head-to-head:
python scripts/eval_run.py --models qwen3:8b gpt-oss:20b

# A subset of positions, against a remote endpoint:
python scripts/eval_run.py --models hermes3:8b \
    --base-url http://localhost:11435 \
    --positions kr_vs_k hanging_knight_e5
```

Output: `output/eval_run/{results.json, summary.txt}`. The scoreboard
columns: `fact` (mean factual score), `pass%` (share ≥ 0.80), `cov`
(key-fact coverage), `hall`/`illeg`/`dir!` (factual errors), `qual`
(judge score, if run), `lat`, `words`.

Models under test run at **temperature 0 by default** for reproducible
scores; pass `--temperature 0.7` to match production coaching.

## Layer 2 — add the judge (on demand)

Point `--judge-*` at any OpenAI-compatible endpoint. Examples:

```bash
# Via the FITT gateway's frontier alias (Bearer auth):
python scripts/eval_run.py --models hermes3:8b \
    --judge-provider openai_compat \
    --judge-model fitt-smart \
    --judge-base-url http://<gateway>:8421/v1 \
    --judge-api-key "$FITT_TOKEN"

# Via a local/remote Ollama judge (no auth):
python scripts/eval_run.py --models hermes3:8b --base-url http://localhost:11435 \
    --judge-provider ollama --judge-model qwen3:14b --judge-base-url http://localhost:11435
```

The judge is **grounded**: it receives the engine report as ground
truth and is told not to use its own chess vision for factual claims.
It scores six binary rubric criteria (`data/eval/rubric.v1.yaml`):
`key_idea`, `explains_why`, `actionable`, `level_fit`, `grounded`,
`constructive`. `grounded` fails iff the judge flags a contradiction.

A judge failure never invalidates Layer 1 — the factual scoreboard
always stands.

Use a judge **stronger** than the models under test, ideally a
frontier model. A same-family judge risks self-preference bias.

## Layer 3 — calibrate the judge against a human

Trust the judge's scores only after confirming it agrees with you on
a seed set.

```bash
# 1. Produce a judged run over the seed set (Layer 1 + Layer 2):
python scripts/eval_run.py --models hermes3:8b --judge-model fitt-smart \
    --judge-base-url http://<gateway>:8421/v1 --judge-api-key "$FITT_TOKEN" \
    --out output/seed

# 2. Emit a review file + a ratings template:
python scripts/eval_calibrate.py generate --results output/seed/results.json

# 3. Read output/eval_calibrate/seed_review.md, fill in the ratings
#    template (true/false per criterion) and save it.

# 4. Compare the judge against your ratings:
python scripts/eval_calibrate.py agreement \
    --results output/seed/results.json \
    --ratings output/eval_calibrate/seed_ratings_template.yaml
```

`agreement` prints per-criterion and overall agreement and exits
non-zero if any criterion falls below 80%. If it does, sharpen the
rubric wording or pick a stronger judge before trusting automated
quality scores.

## The benchmark

Positions live in `data/eval/positions.yaml`. Each has a FEN, level,
phase, and **ground-truth coaching points** — structured, checkable
assertions wherever possible:

```yaml
- id: hanging_knight_e5
  fen: "r1bqkb1r/pppppppp/2n5/4N3/4n3/8/PPPP1PPP/RNBQKB1R w KQkq - 0 4"
  level: intermediate
  phase: opening
  points:
    - kind: eval_direction      # white_better | black_better | equal
      value: black_better
    - kind: hanging_piece       # a square
      value: e5
    - kind: free                # soft text hint (optional credit)
      value: undefended
      required: false
```

Point kinds: `eval_direction`, `hanging_piece`, `tactic` (all checked
against the engine), `phase` and `free` (un-checkable hints). Every
position must have at least one *required, referenceable* point — a
test enforces this so a position can't score a vacuous 1.0.

### Adding a position — derive ground truth from the engine

Annotations must match the engine oracle, not your intuition (we
learned this the hard way: three seed positions were mis-annotated and
scored correct coaching as wrong). After editing `positions.yaml`,
run the guard on an engine-capable box:

```bash
python scripts/eval_check_annotations.py
```

It fetches the engine report for every position and flags any
`eval_direction` / `hanging_piece` / `tactic` annotation that
disagrees with the engine. Exits non-zero on any mismatch.

## Running the tests

```bash
tox -e py3        # or: .tox/py3/Scripts/python -m pytest tests/test_eval_*.py
```

The harness is covered by property-based and unit tests plus
mock-judge integration tests, so the whole pipeline is verifiable
without an engine or live tokens.

## Superseded scripts

`scripts/eval_coaching.py` and `scripts/eval_models.py` are the older
keyword-matching evaluators. They're kept for reference but superseded
by this harness, which checks correctness against the engine instead
of grepping for vocabulary.
