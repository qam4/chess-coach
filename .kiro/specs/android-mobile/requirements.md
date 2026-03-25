# Requirements: Android Mobile App

## Overview

Package chess-coach as an Android app that runs entirely on-device.
The app bundles the Blunder engine (ARM64 binary), the Python runtime
with chess-coach, and the web UI. A WebView wraps the existing
localhost web server. No LLM required — template-based coaching only.

The user installs an APK, opens the app, and plays chess with coaching.
No terminal, no config files, no external dependencies.

## User Stories

### 1. One-Tap Launch
As a mobile user, I want to open the app and immediately see the
chessboard so I can start playing without any setup.

#### Acceptance Criteria
- 1.1 The app starts the FastAPI server and engine in the background on launch
- 1.2 The WebView loads the UI once the server is ready
- 1.3 A splash/loading screen shows while the server boots (expected: 2-5s)
- 1.4 If the engine binary fails to start, a clear error message is shown

### 2. Touch-Friendly Board
As a mobile user, I want to move pieces by tapping and dragging on the
touchscreen so I can play comfortably on a phone.

#### Acceptance Criteria
- 2.1 The chessboard fills the screen width with no horizontal scrolling
- 2.2 Pieces can be moved by touch-drag (already supported by chessboard.js)
- 2.3 The coaching panel scrolls below the board (not beside it)
- 2.4 All buttons and controls are large enough for touch (min 44px tap targets)
- 2.5 The eval bar is visible alongside the board without crowding

### 3. Template-Only Coaching (No LLM)
As a mobile user, I want instant coaching feedback without needing an
LLM server running, so the app works standalone.

#### Acceptance Criteria
- 3.1 Template mode ("Quick mode") is enabled by default and cannot be toggled off
- 3.2 The LLM toggle checkbox is hidden in mobile mode
- 3.3 Coaching text is generated from templates (instant, no network calls)
- 3.4 All coaching features work: eval summary, threats, hanging pieces,
      opening detection, move classification, best move explanation

### 4. Bundled Engine Binary
As a mobile user, I want the chess engine included in the app so I
don't need to install anything separately.

#### Acceptance Criteria
- 4.1 The Blunder ARM64 binary is bundled as an APK asset
- 4.2 On first launch, the binary is extracted to app-private storage
      and made executable
- 4.3 The opening book (.bin file) is also bundled and extracted
- 4.4 The engine starts via subprocess stdin/stdout pipes (same as desktop)
- 4.5 Engine depth defaults to 8 for mobile (fast enough for interactive play)

### 5. Offline Operation
As a mobile user, I want the app to work completely offline since
everything runs on-device.

#### Acceptance Criteria
- 5.1 No network permissions required in the Android manifest
- 5.2 All assets (JS, CSS, images, opening book) are bundled locally
- 5.3 The FastAPI server binds to localhost only

### 6. App Lifecycle Management
As a mobile user, I want the app to handle backgrounding and
resumption gracefully.

#### Acceptance Criteria
- 6.1 The engine process is stopped when the app goes to background
- 6.2 The engine process is restarted when the app returns to foreground
- 6.3 The current game state is preserved across background/foreground cycles
- 6.4 The server shuts down cleanly when the app is closed

### 7. Reasonable APK Size
As a mobile user, I want the app to be a reasonable download size.

#### Acceptance Criteria
- 7.1 Target APK size under 50MB (engine ~5MB, Python runtime ~20-30MB,
      assets ~5MB)
- 7.2 NNUE weight files (if any) are embedded in the engine binary,
      not shipped as separate large files

### 8. Mobile-Optimized Performance
As a mobile user, I want the engine to respond quickly without
draining my battery.

#### Acceptance Criteria
- 8.1 Engine analysis completes in under 5 seconds at depth 8 on
      a mid-range phone (Snapdragon 600-series or equivalent)
- 8.2 Template coaching generation is under 50ms
- 8.3 The engine does not run continuously — only when analyzing or
      playing a move
- 8.4 CPU usage drops to near zero when idle (waiting for user input)
