# Chess Coach

A chess coaching tool that pairs engine analysis with LLM-powered natural
language explanations. Instead of just showing you the best move, it explains
*why* — what's happening in the position, what the plan is, and what to look
for.

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

```bash
pip install -e ".[dev]"

# Run checks
pytest
mypy src/
ruff check src/ tests/
ruff format --check src/ tests/
```

CI runs on GitHub Actions (Python 3.11 + 3.12) on every push to main.

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
