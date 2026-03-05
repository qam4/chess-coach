# Tasks: Chess Coaching MVP

## Phase 1 — Project Skeleton

- [x] 1. Set up project structure and packaging
  - [x] 1.1 Create `pyproject.toml` with project metadata, dependencies (python-chess, httpx, pyyaml, click, fastapi, uvicorn), and `[dev]` extras (pytest, mypy, ruff)
  - [x] 1.2 Create `src/chess_coach/__init__.py` with version string
  - [x] 1.3 Create `src/chess_coach/cli.py` with click group stub (`explain` and `check` commands that print "not implemented")
  - [x] 1.4 Create `config.example.yaml` with all config sections and sensible defaults
  - [x] 1.5 Create `tests/` directory with `conftest.py` and a smoke test that imports chess_coach
  - [x] 1.6 Verify `pip install -e ".[dev]"` works and `chess-coach --help` prints usage

## Phase 2 — Engine Communication

- [x] 2. Implement engine protocol abstraction and Xboard engine
  - [x] 2.1 Create `src/chess_coach/engine.py` with `AnalysisLine`, `AnalysisResult` dataclasses and `EngineProtocol` ABC (`start`, `stop`, `analyze`, `is_ready`)
  - [x] 2.2 Implement `XboardEngine(EngineProtocol)`: subprocess management, xboard command sequence (`xboard`, `protover 2`, `force`, `setboard`, `analyze`), thinking output parser
  - [x] 2.3 Add background thread for engine stdout reading with configurable timeout
  - [x] 2.4 Write tests for `XboardEngine` using a mock engine subprocess (test start/stop, analyze, timeout handling)

## Phase 3 — Position Analysis

- [x] 3. Implement the analyzer bridge
  - [x] 3.1 Create `src/chess_coach/analyzer.py` with `analyze_position(fen, engine, depth)` that calls the engine and returns `AnalysisResult`
  - [x] 3.2 Implement `format_analysis_for_llm(fen, result, top_n)` using python-chess: material count, side to move, check/checkmate status, PV in SAN notation
  - [x] 3.3 Write tests for analyzer formatting (known FEN → expected formatted text)

## Phase 4 — LLM Provider Abstraction

- [x] 4. Implement LLM providers
  - [x] 4.1 Create `src/chess_coach/llm/base.py` with `LLMProvider` ABC (`generate`, `is_available`) and `create_provider` factory
  - [x] 4.2 Create `src/chess_coach/llm/ollama.py` with `OllamaProvider`: POST to `/api/generate`, 120s timeout, error handling
  - [x] 4.3 Create `src/chess_coach/llm/openai.py` with `OpenAICompatProvider`: POST to `/v1/chat/completions`, 120s timeout
  - [x] 4.4 Create `src/chess_coach/llm/__init__.py` re-exporting `create_provider` and provider classes
  - [x] 4.5 Write tests for providers using httpx mock transport (test generate, is_available, error cases)

## Phase 5 — Prompt Engineering

- [x] 5. Implement prompt templates
  - [x] 5.1 Create `src/chess_coach/prompts.py` with `SYSTEM_PROMPT` (coaching persona), `build_coaching_prompt(analysis_text, level)` function
  - [x] 5.2 Implement three coaching levels: beginner (simple terms, tactics focus), intermediate (balanced), advanced (prophylaxis, pawn structure, long-term plans)
  - [x] 5.3 Cap response guidance at ~200 words in the prompt
  - [x] 5.4 Write tests verifying prompt construction includes analysis text and level-appropriate instructions

## Phase 6 — Coach Orchestrator

- [x] 6. Implement the Coach class
  - [x] 6.1 Create `src/chess_coach/coach.py` with `CoachingResponse` dataclass (fen, analysis, coaching_text, elapsed_ms) and `Coach` class
  - [x] 6.2 Implement `Coach.explain(fen, depth, level)`: calls analyzer → format → prompt → LLM → returns CoachingResponse
  - [x] 6.3 Implement `Coach.check()`: verifies engine is_ready and LLM is_available, returns status dict
  - [x] 6.4 Write tests for Coach using mocked engine and LLM (test explain pipeline, check success/failure)

## Phase 7 — CLI and Config

- [x] 7. Wire up the CLI with config loading
  - [x] 7.1 Implement config loading in `cli.py`: load `config.yaml`, merge CLI flags (--depth, --level, --config)
  - [x] 7.2 Implement `explain` command: parse FEN arg, create Coach, call explain, print coaching text
  - [x] 7.3 Implement `check` command: create Coach, call check, print status with clear pass/fail messages
  - [x] 7.4 Add `--depth`, `--level`, `--config` options to the CLI
  - [x] 7.5 Write integration tests for CLI using click.testing.CliRunner

## Phase 8 — Web UI

