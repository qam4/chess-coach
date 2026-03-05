# Requirements: Chess Coaching MVP

## Overview

A chess coaching tool that combines engine analysis with LLM-powered natural
language explanations. The user provides a chess position (FEN), the engine
analyzes it, and an LLM explains what's happening, what the best plan is,
and why the top moves are good — in plain English adapted to the user's level.

## User Stories

### 1. Single Position Coaching
As a chess player, I want to paste a FEN string and get a natural language
explanation of the position so I understand what's happening and what to do.

#### Acceptance Criteria
- 1.1 The CLI accepts a FEN string and returns coaching text
- 1.2 The coaching text explains who stands better and why
- 1.3 The coaching text explains the best plan for the side to move
- 1.4 The coaching text explains the top move in plain language
- 1.5 Response time is under 15 seconds on a machine with a GPU

### 2. Configurable Analysis Depth
As a user, I want to control how deep the engine analyzes so I can trade
speed for accuracy.

#### Acceptance Criteria
- 2.1 The config file has a depth setting (default: 18)
- 2.2 The CLI has a --depth flag that overrides the config
- 2.3 Higher depth produces more accurate analysis at the cost of time

### 3. Coaching Level Adaptation
As a beginner, I want simpler explanations; as an advanced player, I want
nuanced positional analysis.

#### Acceptance Criteria
- 3.1 Three coaching levels: beginner, intermediate, advanced
- 3.2 The config file has a level setting (default: intermediate)
- 3.3 The CLI has a --level flag that overrides the config
- 3.4 Beginner explanations use simple terms and focus on tactics/piece safety
- 3.5 Advanced explanations discuss prophylaxis, pawn structure, long-term plans

### 4. Pluggable LLM Backend
As a developer, I want to swap LLM providers without changing application
code so I can use whichever model runs best on my hardware.

#### Acceptance Criteria
- 4.1 LLM provider is selected via config.yaml (provider field)
- 4.2 Ollama provider works out of the box with local models
- 4.3 OpenAI-compatible provider works with llama.cpp server, vLLM, LM Studio
- 4.4 Adding a new provider requires only implementing the LLMProvider interface
- 4.5 The system reports a clear error if the LLM is not reachable

### 5. Pluggable Engine Backend
As a developer, I want to swap chess engines without changing application
code so I can use Blunder, Stockfish, or any Xboard/UCI engine.

#### Acceptance Criteria
- 5.1 Engine binary path and protocol are configured in config.yaml
- 5.2 Xboard protocol is supported (MVP)
- 5.3 UCI protocol is supported (post-MVP, when Blunder adds UCI)
- 5.4 Engine is managed as a subprocess with clean startup/shutdown
- 5.5 Engine thinking output is parsed into structured AnalysisLine objects

### 6. Health Check
As a user, I want to verify that the engine and LLM are properly configured
before trying to analyze a position.

#### Acceptance Criteria
- 6.1 `chess-coach check` verifies the engine binary exists
- 6.2 `chess-coach check` verifies the LLM provider is reachable
- 6.3 `chess-coach check` verifies the configured model is available
- 6.4 Clear error messages indicate what's wrong and how to fix it

### 7. Web UI
As a chess player, I want a browser-based interface with an interactive
chessboard so I can visually explore positions and read coaching advice
alongside the board instead of copy-pasting FEN strings in a terminal.

#### Acceptance Criteria
- 7.1 `chess-coach serve` starts a local web server (default: localhost:8000)
- 7.2 The UI displays an interactive chessboard (drag-and-drop pieces, click-to-move)
- 7.3 The user can paste a FEN or set up a position on the board
- 7.4 Clicking "Analyze" sends the position to the backend and displays coaching text
- 7.5 An eval bar shows the engine's score visually
- 7.6 Best move arrows are drawn on the board for the top engine lines
- 7.7 Coaching level and depth are selectable in the UI
- 7.8 The UI works in any modern browser (Chrome, Firefox, Edge, Safari)
- 7.9 All processing remains local — the server only binds to localhost

### 8. Play vs Engine (Web UI)
As a chess player, I want to play a game against the engine in the web UI
so I can practice and get real-time coaching on my moves.

#### Acceptance Criteria
- 8.1 A "Play" mode toggle switches the UI from analysis mode to play mode
- 8.2 The user chooses to play as White or Black
- 8.3 The engine responds to user moves within the configured time/depth limit
- 8.4 After each engine move, the coach automatically explains why the engine played that move
- 8.5 After each user move, the coach comments on whether it was good, inaccurate, or a blunder
- 8.6 The user can undo their last move
- 8.7 The game can be reset or a new game started at any time
- 8.8 The move list is displayed alongside the board
- 8.9 The eval bar updates after every move

### 9. PGN Game Review (Future)
As a chess player, I want to load a PGN game and get coaching for each
critical position so I can review my games and learn from mistakes.

#### Acceptance Criteria
- 9.1 The CLI accepts a PGN file path
- 9.2 The tool identifies critical positions (large eval swings, blunders)
- 9.3 Each critical position gets a coaching explanation
- 9.4 Output is formatted as an annotated game

### 10. Interactive Mode (Future)
As a chess player, I want an interactive session where I can ask follow-up
questions about a position.

#### Acceptance Criteria
- 10.1 The CLI has an interactive mode (REPL)
- 10.2 The user can set a position, get coaching, then ask follow-up questions
- 10.3 The LLM maintains conversation context within a session
- 10.4 The user can navigate forward/backward through a game

### 11. Open Source LLM Requirement
As the project owner, I want all LLM models used to be open source with
permissive licenses (Apache 2.0 or equivalent) so there are no royalty
or legal issues.

#### Acceptance Criteria
- 11.1 Default model recommendation is Apache 2.0 licensed (Qwen3-8B)
- 11.2 Documentation lists recommended models with their licenses
- 11.3 No proprietary API keys are required for the default setup
- 11.4 All inference runs locally — no data leaves the user's machine
