# Tasks: Chess Coaching MVP

## Phase 1 — Project Skeleton

- [ ] 1. Set up project structure and packaging
  - [ ] 1.1 Create `pyproject.toml` with project metadata, dependencies (python-chess, httpx, pyyaml, click, fastapi, uvicorn), and `[dev]` extras (pytest, mypy, ruff)
  - [ ] 1.2 Create `src/chess_coach/__init__.py` with version string
  - [ ] 1.3 Create `src/chess_coach/cli.py` with click group stub (`explain` and `check` commands that print "not implemented")
  - [ ] 1.4 Create `config.example.yaml` with all config sections and sensible defaults
  - [ ] 1.5 Create `tests/` directory with `conftest.py` and a smoke test that imports chess_coach
  - [ ] 1.6 Verify `pip install -e ".[dev]"` works and `chess-coach --help` prints usage

## Phase 2 — Engine Communication

- [ ] 2. Implement engine protocol abstraction and Xboard engine
  - [ ] 2.1 Create `src/chess_coach/engine.py` with `AnalysisLine`, `AnalysisResult` dataclasses and `EngineProtocol` ABC (`start`, `stop`, `analyze`, `is_ready`)
  - [ ] 2.2 Implement `XboardEngine(EngineProtocol)`: subprocess management, xboard command sequence (`xboard`, `protover 2`, `force`, `setboard`, `analyze`), thinking output parser
  - [ ] 2.3 Add background thread for engine stdout reading with configurable timeout
  - [ ] 2.4 Write tests for `XboardEngine` using a mock engine subprocess (test start/stop, analyze, timeout handling)

## Phase 3 — Position Analysis

- [ ] 3. Implement the analyzer bridge
  - [ ] 3.1 Create `src/chess_coach/analyzer.py` with `analyze_position(fen, engine, depth)` that calls the engine and returns `AnalysisResult`
  - [ ] 3.2 Implement `format_analysis_for_llm(fen, result, top_n)` using python-chess: material count, side to move, check/checkmate status, PV in SAN notation
  - [ ] 3.3 Write tests for analyzer formatting (known FEN → expected formatted text)

## Phase 4 — LLM Provider Abstraction

- [ ] 4. Implement LLM providers
  - [ ] 4.1 Create `src/chess_coach/llm/base.py` with `LLMProvider` ABC (`generate`, `is_available`) and `create_provider` factory
  - [ ] 4.2 Create `src/chess_coach/llm/ollama.py` with `OllamaProvider`: POST to `/api/generate`, 120s timeout, error handling
  - [ ] 4.3 Create `src/chess_coach/llm/openai.py` with `OpenAICompatProvider`: POST to `/v1/chat/completions`, 120s timeout
  - [ ] 4.4 Create `src/chess_coach/llm/__init__.py` re-exporting `create_provider` and provider classes
  - [ ] 4.5 Write tests for providers using httpx mock transport (test generate, is_available, error cases)

## Phase 5 — Prompt Engineering

- [ ] 5. Implement prompt templates
  - [ ] 5.1 Create `src/chess_coach/prompts.py` with `SYSTEM_PROMPT` (coaching persona), `build_coaching_prompt(analysis_text, level)` function
  - [ ] 5.2 Implement three coaching levels: beginner (simple terms, tactics focus), intermediate (balanced), advanced (prophylaxis, pawn structure, long-term plans)
  - [ ] 5.3 Cap response guidance at ~200 words in the prompt
  - [ ] 5.4 Write tests verifying prompt construction includes analysis text and level-appropriate instructions

## Phase 6 — Coach Orchestrator

- [ ] 6. Implement the Coach class
  - [ ] 6.1 Create `src/chess_coach/coach.py` with `CoachingResponse` dataclass (fen, analysis, coaching_text, elapsed_ms) and `Coach` class
  - [ ] 6.2 Implement `Coach.explain(fen, depth, level)`: calls analyzer → format → prompt → LLM → returns CoachingResponse
  - [ ] 6.3 Implement `Coach.check()`: verifies engine is_ready and LLM is_available, returns status dict
  - [ ] 6.4 Write tests for Coach using mocked engine and LLM (test explain pipeline, check success/failure)

## Phase 7 — CLI and Config

- [ ] 7. Wire up the CLI with config loading
  - [ ] 7.1 Implement config loading in `cli.py`: load `config.yaml`, merge CLI flags (--depth, --level, --config)
  - [ ] 7.2 Implement `explain` command: parse FEN arg, create Coach, call explain, print coaching text
  - [ ] 7.3 Implement `check` command: create Coach, call check, print status with clear pass/fail messages
  - [ ] 7.4 Add `--depth`, `--level`, `--config` options to the CLI
  - [ ] 7.5 Write integration tests for CLI using click.testing.CliRunner

## Phase 8 — Web UI

- [ ] 8. Implement the web-based coaching interface
  - [ ] 8.1 Add `fastapi`, `uvicorn`, and `jinja2` to `pyproject.toml` dependencies
  - [ ] 8.2 Vendor `chessboard.js`, `chess.js`, and piece SVGs into `src/chess_coach/web/static/vendor/`
  - [ ] 8.3 Create `src/chess_coach/web/server.py` with FastAPI app: `GET /` serves index.html, `POST /api/analyze` calls Coach.explain and returns JSON, `GET /api/health` calls Coach.check
  - [ ] 8.4 Create `src/chess_coach/web/static/index.html` with layout: chessboard (left), coaching panel (right), FEN input, depth slider, level dropdown, analyze button
  - [ ] 8.5 Create `src/chess_coach/web/static/app.js`: initialize chessboard.js board, wire FEN input to board sync, call `/api/analyze` on button click, render coaching text, draw best-move arrows on board
  - [ ] 8.6 Create `src/chess_coach/web/static/style.css`: responsive layout, eval bar (vertical bar with white/black shading based on score), coaching panel styling, loading spinner
  - [ ] 8.7 Add `serve` command to `cli.py`: load config, create Coach, start uvicorn on `localhost:8000` (port overridable with `--port`)
  - [ ] 8.8 Write tests for the FastAPI endpoints using `httpx.AsyncClient` (test analyze, health, static file serving)

## Phase 9 — Polish and Documentation

- [ ] 9. Documentation and final polish
  - [ ] 9.1 Write `README.md` with installation, quickstart (CLI and web UI), configuration reference, and recommended models
  - [ ] 9.2 Add docstrings to all public classes and functions
  - [ ] 9.3 Run full test suite, mypy, ruff format, ruff check — all clean
  - [ ] 9.4 Verify end-to-end: `chess-coach check`, `chess-coach explain <FEN>`, and `chess-coach serve` with a real engine and Ollama
