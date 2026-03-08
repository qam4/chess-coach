# Requirements Document

## Introduction

Chess Coach currently relies on the LLM to interpret raw engine output (a single centipawn score and a principal variation line) and infer positional features like material balance, king safety, hanging pieces, and pawn structure. This is slow (15-30s per LLM call), hallucination-prone, and fundamentally backwards — the engine already knows these things but doesn't expose them.

This feature extends the Blunder chess engine with a custom coaching protocol that runs alongside UCI over the same stdin/stdout pipe. Blunder responds to `coach` commands with structured JSON containing rich evaluation breakdowns. On the chess-coach side, a new `CoachingEngine` adapter consumes this data and feeds it to the LLM, which then only needs to explain the analysis in plain English rather than derive it from scratch.

The result: faster responses, more accurate coaching, and an LLM that acts as a communicator rather than a chess analyst.

## Glossary

- **Coaching_Protocol**: A set of custom commands (prefixed with `coach`) sent over stdin/stdout alongside standard UCI commands, with JSON responses delimited by markers
- **CoachingEngine**: A Python class in chess-coach that extends EngineProtocol to send coaching protocol commands and parse JSON responses
- **UCI**: Universal Chess Interface — the standard protocol for communicating with chess engines
- **Blunder**: The chess engine owned by the user, which will be extended with coaching protocol support
- **Coach_Pipeline**: The orchestration layer in chess-coach (the `Coach` class) that coordinates engine analysis, coaching data, and LLM explanation
- **Position_Report**: A structured JSON object returned by Blunder containing rich evaluation data for a position (material balance, king safety, threats, pawn structure, piece activity)
- **FEN**: Forsyth-Edwards Notation — a standard string format describing a chess position
- **Eval_Breakdown**: A decomposition of the engine's overall centipawn evaluation into component scores (material, mobility, king safety, pawn structure)
- **Hanging_Piece**: A piece that is attacked but not adequately defended
- **Threat**: An immediate tactical danger such as a check, capture, fork, pin, or skewer
- **Tactical_Motif**: A labeled tactical pattern detected in the position or PV lines (fork, pin, skewer, discovered attack, back-rank threat, etc.)
- **Threat_Map**: A per-square summary of attack and defense counts for each side, indicating which pieces attack/defend each square
- **NAG**: Numeric Annotation Glyph — standard chess move annotations (!, !?, ?!, ?, ??, !!) derived from eval deltas
- **Critical_Moment**: A position where the eval is volatile (large swings between candidate moves), indicating the position demands precise play
- **Protocol_Specification**: A versioned document defining the coaching protocol commands, JSON schemas, and response formats, shared between the chess-coach and Blunder projects as the coordination contract

## Requirements

### Requirement 1: Coaching Protocol Command Dispatch

**User Story:** As a developer, I want the CoachingEngine to send custom `coach` commands over the same stdin/stdout pipe used for UCI, so that I can get rich evaluation data without a separate communication channel.

#### Acceptance Criteria

1. WHEN a coaching command is sent, THE CoachingEngine SHALL write the command to the engine process's stdin as a single line prefixed with `coach `
2. WHEN a coaching command is sent, THE CoachingEngine SHALL read the response by consuming lines from stdout until a defined end-of-response marker is received
3. WHEN a standard UCI command is sent, THE CoachingEngine SHALL delegate to the existing UCI command handling without modification
4. THE CoachingEngine SHALL implement the EngineProtocol interface so that existing Coach_Pipeline code can use the CoachingEngine as a drop-in replacement for UciEngine

### Requirement 2: Position Report Retrieval

**User Story:** As a developer, I want to request a full position report for any FEN, so that the coaching pipeline has rich structured data to pass to the LLM.

#### Acceptance Criteria

