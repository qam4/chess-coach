# Design: Chess Coaching MVP

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                     Frontends                                │
│                                                              │
│  ┌──────────────────┐    ┌────────────────────────────────┐  │
│  │   CLI (click)    │    │   Web UI (localhost:8000)      │  │
│  │  explain <FEN>   │    │  chessboard.js + coaching panel│  │
│  │  check           │    │  eval bar + move arrows        │  │
│  │  serve           │    │  FEN input + level/depth       │  │
│  └────────┬─────────┘    └──────────────┬─────────────────┘  │
│           │                             │                    │
└───────────┼─────────────────────────────┼────────────────────┘
            │                             │ HTTP (FastAPI)
            ▼                             ▼
┌─────────────────────────────────────────────────────┐
│                  Coach (orchestrator)                │
│   FEN → Analyzer → format → Prompt → LLM → text    │
└──────┬──────────────────────────────────┬───────────┘
       │                                  │
       ▼                                  ▼
┌──────────────┐                ┌──────────────────┐
│   Analyzer   │                │   LLM Provider   │
│  (engine +   │                │   (abstract)     │
│  python-chess│                │                  │
│  formatting) │                │  ┌────────────┐  │
└──────┬───────┘                │  │  Ollama    │  │
       │                        │  ├────────────┤  │
       ▼                        │  │ OpenAI API │  │
┌──────────────┐                │  └────────────┘  │
│   Engine     │                └──────────────────┘
│  Protocol    │
│  (abstract)  │
│              │
│ ┌──────────┐ │
│ │ Xboard   │ │
│ ├──────────┤ │
│ │ UCI      │ │  (future)
│ └──────────┘ │
└──────────────┘
```

## Module Design

### engine.py — Engine Communication

Abstract `EngineProtocol` interface with concrete `XboardEngine` implementation.

```python
class EngineProtocol(ABC):
    def start() -> None
    def stop() -> None
    def analyze(fen, depth, time_limit) -> AnalysisResult
    def is_ready() -> bool

class XboardEngine(EngineProtocol):
    # Manages subprocess, sends xboard commands, parses thinking output
    # Thinking output format: "depth score time nodes pv..."

class UCIEngine(EngineProtocol):  # future
    # Manages subprocess, sends UCI commands, parses info lines
    # Info format: "info depth N score cp X nodes Y nps Z pv ..."
```

Data structures:
- `AnalysisLine`: depth, score_cp, nodes, time_ms, pv (list of moves)
- `AnalysisResult`: fen, lines (list of AnalysisLine), best_move

The engine runs as a subprocess. Communication is via stdin/stdout pipes.
Line reading uses a background thread with timeout to avoid blocking.

### analyzer.py — Position Analysis

Bridges the engine and the LLM prompt layer. Uses `python-chess` for:
- Board state inspection (material, check status, move number)
- PV conversion from coordinate notation to SAN for readability
- Position validation

Produces a structured text block that the LLM prompt template consumes.

### llm/ — LLM Provider Abstraction

```python
class LLMProvider(ABC):
    def generate(prompt, max_tokens, temperature) -> str
    def is_available() -> bool
