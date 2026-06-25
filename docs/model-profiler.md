# Model-capability profiler

chess-coach runs on an LLM the project does not control and that **will
change** — a new Ollama model, a swapped default, a different endpoint. You
can't know in advance how a given model behaves on the coaching task. The
profiler answers that empirically: point it at a model, it runs a few checks
that each decide a config setting, and it prints the facts plus a recommended
config block you can paste in.

It is a thin wrapper over the existing eval harness (`eval_run` factual scoring
and the move-feedback pairwise A/B). See the spec at
[`.kiro/specs/model-capability-profiler/`](../.kiro/specs/model-capability-profiler/).

## What it measures (cheapest-first, so a bad model fails fast)

| Dimension | What it checks | Drives config |
|-----------|----------------|---------------|
| **reachability** | endpoint reachable + model loaded + can generate | usable at all (gate; short-circuits on fail) |
| **factual** | grounding over the benchmark positions: mean factual score + hallucination/illegal-move counts | `coaching.template_only` (trust the LLM vs. deterministic templates) |
| **guidance** | move-feedback pairwise A/B — does pedagogy guidance beat no-guidance? | `coaching.guidance` (on/off) |
| **latency** | warm per-call response time (p50) | reported as a **fact** — never graded |

## Design principles (kept lean, adapted from FITT)

- **Facts, not verdicts.** Raw numbers are reported (`factual=0.30`,
  `p50=7.2s`); the operator judges them against what the model is *for*.
  Latency never gets a pass/fail.
- **Capability and cost stay separate.** Quality (`metrics`) and latency
  (`latency_s`) are side by side, never blended into one score.
- **Operator-in-the-loop.** The profiler *recommends* config; it never writes
  or auto-applies it.
- **Dimensions are a list, not a schema.** Adding a dimension is appending a
  `DimensionResult` — the renderer and the recommend mapping iterate the list.

The pure layer (`src/chess_coach/eval/profile.py`: data model + `recommend` +
render) is unit-testable with no live model; the producer
(`scripts/profile_model.py`) is the thin step that runs the evals.

## Running it

The guidance dimension runs the full pairwise A/B (~30 min), so run it under
kiro-monitor like the other long evals. It needs the model endpoint (for
generation) and a judge (kiro-cli or an OpenAI-compatible endpoint); the engine
runs locally.

```bash
uv run python scripts/profile_model.py \
    --model qwen3:14b --base-url http://localhost:11435 \
    --judge-provider cli --judge-model claude-sonnet-4.6 \
    --judge-command "kiro-cli chat --no-interactive --model claude-sonnet-4.6 {prompt}"
```

Useful flags: `--factual-min` (default 0.50; below → suggest `template_only`),
`--guidance-win-rate-min` (default 0.60; at/above → suggest `guidance: on`),
`--judge-repeats` (default 5; majority-voted to denoise the judge),
`--out` (default `output/profile_<model>.json`).

### Tunnel stability

If the model is reached over an SSM port-forward, the connection gets
**idle-reset** by the network path during the judge phase (which doesn't touch
the tunnel) — the EC2 box stays healthy but receives zero requests once the
tunnel drops. The `run_profile.ps1` / `run_move_feedback_pairwise.ps1` runners
start a background **heartbeat** (`scripts/tunnel_heartbeat.ps1`) that pings the
endpoint every ~15s to keep the connection warm for the whole run; it's stopped
automatically when the run ends. For ad-hoc work you can run the heartbeat
standalone alongside a session.

## Reading the output

Two parts to stdout (and the full profile is written to
`output/profile_<model>.json`):

1. **Profile** — one line per dimension with its facts and (separately) its
   latency.
2. **Recommendation** — a pasteable config snippet plus a one-line reason per
   setting, each citing the measured number. Advisory only; apply it yourself.

Example shape:

```
[PASS] factual        | factual=0.33, hallucinations=0, illegal_moves=0 | latency: — | n=9
[PASS] guidance       | on_win_rate=0.75, decisive=20, p_value=0.041   | latency: — | n=20
[INFO] latency        | —                                              | latency: 7.2s | n=9

Recommended config (advisory — apply manually):
  coaching.template_only: false
  coaching.guidance: on
Why:
  - coaching.template_only = false: LLM is grounded (factual=0.33, 0 hallucinations/illegal)
  - coaching.guidance = on: guidance helps: on win-rate 75% (>= 60%)
```

## Deferred (append-only when missed)

- **Stored baselines + diffing** a new profile against a known-good one
  (FITT's regression-catcher on model swap). The JSON output is written so this
  can be added later as pure functions over two profiles.
- A **declared-facts** catalog dimension (Ollama `/api/tags` capabilities,
  context window).
- An **instruction-following** dimension (level + word-limit adherence).
- A `chess-coach profile` CLI wrapper over the script.
