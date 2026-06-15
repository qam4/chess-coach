# Chess Coach

A chess coaching tool that pairs engine analysis with LLM-powered natural
language explanations. Instead of just showing you the best move, it explains
*why* — what's happening in the position, what the plan is, and what to look
for.

> **North star:** chess-coach aims to be a *teacher* for a player who
> wants to improve — not a position analyst. When you're stuck, it
> names what to focus on and gives a concrete, sound way to do it at
> your level. See [`VISION.md`](VISION.md).

## How it works

```
FEN position
    → Chess engine (Blunder) analyzes via UCI + coaching protocol
    → Rich structured data: eval breakdown, threats, hanging pieces, tactics
    → LLM (Qwen3 via Ollama) explains in plain English
    → You understand the position, not just the move
```

Features:
- Position analysis with natural language coaching
- Play mode: play against the engine with move-by-move feedback
- Opening identification (3600+ named openings from ECO)
- Web UI with SSE streaming for real-time coaching
- Coaching protocol: structured engine data (eval breakdown, threats, king safety, pawn structure)
- Pluggable LLM backend (Ollama, OpenAI-compatible)

## Quick start

### Prerequisites

1. **Blunder chess engine** — build from [qam4/blunder](https://github.com/qam4/blunder)
2. **Ollama** — install from [ollama.com](https://ollama.com/download), or run via Docker (see below)
3. **Python 3.11+**

### Ollama setup

#### Option A: Native install

```bash
# Install from https://ollama.com/download
ollama pull qwen3:8b
```

#### Option B: Docker (recommended for AL2 / older glibc)

```bash
docker run -d --name ollama -p 11434:11434 -v ollama:/root/.ollama ollama/ollama
docker exec ollama ollama pull qwen3:8b
```

### Install chess-coach

```bash
pip install -e .
cp config.example.yaml config.yaml
# Edit config.yaml with your engine path
```

### Usage

```bash
# Check that engine and LLM are reachable
chess-coach check

# Explain a position
chess-coach explain "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"

# Override depth or coaching level
chess-coach explain "r1bqkb1r/pppppppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4" \
    --depth 12 --level beginner

# Start the web UI
chess-coach serve
```

## Configuration

Edit `config.yaml`:

```yaml
engine:
  path: "path/to/blunder"
  protocol: "uci"              # uci (recommended) or xboard
  args: []                     # --uci/--xboard added automatically
  depth: 8

llm:
  provider: "ollama"           # or "openai_compat"
  model: "qwen3:8b"
  base_url: "http://localhost:11434"
  max_tokens: 512
  temperature: 0.7
  timeout: 300

coaching:
  top_moves: 3
  level: "intermediate"        # beginner, intermediate, advanced
```

The engine protocol defaults to UCI. If Blunder supports the coaching protocol
(`coach ping`), chess-coach automatically uses it for richer analysis data
(eval breakdown, threats, hanging pieces, pawn structure, king safety). If not,
it falls back to standard UCI analysis.

## Development

This project uses [uv](https://docs.astral.sh/uv/) for environment and
dependency management.

```bash
uv sync                              # create .venv with runtime + dev deps

# Run checks
uv run pytest
uv run mypy src/
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
```

CI runs on GitHub Actions (Python 3.11 + 3.12) on every push to main.

## Evaluating coaching quality

How good is the coaching, and which model should produce it? The eval
harness scores models on two axes — **factual accuracy** (objective,
engine-grounded) and **coaching quality** (a frontier LLM judge against
a rubric). Quick start:

```bash
# Free, engine-grounded factual scoreboard:
python scripts/eval_run.py --models qwen3:8b

# Add the coaching-quality judge:
python scripts/eval_run.py --models qwen3:8b --judge-model fitt-smart \
    --judge-base-url http://<gateway>/v1 --judge-api-key "$TOKEN"
```

See [`docs/evaluation.md`](docs/evaluation.md) for the full three-layer
guide (objective checks, LLM-as-judge, human calibration) and how to
add benchmark positions. See [`docs/pedagogy.md`](docs/pedagogy.md) for
the pedagogy layer that grounds the judge's `teaches_principle` standard
and the coach's "what to focus on" (the `--guidance` A/B).

## Swapping the LLM

The LLM provider is pluggable:

```yaml
# Ollama (default)
llm:
  provider: "ollama"
  model: "qwen3:8b"
  base_url: "http://localhost:11434"

# llama.cpp server or any OpenAI-compatible API
llm:
  provider: "openai_compat"
  model: "local-model"
  base_url: "http://localhost:8080"
```

## Swapping the engine

Any UCI-compatible engine works. Xboard is also supported:

```yaml
engine:
  path: "path/to/stockfish"
  protocol: "uci"
```

## License

Apache 2.0
