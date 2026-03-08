---
inclusion: auto
description: Project overview, architecture, module layout, and key design decisions
---

# Chess Coach — Project Overview

Chess Coach is a Python CLI tool that combines chess engine analysis with
LLM-powered natural language explanations. A user provides a FEN position,
the engine analyzes it, and an LLM explains what's happening in plain English.

Repository: `qam4/chess-coach`

## Commands

- `chess-coach explain <FEN>` — full coaching pipeline (engine → analysis → LLM → text)
- `chess-coach check` — verify engine and LLM connectivity

## Architecture

```
CLI (click) → Coach (orchestrator) → Analyzer (engine + python-chess) → LLM Provider
```

The Coach orchestrator:
1. Sends the FEN to the Analyzer, which runs the engine subprocess
2. Formats the engine output with python-chess (material, SAN moves, board state)
3. Builds a coaching prompt with the analysis and coaching level
4. Sends the prompt to the LLM provider
5. Returns the coaching text to the CLI

## Module Layout

```
src/chess_coach/
├── cli.py          # Click CLI: explain, check commands
├── coach.py        # Coach orchestrator class
├── analyzer.py     # Position analysis (engine + python-chess bridge)
├── engine.py       # Engine protocol abstraction (UCI default, Xboard supported)
├── prompts.py      # Prompt templates (system prompt, analysis prompt)
└── llm/
    ├── __init__.py
    ├── base.py     # LLMProvider ABC
    ├── ollama.py   # Ollama provider (POST /api/generate)
    └── openai.py   # OpenAI-compatible provider (POST /v1/chat/completions)
```

## Configuration

Single `config.yaml` with three sections:

```yaml
engine:
  path: /path/to/engine      # engine binary
  protocol: uci               # uci (recommended) or xboard
  depth: 18                   # analysis depth
  args: []                    # extra engine CLI args

llm:
  provider: ollama            # ollama or openai
  model: qwen3:8b             # model name
  base_url: http://localhost:11434  # LLM endpoint
  max_tokens: 512
  temperature: 0.7

coaching:
  level: intermediate         # beginner, intermediate, advanced
  top_moves: 3                # number of top moves to explain
```

## Key Design Decisions

- All LLM inference runs locally — no data leaves the user's machine
- Only open source models with permissive licenses (Apache 2.0 preferred)
- Default model: Qwen3-8B via Ollama (Apache 2.0, good chess reasoning)
- Engine runs as a subprocess with stdin/stdout pipes
- Background thread for engine line reading with timeout
- httpx for all HTTP calls (120s timeout for slow CPU inference)
- Prompt templates are separate from logic for easy tuning

## Dependencies

- `python-chess` — board representation, move validation, SAN conversion
- `httpx` — HTTP client for LLM API calls
- `pyyaml` — config file parsing
- `click` — CLI framework
