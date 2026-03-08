# Coaching Protocol Specification

**Version:** 1.0.0
**Status:** Draft
**Last Updated:** 2025-07-14

## 1. Overview

The Coaching Protocol extends a UCI-compatible chess engine with custom commands for returning rich, structured evaluation data. Commands are sent over the same stdin/stdout pipe used for UCI. All coaching commands are prefixed with `coach` to avoid collision with standard UCI commands.

The engine MUST continue to support all standard UCI commands. Coaching commands are optional — an engine that does not support them simply ignores the `coach` prefix, and the client detects this via the `coach ping` handshake.

## 2. Transport

- **Channel**: stdin/stdout of the engine subprocess (same pipe as UCI)
- **Encoding**: UTF-8
- **Line termination**: `\n` (newline)
- **Direction**: Client → Engine via stdin, Engine → Client via stdout

### 2.1 Request Format

Each coaching command is a single line written to the engine's stdin:

```
coach <command> [parameters]\n
```

### 2.2 Response Format

Each coaching response is a block of lines on stdout delimited by markers:

```
BEGIN_COACH_RESPONSE
<single line of JSON>
END_COACH_RESPONSE
```

Rules:
- The JSON payload MUST be a single line (no embedded newlines)
- The markers MUST appear on their own lines with no leading/trailing whitespace
- The engine MAY emit UCI info lines or other output between the request and `BEGIN_COACH_RESPONSE` — the client MUST ignore non-marker lines while waiting for a coaching response
- The JSON payload is always wrapped in an envelope (see Section 2.3)

### 2.3 Response Envelope

Every JSON response follows this envelope structure:

```json
{
  "protocol": "coaching",
  "version": "1.0.0",
  "type": "<response_type>",
  "data": { ... }
}
```

| Field      | Type   | Description |
|------------|--------|-------------|
| `protocol` | string | Always `"coaching"` |
| `version`  | string | Semver version of the protocol the engine implements |
| `type`     | string | Response type: `"pong"`, `"position_report"`, `"comparison_report"` |
| `data`     | object | The response payload (schema depends on `type`) |

## 3. Commands

### 3.1 `coach ping` — Protocol Detection & Version Negotiation

Sent by the client at startup to detect coaching protocol support and negotiate version.

**Request:**
```
coach ping
```

**Response type:** `"pong"`

**Response `data` schema:**
```json
{
  "status": "ok",
  "engine_name": "<string>",
  "engine_version": "<string>"
}
```

| Field            | Type   | Required | Description |
|------------------|--------|----------|-------------|
| `status`         | string | yes      | Always `"ok"` |
| `engine_name`    | string | yes      | Engine identifier (e.g. `"Blunder"`) |
| `engine_version` | string | yes      | Engine build version (e.g. `"8.5.0"`) |

**Version negotiation:**
- The protocol version is in the envelope's `version` field
- The client compares the engine's major version against its expected major version
- **Same major version**: compatible (proceed)
- **Different major version**: incompatible (client should log a warning and disable coaching)
- Minor/patch differences are backward-compatible

**Timeout behavior:**
- If the engine does not respond with `BEGIN_COACH_RESPONSE` within 2 seconds, the client MUST assume coaching is not supported and fall back to UCI-only mode

**Example:**

Request:
```
coach ping
```

Response:
```
BEGIN_COACH_RESPONSE
{"protocol":"coaching","version":"1.0.0","type":"pong","data":{"status":"ok","engine_name":"Blunder","engine_version":"8.5.0"}}
END_COACH_RESPONSE
```


### 3.2 `coach eval` — Position Evaluation Report

Requests a full position evaluation with rich structured data.

**Request:**
```
coach eval fen <FEN> [multipv <N>]
```

| Parameter   | Type    | Required | Default | Description |
|-------------|---------|----------|---------|-------------|
| `fen`       | string  | yes      | —       | FEN string describing the position (all 6 fields) |
| `multipv`   | integer | no       | 3       | Number of principal variation lines to return |

**Response type:** `"position_report"`

**Response `data` schema:**