```

Two implementations:
- `OllamaProvider`: POST to `/api/generate` on localhost:11434
- `OpenAICompatProvider`: POST to `/v1/chat/completions` (works with
  llama.cpp server, vLLM, LM Studio, or any OpenAI-compatible endpoint)

Factory function `create_provider(name, model, base_url)` instantiates
the right class from config.

All HTTP calls use `httpx` with a 120-second timeout (LLM generation
can take a while on CPU).

### prompts.py — Prompt Engineering

System prompt establishes the coaching persona. Analysis prompt template
injects the engine output and coaching level.

The prompt asks the LLM to:
1. Describe what's happening in the position
2. Explain the best plan for the side to move
3. Explain why the top move is good

Responses are capped at ~200 words to keep them focused and fast.

Prompt templates are separate from logic so they can be tuned without
touching code.

### coach.py — Orchestrator

The `Coach` class ties everything together:
1. Calls `analyze_position()` to get engine analysis
2. Calls `format_analysis_for_llm()` to structure it
3. Calls `build_coaching_prompt()` to create the full prompt
4. Calls `llm.generate()` to get the coaching text
5. Returns a `CoachingResponse` dataclass

### cli.py — Command Line Interface

Built with `click`. Three commands for MVP:
- `explain <FEN>`: full coaching pipeline (CLI output)
- `check`: verify engine + LLM connectivity
- `serve`: start the local web server (FastAPI + uvicorn)

Config loaded from `config.yaml` (path overridable with `--config`).

### web/ — Web UI

Local web interface served by FastAPI on `localhost:8000`.

#### Backend: `web/server.py`

FastAPI app with these endpoints:
- `GET /` — serves the single-page HTML app
- `POST /api/analyze` — accepts `{fen, depth, level}`, returns
  `{coaching_text, eval_cp, best_move, top_lines}` via the Coach pipeline
- `GET /api/health` — calls `Coach.check()`, returns status

The server reuses the same `Coach` instance as the CLI. A single engine
subprocess stays alive across requests for fast response times.

CORS is not needed since the browser loads the page from the same origin.

#### Frontend: `web/static/`

Single-page app with no build step (vanilla JS + CSS):
- `index.html` — page layout: board (left), coaching panel (right)
- `app.js` — board initialization, API calls, UI state management
- `style.css` — layout, eval bar, coaching panel styling

Chess board: `chessboard.js` (BSD license) for the interactive board with
drag-and-drop. `chess.js` (BSD license) for client-side move validation
so illegal moves are rejected before hitting the server.

UI components:
- Interactive chessboard with piece drag-and-drop
- FEN input field (paste or type, board updates live)
- "Analyze" button triggers the coaching pipeline
- Coaching text panel (scrollable, formatted markdown)
- Eval bar (vertical bar showing engine score, white/black shading)
- Best move arrows drawn on the board (green for best, blue for alternatives)
- Depth slider and coaching level dropdown
- Loading spinner during analysis

The JS libraries (`chessboard.js`, `chess.js`) and piece SVGs are vendored
in `web/static/vendor/` so the app works fully offline.

## Configuration

Single `config.yaml` file with three sections:
- `engine`: path, protocol, args, depth
- `llm`: provider, model, base_url, max_tokens, temperature
- `coaching`: top_moves, level

## Dependencies

- `python-chess`: board representation, move validation, SAN conversion
- `httpx`: HTTP client for LLM API calls
- `pyyaml`: config file parsing
- `click`: CLI framework
- `fastapi`: web server for the browser UI
- `uvicorn`: ASGI server to run FastAPI
- `jinja2`: HTML template rendering (FastAPI dependency for static files)

Frontend (vendored, no npm/node required):
- `chessboard.js`: interactive chessboard (BSD license)
- `chess.js`: client-side move validation (BSD license)

All are well-maintained, permissively licensed packages.

## Performance Considerations

- Engine analysis: 1-5 seconds depending on depth
- LLM generation (GPU, 8B model, Q4): 3-5 seconds for 200 tokens
- LLM generation (CPU-only, 8B model): 10-15 seconds (borderline usable)
- Total target: under 15 seconds end-to-end with GPU

## Future Extensions

- **UCI engine support**: Add `UCIEngine` class when Blunder implements UCI.
  UCI provides structured `info` lines and `MultiPV` for multiple top moves.
- **PGN game review**: Parse PGN, identify critical positions (eval swings),
  generate coaching for each. Add PGN upload to the web UI.
- **Interactive mode**: Chat panel in the web UI for follow-up questions
  about the current position, with LLM conversation context.
- **Streaming**: Stream LLM output token-by-token via SSE for perceived speed.
- **Game navigation**: Forward/backward buttons in the web UI to step through
  a loaded PGN game, with coaching at each critical position.
