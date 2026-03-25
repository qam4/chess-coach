# Tasks: Android Mobile App

## Phase 1 — Mobile-Responsive Web UI

- [x] 1. Make the web UI work well on phone screens
  - [x] 1.1 Add `@media (max-width: 480px)` breakpoint to `style.css` with phone-specific layout: board fills width, panels stack vertically, larger tap targets (min 44px), compact header
  - [x] 1.2 Make the chessboard fluid-width on mobile: CSS `width: calc(100vw - 56px)` (viewport minus eval bar and padding), matching `height` via `aspect-ratio: 1`
  - [x] 1.3 Add `ResizeObserver` in `app.js` to call `board.resize()` when the board container size changes (needed for fluid-width board)
  - [x] 1.4 Stack move list panel and coaching panel below the board on narrow screens with full-width layout
  - [x] 1.5 Make modal buttons (color picker) full-width and stacked on narrow screens for easier touch
  - [x] 1.6 Ensure eval bar stays beside the board but thinner (16px) on mobile
  - [x] 1.7 Test on Chrome DevTools mobile emulator: iPhone SE (375px), Pixel 5 (393px), Galaxy S21 (360px)

## Phase 2 — Template-Only Mobile Mode

- [x] 2. Support running without any LLM
  - [x] 2.1 Add `NoneProvider` class to `src/chess_coach/llm/` that returns empty strings from `generate()` and `False` from `is_available()`; register `"none"` in the provider factory
  - [x] 2.2 Add `template_only` flag to coaching config; when `True`, skip all LLM calls in `Coach.explain()`, `Coach.evaluate_move()`, and `Coach.explain_engine_move()` — use template output only
  - [x] 2.3 Detect `?mobile=1` query parameter in `app.js`; when present, hide the template toggle checkbox and the debug panel
  - [x] 2.4 Write unit tests for `NoneProvider` (generate returns empty, is_available returns False)
  - [x] 2.5 Write test that `Coach` with `template_only=True` produces coaching text without any LLM calls

## Phase 3 — Mobile Config and Entrypoint

- [x] 3. Create mobile-specific config and server entrypoint
  - [x] 3.1 Create `config.mobile.yaml` with engine depth 8, `provider: "none"`, `template_only: true`, and `{APP_DATA}` placeholders for engine and book paths
  - [x] 3.2 Create `src/chess_coach/mobile_entry.py` with `start_server(config_path, port)` function that loads config, creates Coach, starts uvicorn; blocks until shutdown signal
  - [x] 3.3 Add config path placeholder resolution: replace `{APP_DATA}` in config values with a provided base directory at load time
  - [x] 3.4 Write test that `mobile_entry.start_server()` boots, responds to `/api/health`, and shuts down cleanly

## Phase 4 — Integration and Documentation

- [x] 4. Verify everything works together and document the Android interface
  - [x] 4.1 Run full test suite (`pytest`) — all existing tests must pass, no regressions
  - [x] 4.2 Run type checker (`mypy src/`) — clean
  - [x] 4.3 Run linter (`ruff check src/ tests/`) — clean
  - [x] 4.4 Create `docs/android-integration.md` documenting: asset list (engine binary, book, config), server entrypoint API, WebView setup, lifecycle management, and the interface contract between the Android wrapper and chess-coach
  - [x] 4.5 Add Android/mobile section to IDEAS.md tracking future mobile improvements (native UI, LLM on-device, etc.)
