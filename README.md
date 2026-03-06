# Chess Coach

A chess coaching tool that pairs engine analysis with LLM-powered natural
language explanations. Instead of just showing you the best move, it explains
*why* — what's happening in the position, what the plan is, and what to look
for.

## How it works

```
FEN position
    → Chess engine (Blunder) analyzes: top moves, scores, PV lines
    → LLM (Qwen3-8B via Ollama) explains in plain English
    → You understand the position, not just the move
```

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

The native Ollama binary requires glibc 2.27+. On Amazon Linux 2 or similar,
use Docker instead:

```bash
# Start Ollama in Docker (persists models across restarts)
docker run -d --name ollama -p 11434:11434 -v ollama:/root/.ollama ollama/ollama

# Pull a model inside the container
docker exec ollama ollama pull qwen3:8b
```

Useful Docker commands:

```bash
# Check if Ollama is already running
docker ps | grep ollama

# Stop and restart
docker stop ollama
docker start ollama

# Pull a different model
docker exec ollama ollama pull mistral
```

The default `base_url: "http://localhost:11434"` in `config.yaml` works for
both native and Docker setups since the container maps port 11434.

### Install chess-coach

```bash
pip install -e .

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
    --depth 20 --level beginner
```

### Example output

```
============================================================
Position: rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1
Best move: e7e5  (+0.12)
============================================================

Engine analysis:
  Line 1: +0.12 (depth 18)   e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O

------------------------------------------------------------
Coach says:
------------------------------------------------------------
This is the starting position after 1.e4. White has occupied the center
with a pawn and opened lines for the bishop and queen. Black has many
good responses.

The engine recommends 1...e5, the classical reply. This fights for the
center immediately and opens the diagonal for Black's dark-squared
bishop. After 2.Nf3 Nc6, both sides develop naturally toward the
Italian Game or Ruy Lopez.

The position is essentially equal — neither side has an advantage yet.
Focus on developing your pieces toward the center and castling early.
```

## Configuration

Edit `config.yaml`:

```yaml
engine:
  path: "path/to/blunder.exe"
  protocol: "xboard"          # "uci" coming soon
  args: ["--xboard", "--nnue", "path/to/weights.bin"]
  depth: 18

llm:
  provider: "ollama"           # or "openai_compat"
  model: "qwen3:8b"
  base_url: "http://localhost:11434"
  max_tokens: 512
  temperature: 0.7
  timeout: 300                 # seconds; increase for slow models

coaching:
  top_moves: 3
  level: "intermediate"        # beginner, intermediate, advanced
```

## Development Setup

### Install dependencies

```bash
# Option A: editable install with dev extras (recommended)
pip install -e ".[dev]"

# Option B: traditional requirements file
pip install -r requirements-dev.txt
```

### Running tests and checks

The project uses [tox](https://tox.wiki/) to run tests, linting, and type checking in isolated environments.

```bash
# Run everything (tests + lint + typecheck)
tox

# Run just tests
tox -e py311

# Run just linting (ruff check + format check)
tox -e lint

# Run just type checking (mypy)
tox -e typecheck

# Auto-fix formatting issues
tox -e format
```

Or run tools directly without tox:

```bash
pytest tests/
ruff check src/ tests/
ruff format src/ tests/
mypy src/chess_coach/
```

## Swapping the LLM

The LLM provider is pluggable. To use a different backend:

### Ollama (default)
```yaml
llm:
  provider: "ollama"
  model: "qwen3:8b"           # or mistral, llama3.1, etc.
  base_url: "http://localhost:11434"
```

### llama.cpp server
```bash
./llama-server -m model.gguf --host 0.0.0.0 --port 8080
```
```yaml
llm:
  provider: "openai_compat"
  model: "local-model"
  base_url: "http://localhost:8080"
```

### Any OpenAI-compatible API
```yaml
llm:
  provider: "openai_compat"
  model: "your-model"
  base_url: "http://your-server:port"
```

## Swapping the engine

Any Xboard-compatible engine works. Just update `config.yaml`:

```yaml
engine:
  path: "path/to/any-xboard-engine"
  protocol: "xboard"
  args: ["--xboard"]
```

UCI support will be added once Blunder implements it.

## License

Apache 2.0
