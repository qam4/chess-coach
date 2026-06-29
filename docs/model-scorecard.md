# Model scorecard

A durable, in-repo record of how each local model performed on the coaching
task, and the config knobs we'd set to use it well. This is the human-readable
companion to the [model-capability profiler](model-profiler.md): the profiler
produces a per-model `output/profile_<model>.json` (gitignored, local-only),
and this table makes the validated findings durable in the repo.

The end-to-end loop the project is built around:

1. **Profile** a swappable local model — `scripts/profile_model.py` runs the
   dimensions (reachability → factual → guidance → latency).
2. **Read** its scorecard (this file) — what it's good at, what it costs.
3. **Set the knobs** in `config.yaml` under `coaching:` to match the model's
   strengths (`guidance` on/off, `template_only` true/false).
4. The **live app** uses the model to its strengths — no code changes per
   model.

## The knobs (config.yaml → `coaching:`)

| Knob | Meaning | When to turn it on |
|------|---------|--------------------|
| `template_only` | Skip the LLM, use deterministic templates only | Model is not grounded (low factual, any hallucinations/illegal moves) — trust templates instead |
| `guidance` | Inject pedagogy guidance (a named teaching principle) into the prompt | Model is strong enough that guidance measurably improves teaching |
| `guidance_max` | Max guidance entries injected (default 3) | Lower to 1 for the safest (most factual) setting; raise for more teaching |

## Scorecard

Numbers below come from this session's profiler/A-B runs (Ollama on EC2,
`localhost:11435`, claude-sonnet-4.6 judge, move-feedback pairwise A/B with
5-vote majority over 20 mistake-biased situations). "Factual" is the mean
0–1 grounding score over the benchmark positions; "guidance" is the
move-feedback win-rate of guidance-on vs guidance-off with a two-sided sign
test.

| Model | Factual | Hallucinations / illegal | Guidance (on win-rate) | Latency (p50) | Recommended knobs |
|-------|---------|--------------------------|------------------------|---------------|-------------------|
| **hermes3:8b** | ~0.17 | — | flat/negative (too weak to use guidance) | — | `template_only: true`, `guidance: off` |
| **gemma4:12b-it-qat** | ~0.30 | 0 / 0 | 8-8 tie (50%, p=1.0) — no benefit | ~7s | `template_only: false`, `guidance: off` |
| **qwen3:8b** | — | — | 14-6 (70%, p=0.115) — leans positive, not significant | — | `template_only: false`, `guidance: off` (on is borderline) |
| **qwen3:14b** | 0.26 | 2 / 1 | **16-4 (80%, p=0.012)** — significant | 6.3s | `template_only: true`, `guidance: on` |

### Reading the table

- **hermes3:8b** — too weak. Low factual grounding and guidance does nothing
  for it. Use templates only.
- **gemma4:12b-it-qat** — well grounded (0 hallucinations, 0 illegal moves)
  and fast, so the LLM path is safe. But guidance gives no teaching benefit
  (a clean 8-8 tie once the SAN-vs-UCI confound was removed), so leave
  guidance off.
- **qwen3:8b** — guidance leans positive (70%) but at p=0.115 it's short of
  significance. Defaulting guidance off; a replication run could promote it.
- **qwen3:14b** — the standout for *teaching*: guidance significantly helps
  (80%, p=0.012 — the first statistically significant teaching benefit
  anywhere in the project). But it's a worse fact-checker on its own
  (factual 0.26, 2 hallucinations, 1 illegal move in the factual dimension),
  so pair `guidance: on` with `template_only: true` — let it teach via the
  guided move-feedback path while templates backstop raw factual claims.

### The capability gradient

A coherent pattern across the three move-feedback A/Bs: guidance does nothing
for the non-reasoning model (gemma), leans positive for the small reasoning
model (qwen3:8b), and significantly helps the larger reasoning model
(qwen3:14b). The pedagogy layer is validated for a model strong enough to use
it.

## Caveats

- These are single runs (move-feedback A/Bs are not yet replicated ≥3×).
  qwen3:14b's p=0.012 is solid but a replication would firm it up; qwen3:8b's
  70% would likely cross into significance with more data.
- Generation is deterministic at temp 0 for gemma (repeats sample judge noise,
  not response variance); qwen is a reasoning model and non-deterministic, so
  its samples carry more genuine response diversity.
- Everything here is a **frontier-judge proxy** for teaching quality, not
  measured student improvement (the project's true north). The scorecard keeps
  the proxy honest; it does not replace longitudinal outcome measurement.