- [x] 8. Implement the web-based coaching interface
  - [x] 8.1 Add `fastapi`, `uvicorn`, and `jinja2` to `pyproject.toml` dependencies
  - [x] 8.2 Vendor `chessboard.js`, `chess.js`, and piece SVGs into `src/chess_coach/web/static/vendor/`
  - [x] 8.3 Create `src/chess_coach/web/server.py` with FastAPI app: `GET /` serves index.html, `POST /api/analyze` calls Coach.explain and returns JSON, `GET /api/health` calls Coach.check
  - [x] 8.4 Create `src/chess_coach/web/static/index.html` with layout: chessboard (left), coaching panel (right), FEN input, depth slider, level dropdown, analyze button
  - [x] 8.5 Create `src/chess_coach/web/static/app.js`: initialize chessboard.js board, wire FEN input to board sync, call `/api/analyze` on button click, render coaching text, draw best-move arrows on board
  - [x] 8.6 Create `src/chess_coach/web/static/style.css`: responsive layout, eval bar (vertical bar with white/black shading based on score), coaching panel styling, loading spinner
  - [x] 8.7 Add `serve` command to `cli.py`: load config, create Coach, start uvicorn on `localhost:8000` (port overridable with `--port`)
  - [x] 8.8 Write tests for the FastAPI endpoints using `httpx.AsyncClient` (test analyze, health, static file serving)

## Phase 8b — Play vs Engine

- [x] 10. Implement Play vs Engine backend
  - [ ] 10.1 Add `play(fen, depth, time_limit) -> str` method to `EngineProtocol` ABC and implement in `XboardEngine` (send `force`, `setboard`, `sd`/`st`, `go`, read `move <move>` response)
  - [ ] 10.2 Add `MoveEvaluation` and `PlayMoveResponse` dataclasses to `coach.py`
  - [ ] 10.3 Implement `Coach.evaluate_move(fen_before, user_move)`: analyze before/after positions, compute eval drop, classify as good (≤30cp) / inaccuracy (31–100cp) / blunder (>100cp), call LLM for feedback text
  - [ ] 10.4 Implement `Coach.explain_engine_move(fen_before, engine_move)`: analyze position, call LLM with engine-move-explanation prompt
  - [x] 10.5 Implement `Coach.play_move(fen, user_move)`: orchestrate evaluate_move → push user move → engine.play → explain_engine_move → return PlayMoveResponse
  - [x] 10.6 Add `MOVE_EVALUATION_PROMPT` and `ENGINE_MOVE_EXPLANATION_PROMPT` templates to `prompts.py`
  - [x] 10.7 Write unit tests for `evaluate_move` classification thresholds with mocked engine
  - [x] 10.8 Write property tests for move classification consistency (hypothesis, 100+ iterations)

- [x] 11. Implement Play vs Engine API endpoints
  - [x] 11.1 Add `POST /api/play/move` endpoint to `server.py`: accepts `{fen, user_move}`, validates with python-chess, calls `Coach.play_move`, returns `PlayMoveResponse` as JSON
  - [x] 11.2 Add `POST /api/play/new` endpoint: accepts `{color}`, returns starting FEN; if color is black, calls `engine.play` for the engine's first move and includes coaching
  - [x] 11.3 Add `POST /api/play/undo` endpoint: accepts `{fen, moves}`, replays all but last two moves from starting position, returns truncated state with eval
  - [x] 11.4 Add game-over detection to play/move response (checkmate, stalemate, draw)
  - [x] 11.5 Write tests for play endpoints using `httpx.AsyncClient` (test move, new, undo, invalid input, game over)

- [x] 12. Implement Play vs Engine frontend
  - [x] 12.1 Add mode toggle (Analyze / Play) to `index.html` and wire up in `app.js` to show/hide the appropriate UI panels
  - [x] 12.2 Add color picker UI (Play as White / Play as Black) and new game button
  - [x] 12.3 Implement play-mode move handler in `app.js`: on piece drop, POST to `/api/play/move`, animate engine response, update board state
  - [x] 12.4 Display user move feedback badge (good ✓ / inaccuracy ?! / blunder ??) and coaching text for engine moves
  - [x] 12.5 Implement move list panel: numbered moves in standard notation, current move highlighted, auto-scroll
  - [x] 12.6 Implement undo button: POST to `/api/play/undo`, update board and move list
  - [x] 12.7 Implement new game flow: color selection → POST to `/api/play/new` → reset board; if playing Black, animate engine's first move
  - [x] 12.8 Update eval bar to refresh after every move in play mode
  - [x] 12.9 Add play-mode styles to `style.css`: move list panel, feedback badges, mode toggle, transitions
  - [x] 12.10 Write property tests for undo round-trip and reset-to-start (hypothesis, 100+ iterations)

## Phase 9 — Polish and Documentation

- [ ] 9. Documentation and final polish
  - [ ] 9.1 Write `README.md` with installation, quickstart (CLI and web UI), configuration reference, and recommended models
  - [ ] 9.2 Add docstrings to all public classes and functions
  - [ ] 9.3 Run full test suite, mypy, ruff format, ruff check — all clean
  - [ ] 9.4 Verify end-to-end: `chess-coach check`, `chess-coach explain <FEN>`, and `chess-coach serve` with a real engine and Ollama

## Phase 10 — UCI Protocol Migration

- [ ] 13. Migrate from Xboard to UCI protocol
  - [ ] 13.1 Implement `UciEngine(EngineProtocol)` using Blunder's UCI support
  - [ ] 13.2 Add MultiPV support to retrieve top N candidate moves per position
  - [ ] 13.3 Update config to default to `protocol: uci`
  - [ ] 13.4 Update README and config examples to reflect UCI as the default
