# Android Integration Guide

How to wrap chess-coach as an Android app.  The Android side is a
Kotlin/Java project that bundles the Python runtime, engine binary,
and assets into an APK.  A WebView points at the localhost server.

## Architecture

```
Android App
├── WebView → http://localhost:8361?mobile=1
├── Background Service
│   ├── Python runtime (Chaquopy)
│   ├── chess_coach.mobile_entry.start_server()
│   └── Blunder engine subprocess (ARM64)
└── Bundled Assets (APK)
    ├── blunder-android-arm64.zip
    ├── config.mobile.yaml
    ├── openings.json
    └── books/i-gm1950.bin
```

## Bundled Assets

The Android zip (`blunder-android-arm64.zip`, ~15MB) extracts to:

```
{FILES_DIR}/
├── engine/
│   └── blunder          # ARM64 ELF executable, ~1MB stripped
└── books/
    ├── i-gm1950.bin     # 19MB — GM games opening book (default)
    ├── k-stfish.bin     # 5.5MB — Stockfish-style book
    ├── n-larsen.bin     # 991KB — Larsen-style book
    └── openings.epd     # 23KB — opening positions
```

| Asset | Source | Extract to |
|-------|--------|------------|
| Engine zip | `blunder/build/mobile-dist/blunder-android-arm64.zip` | `{FILES_DIR}/` (unzip directly) |
| Config | `config.mobile.yaml` (this repo) | `{FILES_DIR}/config.yaml` |
| Openings DB | `src/chess_coach/data/openings.json` | Bundled in Python package (no extraction needed) |

`{FILES_DIR}` = `context.getFilesDir()` in Android.

## Server Entrypoint

The Android wrapper calls one function to start the server:

```python
from chess_coach.mobile_entry import start_server

# Blocks until shutdown — run in a background thread/service
start_server(
    config_path="/data/data/com.example.app/files/config.yaml",
    port=8361,
    app_data_dir="/data/data/com.example.app/files",
)
```

The `{APP_DATA}` placeholders in `config.mobile.yaml` are resolved
to `app_data_dir` at load time.  If `app_data_dir` is omitted, it
defaults to the directory containing the config file.

The entrypoint handles:
- Loading config with placeholder resolution
- Making the engine binary executable (chmod +x)
- Creating the engine, coach, and FastAPI app
- Starting uvicorn on localhost

## Config: config.mobile.yaml

```yaml
engine:
  path: "{APP_DATA}/engine/blunder"
  protocol: "uci"
  args: ["--uci"]
  depth: 8
  book: "{APP_DATA}/books/i-gm1950.bin"

llm:
  provider: "none"       # No LLM — template coaching only

coaching:
  level: intermediate
  top_moves: 3
  template_only: true    # Skip all LLM calls
```

## WebView Setup

```kotlin
webView.settings.javaScriptEnabled = true
webView.settings.domStorageEnabled = true
webView.settings.allowFileAccess = false
webView.loadUrl("http://127.0.0.1:8361?mobile=1")
```

The `?mobile=1` parameter tells the web UI to:
- Hide the LLM/template toggle (always template mode)
- Hide the debug panel
- Hide the analyze mode tab (play-only on mobile)

## App Lifecycle

```
onCreate()
  → Extract assets to FILES_DIR (first run / version upgrade only)
  → Start Python in background thread:
      mobile_entry.start_server(config_path, 8361, files_dir)
  → Poll http://127.0.0.1:8361/ until HTTP 200
  → Load WebView

onPause()
  → Keep server running (fast resume)

onDestroy()
  → Signal server shutdown (uvicorn.Server.should_exit = True)
  → Engine subprocess is cleaned up automatically
```

## First Launch: Asset Extraction

1. Unzip `blunder-android-arm64.zip` → `{FILES_DIR}/` (creates `engine/` and `books/` dirs)
2. Copy `config.mobile.yaml` → `{FILES_DIR}/config.yaml`
3. The Python entrypoint handles `chmod +x` on `engine/blunder`

Total extracted size: ~27MB (engine 1MB + books 26MB).
Skip extraction on subsequent launches (check a version marker file).

To save space, you could ship only `n-larsen.bin` (991KB) instead of
all three books. The config just needs the `book:` path updated.

## Python Runtime: Chaquopy (Recommended)

Add to `build.gradle`:

```groovy
plugins {
    id 'com.chaquo.python' version '15.0.1'
}

python {
    pip {
        install "chess-coach"  // or install from local wheel
    }
}
```

Chaquopy bundles CPython into the APK and handles pip dependencies.
Call Python from Kotlin via `Python.getInstance().getModule(...)`.

## Server API (existing, no changes needed)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web UI (HTML) |
| `/api/play/move/template` | POST | Play a move (template coaching) |
| `/api/play/new` | POST | Start new game |
| `/api/play/undo` | POST | Undo last move |
| `/api/play/strength` | POST | Set engine Elo |
| `/api/analyze/template` | POST | Analyze position (template) |

## Performance Expectations

| Component | Target | Notes |
|-----------|--------|-------|
| Cold start | <5s | Asset extraction cached |
| Server boot | <3s | Python import + engine start |
| Engine depth 8 | <3s | ARM64 Cortex-A76 class |
| Template coaching | <50ms | Pure Python |
| Touch response | <16ms | 60fps in WebView |
| Memory | <150MB | Python + engine + WebView |

## No Network Required

The app runs entirely offline:
- No LLM server needed (template-only mode)
- Server binds to 127.0.0.1 only
- No Android INTERNET permission required
- All assets bundled in APK