```json
{
  "fen": "<string>",
  "eval_cp": <integer>,
  "eval_breakdown": {
    "material": <integer>,
    "mobility": <integer>,
    "king_safety": <integer>,
    "pawn_structure": <integer>
  },
  "hanging_pieces": {
    "white": [
      {"square": "<string>", "piece": "<string>"}
    ],
    "black": [
      {"square": "<string>", "piece": "<string>"}
    ]
  },
  "threats": {
    "white": [
      {
        "type": "<string>",
        "source_square": "<string>",
        "target_squares": ["<string>"],
        "description": "<string>"
      }
    ],
    "black": [ ... ]
  },
  "pawn_structure": {
    "white": {
      "isolated": ["<string>"],
      "doubled": ["<string>"],
      "passed": ["<string>"]
    },
    "black": { ... }
  },
  "king_safety": {
    "white": {
      "score": <integer>,
      "description": "<string>"
    },
    "black": { ... }
  },
  "top_lines": [
    {
      "depth": <integer>,
      "eval_cp": <integer>,
      "moves": ["<string>"],
      "theme": "<string>"
    }
  ],
  "tactics": [
    {
      "type": "<string>",
      "squares": ["<string>"],
      "pieces": ["<string>"],
      "in_pv": <boolean>,
      "description": "<string>"
    }
  ],
  "threat_map": [
    {
      "square": "<string>",
      "piece": "<string or null>",
      "white_attackers": <integer>,
      "black_attackers": <integer>,
      "white_defenders": <integer>,
      "black_defenders": <integer>,
      "net_attacked": <boolean>
    }
  ],
  "critical_moment": <boolean>,
  "critical_reason": "<string or null>"
}
```

**Field reference:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `fen` | string | yes | The FEN that was evaluated |
| `eval_cp` | integer | yes | Overall evaluation in centipawns from side-to-move perspective. Positive = side to move is better. |
| `eval_breakdown` | object | yes | Component scores that sum to approximately `eval_cp` |
| `eval_breakdown.material` | integer | yes | Material balance in centipawns |
| `eval_breakdown.mobility` | integer | yes | Piece mobility score in centipawns |
| `eval_breakdown.king_safety` | integer | yes | King safety score in centipawns |
| `eval_breakdown.pawn_structure` | integer | yes | Pawn structure score in centipawns |
| `hanging_pieces` | object | yes | Pieces that are attacked but not adequately defended |
| `hanging_pieces.white` | array | yes | White's hanging pieces (may be empty `[]`) |
| `hanging_pieces.black` | array | yes | Black's hanging pieces (may be empty `[]`) |
| `hanging_pieces.*.square` | string | yes | Square in algebraic notation (e.g. `"f5"`) |
| `hanging_pieces.*.piece` | string | yes | Piece type: `"pawn"`, `"knight"`, `"bishop"`, `"rook"`, `"queen"` |
| `threats` | object | yes | Immediate tactical threats per side |
| `threats.white` | array | yes | Threats by white (may be empty `[]`) |
| `threats.black` | array | yes | Threats by black (may be empty `[]`) |
| `threats.*.type` | string | yes | One of: `"check"`, `"capture"`, `"fork"`, `"pin"`, `"skewer"`, `"discovered_attack"` |
| `threats.*.source_square` | string | yes | Square of the threatening piece |
| `threats.*.target_squares` | array | yes | Squares being threatened |
| `threats.*.description` | string | yes | Human-readable description (e.g. `"Nc3 forks Ra4 and e4 pawn"`) |
| `pawn_structure` | object | yes | Pawn structure features per side |
| `pawn_structure.white` | object | yes | White's pawn features |
| `pawn_structure.black` | object | yes | Black's pawn features |
| `pawn_structure.*.isolated` | array | yes | Files with isolated pawns (e.g. `["a", "d"]`) |
| `pawn_structure.*.doubled` | array | yes | Files with doubled pawns |
| `pawn_structure.*.passed` | array | yes | Files with passed pawns |
| `king_safety` | object | yes | King safety assessment per side |
| `king_safety.white` | object | yes | White king safety |
| `king_safety.black` | object | yes | Black king safety |
| `king_safety.*.score` | integer | yes | King safety component score in centipawns |
| `king_safety.*.description` | string | yes | Human-readable assessment (e.g. `"king exposed, missing g-pawn shield"`) |
| `top_lines` | array | yes | Top N principal variation lines |
| `top_lines.*.depth` | integer | yes | Search depth reached |
| `top_lines.*.eval_cp` | integer | yes | Evaluation in centipawns |
| `top_lines.*.moves` | array | yes | Move sequence in UCI notation (e.g. `["e2e4", "e7e5", "g1f3"]`) |
| `top_lines.*.theme` | string | yes | Short label for the line's idea (e.g. `"kingside attack"`, `"central pawn break"`) |
| `tactics` | array | yes | Detected tactical motifs (may be empty `[]`) |
| `tactics.*.type` | string | yes | One of: `"fork"`, `"pin"`, `"skewer"`, `"discovered_attack"`, `"back_rank_threat"`, `"overloaded_piece"` |
| `tactics.*.squares` | array | yes | Squares involved in the tactic |
| `tactics.*.pieces` | array | yes | Pieces involved (e.g. `["Nc7", "Ra8", "Ke8"]`) |
| `tactics.*.in_pv` | boolean | yes | `true` if motif appears in a PV line, `false` if on the board now |
| `tactics.*.description` | string | yes | Human-readable description (e.g. `"Fork: Nc7 attacks Ra8 and Ke8"`) |
| `threat_map` | array | yes | Per-square attack/defense counts (only squares that are attacked or contain pieces) |
| `threat_map.*.square` | string | yes | Square in algebraic notation |
| `threat_map.*.piece` | string/null | yes | Piece on the square, or `null` if empty |
| `threat_map.*.white_attackers` | integer | yes | Number of white pieces attacking this square |
| `threat_map.*.black_attackers` | integer | yes | Number of black pieces attacking this square |
| `threat_map.*.white_defenders` | integer | yes | Number of white pieces defending this square |
| `threat_map.*.black_defenders` | integer | yes | Number of black pieces defending this square |
| `threat_map.*.net_attacked` | boolean | yes | `true` if the piece on this square is attacked more times than defended by its own side |
| `critical_moment` | boolean | yes | `true` when eval spread between best and 3rd-best move exceeds 100cp |
| `critical_reason` | string/null | yes | Reason string when `critical_moment` is `true`, `null` otherwise |

