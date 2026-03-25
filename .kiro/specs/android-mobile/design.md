# Design: Android Mobile App

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│              Android App (Kotlin)                │
│                                                  │
│  ┌──────────────────────────────────────────┐    │
│  │           WebView Activity               │    │
│  │     loads http://localhost:PORT           │    │
│  │     (existing web UI, unchanged)         │    │
│  └──────────────┬───────────────────────────┘    │
│                 │                                 │
│  ┌──────────────▼───────────────────────────┐    │
│  │        Background Service                │    │
│  │  1. Extract engine + assets on first run │    │
│  │  2. Start Python + FastAPI server        │    │
│  │  3. Manage engine subprocess lifecycle   │    │
│  └──────────────────────────────────────────┘    │
│                                                  │
│  ┌──────────────────────────────────────────┐    │
│  │          Bundled Assets (APK)            │    │
│  │  - blunder-arm64 (engine binary)         │    │
│  │  - Python runtime (Chaquopy / embedded)  │    │
│  │  - chess-coach Python package            │    │
│  │  - web/static/* (HTML, JS, CSS, images)  │    │
│  │  - openings.json + opening book .bin     │    │
│  │  - config.mobile.yaml                    │    │
│  └──────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
```

## Component Design

### 1. Chess-Coach Changes (this repo)

Changes needed in chess-coach to support mobile deployment. These are
the tasks we own. The Android app wrapper is a separate project.

#### 1a. Mobile-Responsive CSS

The existing `@media (max-width: 900px)` breakpoint is a start but
needs significant improvement for phone screens (320-430px wide).

Key changes:
- Board fills viewport width minus eval bar and padding
- Coaching panel moves below the board (vertical scroll)
- Move list panel moves below the board, above coaching
- Controls use full width with larger tap targets (min 44px)
- Header shrinks (smaller title, compact mode toggle)
- FEN input gets a smaller font and wraps properly
- Modal buttons are full-width stacked on narrow screens
- Eval bar stays beside the board but thinner (16px)

New breakpoint: `@media (max-width: 480px)` for phone-specific rules.

#### 1b. Board Resize on Viewport Change

chessboard.js needs `board.resize()` called when the container size
changes. Add a `ResizeObserver` on the board container in `app.js`
so the board adapts to the viewport dynamically. This is needed
because the CSS makes the board fluid-width on mobile.

#### 1c. Mobile Config Preset

A `config.mobile.yaml` that the Android wrapper uses:

```yaml
engine:
  path: "{APP_DATA}/blunder-arm64"
  protocol: "uci"
  depth: 8
  book: "{APP_DATA}/i-gm1950.bin"

llm:
  provider: "none"

coaching:
  level: intermediate
  top_moves: 3
  template_only: true
```

The `{APP_DATA}` placeholder is resolved at runtime by the Android
wrapper to the app's private files directory.

The `provider: "none"` setting means no LLM is loaded. The coach
falls back to template-only mode automatically.

#### 1d. LLM Provider "none"

Add a `NoneProvider` to `llm/` that always returns empty strings
and reports `is_available() = False`. When `provider: "none"` is
configured, the coach uses template-only mode without attempting
any HTTP connections.

#### 1e. Mobile Mode Detection in Web UI

The server passes a `mobile` flag to the frontend (via a query
parameter or a `/api/config` endpoint). When in mobile mode:
- The template toggle checkbox is hidden (always on)
- The debug panel is hidden
- The FEN input in analyze mode uses a more compact layout

Detection: the Android wrapper adds `?mobile=1` to the WebView URL,
or the server sets it based on config (`template_only: true`).

#### 1f. Server Startup Entrypoint

A clean Python entrypoint that the Android wrapper calls:

```python
# chess_coach.mobile_entry
def start_server(config_path: str, port: int = 8000) -> None:
    """Start the FastAPI server for mobile use.

    Blocks until the server is stopped. The Android wrapper calls
    this from a background thread/service.
    """
```

This avoids the CLI layer (click) and directly boots the server
with the mobile config. Returns a way to signal shutdown.

### 2. Android Wrapper (separate repo)

This section documents the interface contract so the Android side
knows what to build. We don't implement this — it's the other repo.

#### 2a. Asset Extraction

On first launch (or version upgrade), extract from APK assets:
- `blunder-arm64` → `{filesDir}/blunder-arm64`, chmod +x
- `i-gm1950.bin` → `{filesDir}/i-gm1950.bin`
- `config.mobile.yaml` → `{filesDir}/config.yaml`
  (replace `{APP_DATA}` with actual `filesDir` path)

#### 2b. Python Runtime

Options (in order of recommendation):
1. **Chaquopy** — Gradle plugin, bundles CPython in the APK,
   pip-installs chess-coach and dependencies at build time.
   Easiest path. Supports calling Python from Kotlin/Java.
2. **BeeWare/Briefcase** — packages Python apps for Android.
   More standalone but less flexible for WebView integration.
3. **Termux bootstrap** — bundle a minimal Termux environment.
   Heaviest option, most flexible.

#### 2c. Server Lifecycle

```
App.onCreate()
  → extract assets (if first run)
  → start Python in background thread:
      chess_coach.mobile_entry.start_server(config_path, port)
  → poll localhost:PORT/api/health until ready
  → load WebView with http://localhost:PORT?mobile=1

App.onPause()
  → (optional) keep server running for quick resume

App.onDestroy()
  → signal server shutdown
  → kill engine subprocess
```

#### 2d. WebView Configuration

```kotlin
webView.settings.javaScriptEnabled = true
webView.settings.domStorageEnabled = true
webView.settings.allowFileAccess = false  // all via localhost
webView.loadUrl("http://localhost:$port?mobile=1")
```

### 3. Interface Contract

The chess-coach server exposes these endpoints (already existing):
- `GET /` — web UI
- `POST /api/analyze` — position analysis
- `POST /api/play/move` — play a move
- `POST /api/play/new` — new game
- `POST /api/play/undo` — undo last move
- `GET /api/health` — server health check

The Android wrapper only needs to:
1. Start the Python server process
2. Wait for `/api/health` to return 200
3. Point a WebView at `http://localhost:PORT`

No custom Android↔Python bridge needed. The WebView talks to the
server over HTTP, same as a desktop browser.

## Performance Budget

| Component | Target | Notes |
|-----------|--------|-------|
| App cold start | <5s | Asset extraction cached after first run |
| Server boot | <3s | Python import + engine start |
| Engine analysis (depth 8) | <3s | ARM64, single position |
| Template coaching | <50ms | Pure Python string formatting |
| Board interaction | <16ms | 60fps touch response (JS) |
| Memory usage | <150MB | Python ~80MB + engine ~30MB + WebView ~40MB |

## Testing Strategy

### Chess-Coach Side (this repo)

- Existing test suite must pass (no regressions)
- New tests for `NoneProvider` (returns empty, is_available=False)
- New tests for mobile config loading (template_only flag)
- Manual testing of responsive CSS on Chrome DevTools mobile emulator
  (iPhone SE 375px, Pixel 5 393px, Galaxy S21 360px)
- Test `mobile_entry.start_server()` boots and responds to health check

### Android Side (other repo)

- Asset extraction works on fresh install
- Server starts and health check passes
- WebView loads and board is interactive
- Touch drag-and-drop works for piece movement
- App survives background/foreground cycle
- Clean shutdown on app close
