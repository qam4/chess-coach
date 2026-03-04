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
2. **Ollama** — install from [ollama.com](https://ollama.com/download)
3. **Python 3.11+**

### Setup

```bash
# Pull an LLM model (Apache 2.0 license, runs locally)
ollama pull qwen3:8b

# Install chess-coach
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

coaching:
  top_moves: 3
  level: "intermediate"        # beginner, intermediate, advanced
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
