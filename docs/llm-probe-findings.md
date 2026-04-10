# LLM Probe Findings — April 2026

Results from `scripts/probe_llm_chess.py` testing 5 local models
against 3 chess positions with structured engine data.

## Key Finding: Smaller Models Win

When given structured engine data (eval breakdowns, threats, tactics,
hanging pieces), smaller models produce zero hallucinations and are
dramatically faster than larger ones.

| Model | Size | Hallucinations (Style E) | Avg Latency | Notes |
|-------|------|--------------------------|-------------|-------|
| qwen3:1.7b | 1.4GB | 0 | 8.9s | Fast, concise, stays grounded |
| llama3.2:3b | 2.0GB | 0 | 15.1s | Best quality/speed tradeoff |
| phi4-mini | 2.5GB | 0 | 25.2s | Verbose but accurate |
| gemma3:4b | 3.3GB | 0 | 22.2s | Solid across the board |
| qwen3:8b | 5.2GB | 4 | 60.8s | Hallucinated board state |

## Why Bigger Failed

qwen3:8b hallucinated "pawns on d4 and e5", "pawn on e6", "knight on
f6", "queen on f1" — none of which exist. The larger model tried to
reason about the position independently rather than staying grounded
in the provided data. Smaller models followed instructions better.

## Prompt Style Comparison

Tested 6 prompt styles (A-F). Only E and F matter:

- **Style E (structured engine data)**: Zero hallucinations across all
  models except qwen3:8b. The model synthesizes and explains the data
  rather than inventing its own analysis.
- **Style F (template rephrase)**: Zero hallucinations but thin — just
  a friendlier version of template output. Limited value-add.
- **Styles A-D (raw FEN)**: High hallucination rate (5-15 across 12
  probes). Models cannot reliably read FEN positions.

## Recommendations

- **Desktop default**: llama3.2:3b — best quality/speed tradeoff
- **Mobile candidate**: qwen3:1.7b — 1.4GB, ~9s, zero hallucinations
- **Avoid**: qwen3:8b for coaching — too slow, more hallucinations
- **Prompt strategy**: Always feed structured engine data, never raw FEN
- **Chess principles in prompt**: Embed well-known principles (fight for
  center, develop first, castle early, etc.) so the LLM has a vocabulary
  to connect engine data to teachable concepts

## Raw Data

- Comparison report: `output/llm_probe/probe_comparison.md`
- Per-model reports: `output/llm_probe/probe_*.md`
- Raw JSON: `output/llm_probe/probe_raw.json`
- Probe script: `scripts/probe_llm_chess.py`
