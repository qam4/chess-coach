# Design Document

## Overview

The profiler is a thin orchestration over the **existing** eval harness plus a
small **pure** core (data model + threshold→recommendation mapping + render).
Point it at a model; it runs cheapest-first dimension checks, reusing
`eval_run`/objective scoring and the move-feedback pairwise A/B; it prints a
per-dimension facts report and an advisory config block, and writes the
profile to a file. No baselines, no diffing, no auto-apply in v1.

```
profile_model.py (producer, thin)
   ├─ reachability  → OllamaProvider.check_status + one smoke generate
   ├─ factual       → existing objective/factual eval over fixed positions
   ├─ guidance      → existing move-feedback pairwise (off vs on)
   └─ latency       → time N warm generate calls
        ↓ build list[DimensionResult]
   eval/profile.py (PURE)
        ├─ CapabilityProfile(model, captured_at, dimensions=[...])
        ├─ recommend(profile, thresholds) → ConfigRecommendation
        └─ render_profile / render_recommendation
        ↓
   stdout report + config snippet  +  output/profile_<model>.json
```

## Components

### Pure core — `src/chess_coach/eval/profile.py`

Lives beside the other pure eval modules (`aggregate.py`, `scoring.py`,
`judge.py`). No engine, no network — unit-testable with constructed inputs.

```python
@dataclass(frozen=True)
class DimensionResult:
    name: str                      # "reachability" | "factual" | "guidance" | "latency"
    status: str                    # "pass" | "fail" | "info"  (info = fact-only, e.g. latency)
    metrics: dict[str, float]      # facts, e.g. {"factual": 0.30, "hallucinations": 0}
    latency_s: float | None = None # cost, kept SEPARATE from quality metrics
    samples: int = 0
    notes: str = ""

@dataclass(frozen=True)
class CapabilityProfile:
    model: str
    captured_at: datetime
    dimensions: list[DimensionResult]   # a list (menu), not fixed fields

@dataclass(frozen=True)
class ConfigSuggestion:
    key: str        # e.g. "coaching.guidance"
    value: str      # e.g. "on"
    reason: str     # one-line, cites the measured fact

@dataclass(frozen=True)
class ConfigRecommendation:
    suggestions: list[ConfigSuggestion]

@dataclass(frozen=True)
class ProfileThresholds:
    factual_min: float = 0.50        # below → suggest template_only
    guidance_win_rate_min: float = 0.60  # at/above → suggest guidance on

def recommend(profile: CapabilityProfile, thresholds: ProfileThresholds) -> ConfigRecommendation: ...
def render_profile(profile: CapabilityProfile) -> str: ...
def render_recommendation(rec: ConfigRecommendation) -> str: ...
def profile_to_dict(profile) -> dict / from_dict(...)  # JSON persistence
```

`recommend` is the only place facts become advice, and it is pure:
- factual dimension: `factual < factual_min` OR `hallucinations > 0`
  → `coaching.template_only: true` (reason cites the number); else `false`.
- guidance dimension: `win_rate >= guidance_win_rate_min`
  → `coaching.guidance: on`; else `off` (reason cites win-rate + significance).
- latency: **no suggestion** — reported as a fact only (Req 5.3).
- reachability fail: a single suggestion noting the model is unusable.

Facts-not-verdicts is enforced structurally: `metrics`/`latency_s` carry the
numbers; `recommend` is small and separable; latency has `status="info"`.

### Producer — `scripts/profile_model.py`

Cheapest-first; stops if reachability fails (Req 2.3). Reuses, not reimplements:
- **reachability:** `OllamaProvider.check_status()` (reachable vs model-loaded,
  the message we already fixed) + one `generate` smoke (`Coach.check` style).
- **factual:** the objective/factual scoring already in `eval/` over a fixed
  position set (the `eval_run` factual path), capturing mean factual +
  hallucination/illegal counts.
- **guidance:** the move-feedback pairwise library functions
  (`load_move_feedback_scenarios`, `pairwise_compare_move`, `majority_winner`,
  `summarize_pairwise`) — the same code path as `eval_move_feedback_pairwise.py`.
  (Refactor that script's loop into an importable function so both call it.)
- **latency:** time N warm `generate` calls (warm first, per FITT's cold-load
  note), report p50.

Long-running (the pairwise A/B is ~30 min), so it is a **script** runnable
under kiro-monitor, consistent with the other eval entry points — not a
blocking CLI command. A thin `chess-coach profile` CLI wrapper is a later
nicety, not v1.

### Output

- stdout: `render_profile` (facts table) then `render_recommendation` (config
  snippet with reasons).
- `output/profile_<model>.json`: the serialized CapabilityProfile (the run is
  recorded; this is also the seed for a future baseline/diff if we add it).

## Reuse map (what already exists)

| Dimension | Existing component reused |
|-----------|---------------------------|
| reachability | `OllamaProvider.check_status`, `Coach.check` |
| factual | `eval/objective.py` scoring, `eval_run.py` factual path |
| guidance | move-feedback pairwise (`judge.pairwise_compare_move`, `majority_winner`, `summarize_pairwise`, `eval/move_feedback.py`) |
| latency | timed `LLMProvider.generate` calls |

## Testing

- **Pure core:** unit-test `recommend` (each threshold branch: low factual →
  template_only; hallucinations present → template_only; win-rate above/below →
  guidance on/off; latency never produces a suggestion), `render_*`, and JSON
  round-trip — all with constructed `DimensionResult`s, no live model.
- **Producer:** light integration with mocked provider/engine for the
  reachability-fail short-circuit; the live evals are already covered by their
  own tests.

## What we are deliberately NOT building (v1)

- Stored **baselines** and profile **diffing** (FITT's regression-catcher).
  The JSON output is written so this can be added later as pure functions over
  two CapabilityProfiles.
- A **declared-facts** catalog layer (Ollama `/api/tags` capabilities, context
  window). Easy to append as `status="info"` dimensions when wanted.
- **Auto-applying** the recommendation to `config.yaml` (operator-in-the-loop).
- Instruction-following / level-adherence dimension — a clean future append
  (dimensions are a list), not needed to make the first config decisions.
