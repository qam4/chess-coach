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

## Play vs Engine (User Story 8)

### Overview

Play mode lets the user play a full game against the engine in the web UI,
with real-time coaching after every move. The user picks a color, makes moves
on the board, and the engine responds. After each move (user or engine), the
coach provides commentary: move evaluation for user moves, explanation for
engine moves.

### Architecture

Play mode adds a new vertical slice through the existing stack:

```
Frontend (app.js)                    Backend (server.py → Coach)
─────────────────                    ────────────────────────────
mode toggle ──┐
color picker ──┤
               │  POST /api/play/move   ┌─────────────────────┐
user move ─────┼───────────────────────►│ Coach.play_move()   │
               │  {fen, user_move}      │  1. push user move  │
               │                        │  2. evaluate_move() │
               │  ◄─────────────────────│  3. engine thinks   │
               │  {engine_move,         │  4. explain move    │
               │   coaching, eval,      │  5. return response │
               │   user_feedback}       └─────────────────────┘
               │
               │  POST /api/play/new
new game ──────┼───────────────────────► reset state, return starting FEN
               │
               │  POST /api/play/undo
undo ──────────┼───────────────────────► pop last move pair, return position
```

### Backend Changes

#### engine.py — New `play_move` method on `EngineProtocol`

The existing `analyze()` enters Xboard analyze mode. For play mode, we need
the engine to *choose* a move. In Xboard protocol this means:

1. `force` — put engine in force mode
2. `setboard <fen>` — set the position
3. `st <seconds>` or `sd <depth>` — set time/depth limit
4. `go` — engine thinks and emits a `move <move>` line

```python
class EngineProtocol(ABC):
    # ... existing methods ...

    @abstractmethod
    def play(self, fen: str, depth: int = 18,
             time_limit: float | None = None) -> str:
        """Return the engine's chosen move in coordinate notation."""
        ...

class XboardEngine(EngineProtocol):
    def play(self, fen: str, depth: int = 18,
             time_limit: float | None = None) -> str:
        self._send("force")
        self._send(f"setboard {fen}")
        if time_limit:
            self._send(f"st {int(time_limit)}")
        else:
            self._send(f"sd {depth}")
        self._send("go")
        # Read until we get "move <move>"
        deadline = time.monotonic() + (time_limit or depth * 2.0)
        while time.monotonic() < deadline:
            line = self._read_line(timeout=1.0)
            if line and line.startswith("move "):
                return line.split()[1]
        raise TimeoutError("Engine did not return a move")
```

#### coach.py — New methods

```python
@dataclass
class MoveEvaluation:
    """Evaluation of a user's move."""
    classification: str  # "good", "inaccuracy", "blunder"
    eval_before_cp: int
    eval_after_cp: int
    eval_drop_cp: int
    feedback: str  # LLM-generated feedback

@dataclass
class PlayMoveResponse:
    """Response from a play_move call."""
    engine_move: str       # SAN notation
    engine_move_uci: str   # UCI/coordinate notation
    coaching_text: str     # Why the engine played this move
    user_feedback: str     # Evaluation of the user's move
    user_classification: str  # good / inaccuracy / blunder
    eval_cp: int           # Eval after engine's move
    eval_score: str        # Human-readable score string

class Coach:
    # ... existing methods ...

    def play_move(self, fen: str, user_move: str) -> PlayMoveResponse:
        """Process a user move and get the engine's response with coaching.

        1. Evaluate the user's move (compare eval before/after)
        2. Apply the user's move to get the new position
        3. Have the engine play its response
        4. Analyze the position after the engine's move
        5. Generate coaching text explaining the engine's move
        """
        ...

    def evaluate_move(self, fen_before: str, user_move: str) -> MoveEvaluation:
        """Classify a user move as good, inaccuracy, or blunder.

        Thresholds (centipawns, from side-to-move perspective):
        - good: eval drop ≤ 30 cp
        - inaccuracy: eval drop 31–100 cp
        - blunder: eval drop > 100 cp
        """
        ...

    def explain_engine_move(self, fen_before: str, engine_move: str) -> str:
        """Generate coaching text explaining why the engine chose this move."""
        ...
```