1. WHEN a valid FEN string is provided, THE CoachingEngine SHALL send a `coach eval fen <FEN>` command to Blunder and return a parsed Position_Report
2. THE Position_Report SHALL contain the following fields: overall eval in centipawns, Eval_Breakdown (material, mobility, king safety, pawn structure component scores), list of Hanging_Pieces for both sides, list of Threats for both sides, pawn structure features (isolated, doubled, passed pawns per side), king safety assessment per side, and the top principal variation lines
3. WHEN an invalid or unparseable FEN is provided, THE CoachingEngine SHALL raise a descriptive error without crashing the engine process
4. FOR ALL valid FEN strings, sending a `coach eval fen` command and parsing the JSON response, then serializing the Position_Report back to JSON and parsing again SHALL produce an equivalent Position_Report (round-trip property)

### Requirement 3: Position Report JSON Schema

**User Story:** As a developer, I want the Position_Report JSON to follow a well-defined schema, so that parsing is reliable and changes are caught early.

#### Acceptance Criteria

1. THE CoachingEngine SHALL validate incoming Position_Report JSON against a defined schema before returning the parsed object
2. WHEN the JSON response does not conform to the schema, THE CoachingEngine SHALL raise a validation error that includes the specific field or constraint that failed
3. THE Position_Report schema SHALL define types and required fields for: `eval_cp` (integer), `eval_breakdown` (object with `material`, `mobility`, `king_safety`, `pawn_structure` integer fields), `hanging_pieces` (object with `white` and `black` arrays), `threats` (object with `white` and `black` arrays), `pawn_structure` (object with `isolated`, `doubled`, `passed` arrays per side), `king_safety` (object with `white` and `black` assessments), and `top_lines` (array of PV line objects)
4. THE Position_Report parser SHALL serialize Position_Report objects back to valid JSON (pretty-printer)
5. FOR ALL valid Position_Report objects, parsing the JSON then serializing then parsing again SHALL produce an equivalent object (round-trip property)

### Requirement 4: Move Comparison Report

**User Story:** As a developer, I want to compare the user's move against the engine's top moves with rich context, so that the LLM can explain what the user missed without guessing.

#### Acceptance Criteria

1. WHEN a FEN and a user move in UCI notation are provided, THE CoachingEngine SHALL send a `coach compare fen <FEN> move <MOVE>` command and return a structured comparison report
2. THE comparison report SHALL contain: the user's move eval, the engine's best move eval, the eval drop, a classification (good, inaccuracy, mistake, blunder), and for each of the top engine moves, the key positional or tactical idea that makes the move strong
3. WHEN the user's move matches the engine's top move, THE comparison report SHALL indicate the move is the best or near-best choice with no "missed idea" section
4. WHEN the user's move is a blunder, THE comparison report SHALL include the refutation line (the opponent's best response that punishes the move)

### Requirement 5: Graceful Fallback to UCI

**User Story:** As a developer, I want the CoachingEngine to fall back to standard UCI analysis when coaching commands are unavailable, so that chess-coach works with any UCI engine, not just a coaching-enabled Blunder.

#### Acceptance Criteria

1. WHEN the CoachingEngine starts, THE CoachingEngine SHALL send a `coach ping` command to detect whether the engine supports the coaching protocol
2. WHEN the engine does not respond to `coach ping` within a configured timeout, THE CoachingEngine SHALL mark coaching protocol as unavailable and use UCI-only analysis for all subsequent requests
3. WHILE the coaching protocol is marked as unavailable, THE CoachingEngine SHALL use standard UCI `go depth` analysis and return AnalysisResult objects compatible with the existing pipeline
4. WHEN the coaching protocol is available, THE CoachingEngine SHALL prefer coaching commands over UCI for position evaluation
5. THE CoachingEngine SHALL expose a boolean property `coaching_available` indicating whether the connected engine supports the coaching protocol

### Requirement 6: Response Timeout and Error Handling

**User Story:** As a developer, I want robust timeout and error handling for coaching commands, so that a slow or misbehaving engine does not hang the coaching pipeline.

#### Acceptance Criteria