**Error handling:**
- If the FEN is invalid, the engine SHOULD respond with an error envelope (see Section 4)
- If the engine cannot evaluate the position (e.g. game over), it SHOULD return a report with `eval_cp: 0` and empty arrays

**Example:**

Request:
```
coach eval fen rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1 multipv 2
```

Response:
```
BEGIN_COACH_RESPONSE
{"protocol":"coaching","version":"1.0.0","type":"position_report","data":{"fen":"rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1","eval_cp":-35,"eval_breakdown":{"material":0,"mobility":-15,"king_safety":0,"pawn_structure":-20},"hanging_pieces":{"white":[],"black":[]},"threats":{"white":[],"black":[]},"pawn_structure":{"white":{"isolated":[],"doubled":[],"passed":[]},"black":{"isolated":[],"doubled":[],"passed":[]}},"king_safety":{"white":{"score":0,"description":"king safe behind pawns"},"black":{"score":0,"description":"king safe behind pawns"}},"top_lines":[{"depth":18,"eval_cp":-35,"moves":["e7e5","g1f3","b8c6","f1b5"],"theme":"open game, central control"},{"depth":18,"eval_cp":-30,"moves":["c7c5","g1f3","d7d6"],"theme":"Sicilian Defense, counterattack"}],"tactics":[],"threat_map":[],"critical_moment":false,"critical_reason":null}}
END_COACH_RESPONSE
```

### 3.3 `coach compare` — Move Comparison Report

Compares a user's move against the engine's top moves with rich context.

**Request:**
```
coach compare fen <FEN> move <MOVE>
```

| Parameter | Type   | Required | Description |
|-----------|--------|----------|-------------|
| `fen`     | string | yes      | FEN string of the position before the move |
| `move`    | string | yes      | The user's move in UCI notation (e.g. `"e2e4"`, `"e7e8q"`) |

**Response type:** `"comparison_report"`

**Response `data` schema:**

