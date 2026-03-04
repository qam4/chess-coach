---
inclusion: manual
description: How to set up the chess-coach development environment from scratch
---

# Development Setup

## Prerequisites

- Python 3.11+
- A chess engine binary (Blunder, Stockfish, or any Xboard/UCI engine)
- Ollama (for local LLM inference)

## Install chess-coach

```bash
git clone https://github.com/qam4/chess-coach.git
cd chess-coach
pip install -e ".[dev]"
```

The `[dev]` extra installs pytest, mypy, ruff, and other dev tools.

## Install Ollama and pull the default model

```bash
# Install Ollama from https://ollama.com
ollama pull qwen3:8b
```

Qwen3-8B is Apache 2.0 licensed and runs well on 8GB+ VRAM GPUs.
For CPU-only machines, consider `qwen3:4b` (slower but lighter).

## Configure

Copy the example config and edit paths:

```bash
cp config.example.yaml config.yaml
```

Set `engine.path` to your engine binary. Example:

```yaml
engine:
  path: /path/to/blunder
  protocol: xboard
  depth: 18
```

## Verify setup

```bash
chess-coach check
```

This verifies the engine binary exists and the LLM is reachable.

## Run tests

```bash
pytest
mypy src/
ruff check src/ tests/
```