1. WHEN a coaching command does not receive an end-of-response marker within a configurable timeout (default 30 seconds), THE CoachingEngine SHALL abort the command and raise a timeout error
2. WHEN the engine process terminates unexpectedly during a coaching command, THE CoachingEngine SHALL detect the process exit, raise a descriptive error, and mark the engine as stopped
3. IF the engine returns malformed JSON in response to a coaching command, THEN THE CoachingEngine SHALL raise a parse error that includes the raw response text for debugging
4. WHEN a timeout or parse error occurs, THE CoachingEngine SHALL remain in a usable state for subsequent commands (no corrupted internal state)

### Requirement 7: Coach Pipeline Integration

**User Story:** As a coach pipeline developer, I want the Coach class to use Position_Report data when available, so that the LLM receives rich structured analysis instead of raw PV lines.

#### Acceptance Criteria

1. WHEN the CoachingEngine has coaching protocol available, THE Coach_Pipeline SHALL pass Position_Report data to the LLM prompt instead of the raw analysis text currently used
2. THE Coach_Pipeline SHALL use a new prompt template that presents Position_Report fields (material balance, threats, hanging pieces, pawn structure, king safety) as structured context for the LLM
3. WHEN the CoachingEngine falls back to UCI-only mode, THE Coach_Pipeline SHALL use the existing prompt templates and analysis formatting without modification
4. WHEN a Position_Report is available for move evaluation, THE Coach_Pipeline SHALL use the comparison report from Requirement 4 instead of computing eval drop from two separate UCI analyses

### Requirement 8: Prompt Template for Rich Engine Data

**User Story:** As a coach pipeline developer, I want prompt templates that present structured engine data clearly, so that the LLM explains rather than analyzes.

#### Acceptance Criteria

1. THE Coach_Pipeline SHALL include a prompt template for position explanation that presents each Position_Report section (material balance, piece activity, pawn structure, king safety, threats, hanging pieces) as labeled fields
2. THE Coach_Pipeline SHALL include a prompt template for move evaluation that presents the comparison report (user move vs best move, eval drop, missed ideas, refutation line) as labeled fields
3. WHEN the Position_Report contains no threats or hanging pieces, THE prompt template SHALL omit those sections rather than showing empty lists
4. THE prompt templates SHALL instruct the LLM to explain the provided analysis in plain language and explicitly prohibit the LLM from adding analysis not present in the engine data

### Requirement 9: Latency Improvement in Play Mode

**User Story:** As a player, I want faster coaching feedback during play mode, so that the game feels interactive rather than waiting minutes per move.

#### Acceptance Criteria

1. WHEN the coaching protocol is available, THE Coach_Pipeline SHALL retrieve a Position_Report and a comparison report in a single round of engine communication instead of performing two separate UCI analyses per move
2. WHEN the coaching protocol is available, THE Coach_Pipeline SHALL complete the engine data retrieval phase of move evaluation within 5 seconds for positions at depth 18 (excluding LLM call time)
3. WHEN the coaching protocol is available, THE LLM prompt for move evaluation SHALL be shorter than the current UCI-based prompt because the engine provides pre-computed classifications and ideas, reducing LLM processing time

### Requirement 10: NAG-Style Move Annotations

**User Story:** As a developer, I want the engine to provide standard chess move annotations (!, !?, ?!, ?, ??, !!), so that the UI can display granular move quality indicators without relying on the LLM.

#### Acceptance Criteria

1. THE comparison report from `coach compare` SHALL include a `nag` field containing the NAG symbol for the user's move, computed from the eval delta
2. THE NAG mapping SHALL use standard thresholds: `!!` (brilliant, finds only winning move in losing position), `!` (good, eval drop ≤ 10cp), `!?` (interesting, eval drop 11-30cp), `?!` (dubious, eval drop 31-100cp), `?` (mistake, eval drop 101-300cp), `??` (blunder, eval drop > 300cp)
3. WHEN the user's move is the engine's top choice, THE NAG SHALL be `!` or `!!` regardless of absolute eval
4. THE CoachingEngine SHALL expose NAG annotations as a string field on the comparison report dataclass

### Requirement 11: Tactical Motif Detection

**User Story:** As a developer, I want the engine to label tactical patterns it detects in a position, so that the LLM can name and explain specific tactics rather than guessing from PV lines.