```json
{
  "fen": "<string>",
  "user_move": "<string>",
  "user_eval_cp": <integer>,
  "best_move": "<string>",
  "best_eval_cp": <integer>,
  "eval_drop_cp": <integer>,
  "classification": "<string>",
  "nag": "<string>",
  "best_move_idea": "<string>",
  "refutation_line": ["<string>"] | null,
  "missed_tactics": [
    {
      "type": "<string>",
      "squares": ["<string>"],
      "pieces": ["<string>"],
      "in_pv": <boolean>,
      "description": "<string>"
    }
  ],
  "top_lines": [
    {
      "depth": <integer>,
      "eval_cp": <integer>,
      "moves": ["<string>"],
      "theme": "<string>"
    }
  ],
  "critical_moment": <boolean>,
  "critical_reason": "<string or null>"
}
```

**Field reference:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `fen` | string | yes | The position that was evaluated |
| `user_move` | string | yes | The user's move in UCI notation |
| `user_eval_cp` | integer | yes | Evaluation after the user's move (from side-to-move perspective before the move) |
| `best_move` | string | yes | Engine's best move in UCI notation |
| `best_eval_cp` | integer | yes | Evaluation of the best move |
| `eval_drop_cp` | integer | yes | `best_eval_cp - user_eval_cp` (always ≥ 0) |
| `classification` | string | yes | One of: `"good"`, `"inaccuracy"`, `"mistake"`, `"blunder"` |
| `nag` | string | yes | NAG symbol: `"!!"`, `"!"`, `"!?"`, `"?!"`, `"?"`, `"??"` |
| `best_move_idea` | string | yes | Human-readable explanation of why the best move is strong |
| `refutation_line` | array/null | yes | Opponent's best response sequence punishing the user's move. Non-null and non-empty when `classification` is `"blunder"`. `null` otherwise. |
| `missed_tactics` | array | yes | Tactical motifs in the engine's best line that the user's move fails to exploit (may be empty `[]`) |
| `top_lines` | array | yes | Engine's top N lines for context (same schema as position_report top_lines) |
| `critical_moment` | boolean | yes | Whether this position is a critical decision point |
| `critical_reason` | string/null | yes | Reason string when critical, `null` otherwise |

**NAG mapping:**

The `nag` field is computed from `eval_drop_cp` using these thresholds:

| NAG | Name | Condition |
|-----|------|-----------|
| `!!` | Brilliant | User finds the only winning move in a losing/equal position |
| `!` | Good | `eval_drop_cp ≤ 10` |
| `!?` | Interesting | `11 ≤ eval_drop_cp ≤ 30` |
| `?!` | Dubious | `31 ≤ eval_drop_cp ≤ 100` |
| `?` | Mistake | `101 ≤ eval_drop_cp ≤ 300` |
| `??` | Blunder | `eval_drop_cp > 300` |

Special case: when `user_move == best_move`, the NAG is `!` or `!!` regardless of absolute eval.

**Classification mapping:**

| Classification | Condition |
|----------------|-----------|
| `good` | `eval_drop_cp ≤ 30` |
| `inaccuracy` | `31 ≤ eval_drop_cp ≤ 100` |
| `mistake` | `101 ≤ eval_drop_cp ≤ 300` |
| `blunder` | `eval_drop_cp > 300` |

**Example — good move:**

Request:
```
coach compare fen rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1 move e2e4
```

Response:
```
BEGIN_COACH_RESPONSE
{"protocol":"coaching","version":"1.0.0","type":"comparison_report","data":{"fen":"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1","user_move":"e2e4","user_eval_cp":35,"best_move":"e2e4","best_eval_cp":35,"eval_drop_cp":0,"classification":"good","nag":"!","best_move_idea":"Controls the center and opens lines for the bishop and queen","refutation_line":null,"missed_tactics":[],"top_lines":[{"depth":18,"eval_cp":35,"moves":["e2e4","e7e5","g1f3","b8c6"],"theme":"open game, central control"},{"depth":18,"eval_cp":30,"moves":["d2d4","d7d5","c2c4"],"theme":"Queen's Gambit, central pawn tension"}],"critical_moment":false,"critical_reason":null}}
END_COACH_RESPONSE
```

**Example — blunder:**

Request:
```
coach compare fen r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4 move d2d3
```