The `evaluate_move` method:
1. Analyzes the position before the user's move (gets eval_before)
2. Pushes the user's move, analyzes the new position (gets eval_after)
3. Computes eval_drop = eval_before - eval_after (from the user's perspective)
4. Classifies based on thresholds
5. Calls the LLM with a move-evaluation prompt to generate feedback

The `explain_engine_move` method:
1. Analyzes the position after the engine's move
2. Calls the LLM with a move-explanation prompt

#### prompts.py — New prompt templates

Two new prompt templates:

- `MOVE_EVALUATION_PROMPT`: Given the position, the user's move, and the eval
  drop, ask the LLM to explain whether the move was good or what was missed.
- `ENGINE_MOVE_EXPLANATION_PROMPT`: Given the position and the engine's move,
  ask the LLM to explain the idea behind the move.

Both prompts respect the coaching level setting.

#### web/server.py — New endpoints

```
POST /api/play/move
  Request:  { "fen": "<FEN>", "user_move": "<UCI move>" }
  Response: { "engine_move": "Nf3", "engine_move_uci": "g1f3",
              "coaching_text": "...", "user_feedback": "...",
              "user_classification": "good",
              "eval_cp": 35, "eval_score": "+0.35" }

POST /api/play/new
  Request:  { "color": "white" | "black" }
  Response: { "fen": "<starting FEN>",
              "engine_move": null | "e2e4",  // if user is Black
              "coaching_text": null | "..." }

POST /api/play/undo
  Request:  { "fen": "<current FEN>", "moves": ["e2e4", "e7e5", ...] }
  Response: { "fen": "<FEN after removing last move pair>",
              "moves": ["e2e4"],  // truncated move list
              "eval_cp": 20, "eval_score": "+0.20" }
```

The undo endpoint receives the full move list and replays all but the last
two moves (user move + engine response) from the starting position. This is
stateless — the server doesn't track game state; the client sends everything
needed.

### Frontend Changes

#### app.js — Play mode state

New state variables:
- `mode`: `"analysis"` | `"play"` — controls which UI panel is active
- `playerColor`: `"white"` | `"black"`
- `gameMoves`: array of `{ uci, san, fen }` objects — full move history
- `gameChess`: a `chess.js` Game instance tracking the play-mode position

Mode toggle:
- Switching to play mode hides the FEN input and analyze button, shows the
  color picker, new game button, undo button, and move list panel.
- Switching to analysis mode restores the original UI.

Move handling in play mode:
1. User drops a piece → `chess.js` validates the move
2. If legal, POST to `/api/play/move` with current FEN and the UCI move
3. On response: animate the engine's move on the board, display coaching
   text, display user feedback, update eval bar, append to move list
4. If the game is over (checkmate/stalemate/draw), display the result

Move list panel:
- Displayed to the right of the coaching panel (or below on narrow screens)
- Standard chess notation: `1. e4 e5 2. Nf3 Nc6 ...`
- Current move highlighted

Undo:
- Sends the move list to `/api/play/undo`
- Receives the truncated position, updates board and move list

New game:
- Prompts for color choice, POSTs to `/api/play/new`
- If user chose Black, the engine moves first and the response includes
  the engine's opening move + coaching

#### index.html — New UI elements

- Mode toggle (radio buttons or tab bar): "Analyze" | "Play"
- Color picker (shown when starting a new game): "Play as White" | "Play as Black"
- Move list panel (scrollable, alongside the board)
- Undo button
- New Game button
- User feedback badge (good ✓ / inaccuracy ?! / blunder ??) shown briefly after each user move

#### style.css — Play mode styles

- Move list panel styling (numbered moves, current move highlight)
- User feedback badge colors (green/yellow/red)
- Mode toggle styling
- Transition animations for mode switching

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

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Color choice determines first mover

*For any* color choice (white or black), when a new game is started, the engine should make the first move if and only if the user chose to play as Black.

**Validates: Requirements 8.2**

### Property 2: Engine returns a legal move

*For any* valid chess position where it is the engine's turn, calling `play()` should return a move that is legal in that position according to the rules of chess.

**Validates: Requirements 8.3**

### Property 3: Play move response completeness

*For any* valid position and legal user move, the `play_move()` response should include a legal engine move (SAN and UCI), non-empty coaching text explaining the engine's move, non-empty user feedback text, a move classification string that is one of "good"/"inaccuracy"/"blunder", and a numeric eval score.

**Validates: Requirements 8.4, 8.9**

### Property 4: Move classification consistency with eval thresholds

*For any* eval_before and eval_after values (in centipawns), the move classification should be deterministic: "good" when eval drop ≤ 30 cp, "inaccuracy" when eval drop is 31–100 cp, and "blunder" when eval drop > 100 cp. The classification function should be a pure function of the eval difference.

**Validates: Requirements 8.5**

### Property 5: Undo restores previous position

*For any* game state with at least one move pair (user move + engine response), undoing should restore the board to the FEN that existed before the user's last move, and the move list should shrink by exactly two entries.

**Validates: Requirements 8.6**

### Property 6: Reset produces starting position

*For any* game state (regardless of how many moves have been played), resetting the game should produce the standard chess starting position FEN and an empty move list.

**Validates: Requirements 8.7**

### Property 7: Move list tracks game history

*For any* sequence of N legal moves played in a game, the move list should contain exactly N entries, each with the correct SAN notation, in the order they were played.

**Validates: Requirements 8.8**

## Error Handling

- **Engine timeout during play**: If the engine doesn't return a move within
  the configured time limit, the `/api/play/move` endpoint returns a 504 with
  a clear error message. The frontend displays the error and the user can retry.
- **Invalid user move**: The frontend validates moves client-side with `chess.js`.
  The backend also validates with `python-chess` and returns 400 if the move is
  illegal (defense in depth).
- **LLM failure during coaching**: If the LLM is unreachable, the engine move
  is still returned with empty coaching text and a flag indicating the LLM was
  unavailable. The game continues — coaching is best-effort.
- **Game over detection**: After each move, the backend checks for checkmate,
  stalemate, draw by repetition, 50-move rule, and insufficient material.
  The response includes a `game_over` flag and `result` string when applicable.

## Testing Strategy

### Unit Tests

- `test_play_move_classification`: Verify that specific eval drops map to the
  correct classification (e.g., drop of 10 → good, drop of 50 → inaccuracy,
  drop of 150 → blunder).
- `test_play_new_game_white`: Start a new game as white, verify starting FEN
  and no engine move in response.
- `test_play_new_game_black`: Start a new game as black, verify engine makes
  the first move.
- `test_play_undo_no_moves`: Verify undo with no moves returns an error.
- `test_play_game_over_detection`: Verify checkmate/stalemate positions are
  correctly detected.
- `test_play_move_endpoint_invalid_fen`: Verify 400 response for malformed FEN.
- `test_play_move_endpoint_illegal_move`: Verify 400 response for illegal moves.

### Property-Based Tests

Use `hypothesis` (Python property-based testing library). Each test runs a
minimum of 100 iterations.

- **Feature: chess-coaching-mvp, Property 2: Engine returns a legal move** —
  Generate random valid FENs, call `engine.play()`, verify the returned move
  is in the position's legal move set.
- **Feature: chess-coaching-mvp, Property 4: Move classification consistency** —
  Generate random pairs of (eval_before, eval_after) integers, verify the
  classification matches the threshold rules deterministically.
- **Feature: chess-coaching-mvp, Property 5: Undo restores previous position** —
  Generate a random sequence of moves from the starting position, apply undo,
  verify the FEN matches the position before the last move pair.
- **Feature: chess-coaching-mvp, Property 6: Reset produces starting position** —
  Generate a random sequence of moves, call reset, verify the result is the
  standard starting FEN with an empty move list.
- **Feature: chess-coaching-mvp, Property 7: Move list tracks game history** —
  Generate a random sequence of N legal moves, verify the move list has exactly
  N entries in the correct order.

Each property test is tagged with a comment referencing the design property:
```python
# Feature: chess-coaching-mvp, Property 4: Move classification consistency
@given(eval_before=st.integers(-3000, 3000), eval_after=st.integers(-3000, 3000))
def test_classification_consistency(eval_before, eval_after):
    ...
```

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