#### Acceptance Criteria

1. THE Position_Report SHALL include a `tactics` field containing a list of detected Tactical_Motifs, each with a type label (fork, pin, skewer, discovered_attack, back_rank_threat, overloaded_piece), the squares and pieces involved, and whether it exists on the board now or appears in the PV
2. THE comparison report SHALL include a `missed_tactics` field listing any Tactical_Motifs present in the engine's best line that the user's move fails to exploit or defend against
3. WHEN no tactical motifs are detected, THE `tactics` and `missed_tactics` fields SHALL be empty arrays
4. THE prompt templates SHALL present detected tactics as labeled items (e.g., "Fork: Nc7 attacks Ra8 and Ke8") so the LLM explains them rather than discovers them

### Requirement 12: Threat Map

**User Story:** As a developer, I want the engine to provide a threat map showing which squares and pieces are attacked and defended, so that the LLM can explain danger zones and piece safety accurately.

#### Acceptance Criteria

1. THE Position_Report SHALL include a `threat_map` field containing per-square attack and defense counts for each side, limited to squares that are attacked or contain pieces
2. EACH threat_map entry SHALL include: the square (e.g., "f7"), the piece on it (if any), the number of white attackers, the number of black attackers, the number of white defenders, and the number of black defenders
3. THE threat_map SHALL flag squares where a piece is attacked more times than it is defended (net-attacked)
4. THE prompt templates SHALL use threat_map data to describe piece safety (e.g., "Your bishop on f5 is attacked twice and defended once")

### Requirement 13: MultiPV Top Lines

**User Story:** As a developer, I want the engine to return multiple principal variation lines in the Position_Report, so that the LLM can explain alternative plans and not just the single best move.

#### Acceptance Criteria

1. THE Position_Report `top_lines` field SHALL contain up to N principal variation lines (configurable, default 3), each with depth, eval in centipawns, and the move sequence in UCI notation
2. EACH top line SHALL include a `theme` field — a short label describing the strategic or tactical idea of the line (e.g., "kingside attack", "central pawn break", "piece exchange simplification")
3. THE `coach eval` command SHALL accept an optional `multipv <N>` parameter to control how many lines are returned
4. WHEN the engine cannot produce N distinct lines (e.g., forced positions), THE `top_lines` array SHALL contain as many lines as the engine found

### Requirement 14: Critical Moment Detection

**User Story:** As a developer, I want the engine to flag positions where the eval is volatile across candidate moves, so that the coaching pipeline can emphasize these positions as critical decision points.

#### Acceptance Criteria

1. THE Position_Report SHALL include a `critical_moment` boolean field that is true when the eval spread between the best move and the third-best move exceeds a threshold (default 100cp)
2. WHEN `critical_moment` is true, THE Position_Report SHALL include a `critical_reason` string describing why the position is critical (e.g., "large eval swing — one move wins, others lose material")
3. THE Coach_Pipeline SHALL use the `critical_moment` flag to adjust the LLM prompt, requesting more detailed explanation for critical positions and briefer feedback for routine positions
4. THE comparison report SHALL include a `critical_moment` field so that play-mode UI can visually highlight critical moves

### Requirement 15: Protocol Specification Document

**User Story:** As a developer working across both chess-coach and Blunder, I want a single versioned protocol specification document, so that both projects implement the same contract and changes are coordinated.

#### Acceptance Criteria

1. THE project SHALL include a `docs/coaching-protocol.md` document that defines all coaching protocol commands, their parameters, and their JSON response schemas
2. THE protocol specification SHALL include a version number (semver) that is incremented when commands or schemas change
3. THE protocol specification SHALL include example request/response pairs for each command (`coach ping`, `coach eval`, `coach compare`)
4. THE CoachingEngine SHALL validate that the engine's reported protocol version (returned by `coach ping`) is compatible with the version it expects, and log a warning if there is a mismatch
5. THE protocol specification SHALL serve as the shared contract between the chess-coach and Blunder repositories — changes to the protocol require updating this document first