Response:
```
BEGIN_COACH_RESPONSE
{"protocol":"coaching","version":"1.0.0","type":"comparison_report","data":{"fen":"r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4","user_move":"d2d3","user_eval_cp":-150,"best_move":"h5f7","best_eval_cp":20000,"eval_drop_cp":20150,"classification":"blunder","nag":"??","best_move_idea":"Scholar's mate: Qxf7# is checkmate","refutation_line":["g8h6","c1h6","g7h6"],"missed_tactics":[{"type":"back_rank_threat","squares":["f7"],"pieces":["Qh5","Bc4"],"in_pv":true,"description":"Qxf7# delivers checkmate — the f7 pawn is only defended by the king"}],"top_lines":[{"depth":18,"eval_cp":20000,"moves":["h5f7"],"theme":"Scholar's mate, immediate checkmate"}],"critical_moment":true,"critical_reason":"One move wins immediately (checkmate), all others lose the advantage"}}
END_COACH_RESPONSE
```

## 4. Error Responses

When the engine encounters an error processing a coaching command, it SHOULD respond with an error envelope:

```
BEGIN_COACH_RESPONSE
{"protocol":"coaching","version":"1.0.0","type":"error","data":{"code":"<error_code>","message":"<description>"}}
END_COACH_RESPONSE
```

**Error codes:**

| Code | Description |
|------|-------------|
| `invalid_fen` | The provided FEN string could not be parsed |
| `invalid_move` | The provided move is not legal in the given position |
| `internal_error` | An unexpected error occurred in the engine |

**Example:**

Request:
```
coach eval fen not-a-valid-fen
```

Response:
```
BEGIN_COACH_RESPONSE
{"protocol":"coaching","version":"1.0.0","type":"error","data":{"code":"invalid_fen","message":"Could not parse FEN: 'not-a-valid-fen'"}}
END_COACH_RESPONSE
```

## 5. Protocol Versioning

This protocol uses [Semantic Versioning](https://semver.org/):

- **Major** version: incremented for breaking changes (removed fields, changed semantics, renamed commands)
- **Minor** version: incremented for backward-compatible additions (new optional fields, new commands)
- **Patch** version: incremented for clarifications or documentation fixes

The current version is **1.0.0**.

### Compatibility Rules

| Client expects | Engine reports | Result |
|----------------|---------------|--------|
| 1.0.0 | 1.0.0 | ✅ Fully compatible |
| 1.0.0 | 1.0.1 | ✅ Fully compatible (patch) |
| 1.0.0 | 1.1.0 | ✅ Compatible (engine has additions client ignores) |
| 1.0.0 | 2.0.0 | ❌ Incompatible (client should disable coaching) |
| 2.0.0 | 1.0.0 | ❌ Incompatible (client should disable coaching) |

## 6. Implementation Notes

### For Engine Implementors (Blunder)

1. **Command parsing**: Split the input line on spaces. First token is `coach`, second is the command name, remaining tokens are key-value parameters.
2. **JSON output**: Use compact JSON (no pretty-printing) for the single-line payload between markers.
3. **Interleaving with UCI**: The engine may receive `coach` commands at any time, including between UCI commands. Process them synchronously — the client waits for `END_COACH_RESPONSE` before sending the next command.
4. **Unknown commands**: If the engine receives a `coach` command it doesn't recognize, respond with an error envelope (`code: "unknown_command"`).
5. **Thread safety**: Coaching commands and UCI commands share the same stdin/stdout. The client guarantees it will not send a coaching command while a UCI `go` search is in progress.
6. **Eval perspective**: All `eval_cp` values are from the side-to-move perspective. Positive means the side to move is better.
7. **Move notation**: All moves in `moves`, `user_move`, `best_move`, and `refutation_line` fields use UCI notation (e.g. `"e2e4"`, `"e7e8q"` for promotion).

### For Client Implementors (chess-coach)

1. **Handshake order**: Send `uci` → wait for `uciok` → send `isready` → wait for `readyok` → send `coach ping` → wait for response or timeout.
2. **Timeout**: Use a 2-second timeout for `coach ping` and a configurable timeout (default 30s) for `coach eval` and `coach compare`.
3. **Fallback**: If `coach ping` times out, set `coaching_available = False` and never send coaching commands for this session.
4. **Marker parsing**: Read lines from stdout. Ignore any line that is not `BEGIN_COACH_RESPONSE`. Once `BEGIN_COACH_RESPONSE` is seen, the next line is the JSON payload, and the line after that must be `END_COACH_RESPONSE`.
5. **Validation**: Validate the JSON against the expected schema before using the data. Check the envelope `protocol` and `version` fields.
