# Implementation Plan: Engine Coaching Protocol

## Overview

Incrementally build the coaching protocol integration: data models first, then protocol parsing and the CoachingEngine adapter, then prompt templates, and finally Coach pipeline branching. Each step builds on the previous, with property-based tests validating correctness properties from the design.

## Tasks

- [-] 1. Create data models and error hierarchy
  - [x] 1.1 Create `src/chess_coach/models.py` with all coaching data models
    - Define frozen dataclasses: `EvalBreakdown`, `HangingPiece`, `Threat`, `PawnFeatures`, `KingSafety`, `TacticalMotif`, `ThreatMapEntry`, `PVLine`, `PositionReport`, `ComparisonReport`
    - Each dataclass gets `to_dict()` and `from_dict()` class methods for JSON round-tripping
    - Define error hierarchy: `CoachingProtocolError`, `CoachingTimeoutError`, `CoachingParseError`, `CoachingValidationError`, `EngineTerminatedError`
    - Define `validate_position_report(data: dict) -> PositionReport` and `validate_comparison_report(data: dict) -> ComparisonReport` functions that check required keys, types, and nested structure, raising `CoachingValidationError` with the offending field name on failure
    - _Requirements: 2.2, 3.1, 3.2, 3.3, 3.4, 4.2, 6.1, 6.2, 6.3, 10.4, 11.1, 12.1, 12.2, 14.1, 14.2_

  - [ ]* 1.2 Write property tests for PositionReport round-trip serialization
    - **Property 1: PositionReport round-trip serialization**
    - Create `tests/test_models.py` with Hypothesis strategies for all sub-models (`st_eval_breakdown`, `st_hanging_piece`, `st_threat`, `st_pawn_features`, `st_king_safety`, `st_tactical_motif`, `st_threat_map_entry`, `st_pv_line`, `st_position_report`)
    - Test: `PositionReport.from_dict(report.to_dict()) == report` for all generated reports
    - **Validates: Requirements 2.2, 2.4, 3.4, 3.5**

  - [ ]* 1.3 Write property tests for ComparisonReport round-trip serialization
    - **Property 2: ComparisonReport round-trip serialization**
    - Add `st_comparison_report` strategy to `tests/test_models.py`
    - Test: `ComparisonReport.from_dict(report.to_dict()) == report` for all generated reports
    - **Validates: Requirements 4.1, 4.2**

  - [ ]* 1.4 Write property test for blunder classification requires refutation line
    - **Property 6: Blunder classification requires refutation line**
    - Test: for any ComparisonReport where `classification == "blunder"`, `refutation_line` is a non-empty list; for non-blunder, `refutation_line` may be None or empty
    - **Validates: Requirements 4.4**

  - [ ]* 1.5 Write property test for ThreatMapEntry net_attacked invariant
    - **Property 11: ThreatMapEntry net_attacked invariant**
    - Test: for any ThreatMapEntry with a piece, `net_attacked` is True iff opposing attackers > own defenders
    - **Validates: Requirements 12.3**

  - [ ]* 1.6 Write property test for critical_moment implies critical_reason
    - **Property 12: critical_moment implies critical_reason**
    - Test: for any PositionReport, `critical_moment == True` implies `critical_reason` is a non-empty string; `critical_moment == False` implies `critical_reason is None`
    - **Validates: Requirements 14.1, 14.2**

- [x] 2. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [-] 3. Implement NAG mapping and coaching command formatting
  - [x] 3.1 Add `compute_nag(eval_drop_cp: int, user_move: str, best_move: str) -> str` function to `src/chess_coach/models.py`
    - Implement NAG threshold mapping: `!!` (brilliant), `!` (≤10cp), `!?` (11-30cp), `?!` (31-100cp), `?` (101-300cp), `??` (>300cp)
    - When `user_move == best_move`, return `!` or `!!` regardless of eval drop
    - _Requirements: 10.1, 10.2, 10.3_

  - [ ]* 3.2 Write property test for NAG threshold mapping
    - **Property 7: NAG threshold mapping**
    - Create `tests/test_nag.py`
    - Test: for any integer eval_drop, the computed NAG matches the threshold rules; for any case where user_move == best_move, NAG is `!` or `!!`
    - **Validates: Requirements 10.2, 10.3**

  - [x] 3.3 Add coaching command formatting helpers to `src/chess_coach/models.py` or a new section in `engine.py`
    - `format_coaching_command(cmd_type: str, **params) -> str` — formats `coach eval fen <FEN> multipv <N>`, `coach compare fen <FEN> move <MOVE>`, `coach ping`
    - _Requirements: 1.1, 2.1, 4.1, 13.3_

  - [ ]* 3.4 Write property test for coaching command formatting
    - **Property 5: Coaching command formatting**
    - Create `tests/test_coaching_protocol.py`
    - Test: for any command type and valid params, the formatted string is a single line starting with `coach ` followed by the command type
    - **Validates: Requirements 1.1, 2.1, 4.1**

- [-] 4. Implement protocol response parsing and version checking
  - [x] 4.1 Add response marker extraction and JSON parsing logic
    - Implement `parse_coaching_response(lines: list[str]) -> dict` that extracts JSON between `BEGIN_COACH_RESPONSE` / `END_COACH_RESPONSE` markers, parses the envelope, checks `protocol` field, and returns the `data` dict
    - Raise `CoachingParseError` with raw text for malformed JSON
    - _Requirements: 1.2, 6.3_

  - [ ]* 4.2 Write property test for response marker extraction
    - **Property 3: Response marker extraction**
    - Add to `tests/test_coaching_protocol.py`
    - Test: for any JSON-serializable dict, wrapping in markers and parsing yields the original dict
    - **Validates: Requirements 1.2**

  - [ ]* 4.3 Write property test for malformed JSON raises parse error with raw text
    - **Property 10: Malformed JSON raises parse error with raw text**
    - Test: for any non-JSON string wrapped in markers, parsing raises `CoachingParseError` whose message contains the raw text
    - **Validates: Requirements 6.3**

  - [x] 4.4 Add version compatibility checking logic
    - Implement `check_version_compatibility(engine_version: str, expected_version: str) -> str` returning `"compatible"`, `"compatible_warning"`, or `"incompatible"`
    - Different major → incompatible; different minor (engine > expected) → warning; same major, patch-only → compatible
    - _Requirements: 15.4_

  - [ ]* 4.5 Write property test for version compatibility logic
    - **Property 13: Version compatibility logic**
    - Add to `tests/test_coaching_protocol.py`
    - Test: for any two semver strings, compatibility result matches the rules
    - **Validates: Requirements 15.4**

  - [ ]* 4.6 Write property test for schema validation rejects invalid data
    - **Property 4: Schema validation rejects invalid data**
    - Add to `tests/test_coaching_protocol.py`
    - Test: for any dict missing a required PositionReport field or with wrong type, `validate_position_report()` raises `CoachingValidationError` mentioning the offending field
    - **Validates: Requirements 3.1, 3.2**

- [x] 5. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [-] 6. Implement CoachingEngine class
  - [x] 6.1 Add `CoachingEngine` class to `src/chess_coach/engine.py`
    - Implement `__init__` accepting `path`, `args`, `coaching_timeout`, `ping_timeout`; create inner `UciEngine` instance
    - Implement `EngineProtocol` interface methods (`start`, `stop`, `analyze`, `is_ready`, `play`) by delegating to inner `UciEngine`
    - Implement `start()` to call inner engine start, then `_probe_coaching_protocol()` to send `coach ping` and set `coaching_available`
    - Implement `_send_coaching_command(cmd: str) -> dict` that writes to stdin, reads lines until `END_COACH_RESPONSE` or timeout, parses response via `parse_coaching_response()`
    - Implement `get_position_report(fen, multipv=3) -> PositionReport` and `get_comparison_report(fen, user_move) -> ComparisonReport`
    - Handle timeout (`CoachingTimeoutError`), process death (`EngineTerminatedError`), and ensure engine remains usable after errors
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.3, 4.1, 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.2, 6.3, 6.4, 15.4_

  - [ ]* 6.2 Write unit tests for CoachingEngine
    - Create `tests/test_coaching_engine.py`
    - Test startup handshake with mock engine process (coaching available and unavailable paths)
    - Test `coaching_available` property reflects ping result
    - Test UCI delegation (analyze, play, is_ready delegate to inner engine)
    - Test timeout handling (mock engine that never sends END_COACH_RESPONSE)
    - Test process death detection (mock engine that exits mid-command)
    - Test recovery after timeout/parse error (engine remains usable)
    - _Requirements: 1.3, 1.4, 5.1, 5.2, 5.3, 5.5, 6.1, 6.2, 6.4_

- [-] 7. Implement rich prompt templates
  - [x] 7.1 Add rich prompt templates to `src/chess_coach/prompts.py`
    - Add `RICH_COACHING_PROMPT` template for position explanation with labeled sections for each PositionReport field
    - Add `RICH_MOVE_EVALUATION_PROMPT` template for move evaluation with ComparisonReport fields
    - Add `build_rich_coaching_prompt(report: PositionReport, level: str) -> str` that formats the template, omitting empty sections (no threats, no hanging pieces, no tactics)
    - Add `build_rich_move_evaluation_prompt(report: ComparisonReport, level: str) -> str` that formats the template, omitting empty missed_tactics and null refutation_line
    - Both templates instruct the LLM to explain provided data, not add its own analysis
    - When `critical_moment` is True, include language requesting more detailed explanation
    - _Requirements: 7.2, 8.1, 8.2, 8.3, 8.4, 11.4, 12.4, 14.3_

  - [ ]* 7.2 Write property test for rich position prompt completeness and omission
    - **Property 8: Rich position prompt completeness and omission**
    - Create `tests/test_coaching_prompts.py`
    - Test: for any PositionReport, the formatted prompt contains labeled sections for non-empty fields and omits sections for empty fields; critical_moment=True triggers detailed explanation language
    - **Validates: Requirements 7.2, 8.1, 8.3, 11.4, 12.4, 14.3**

  - [ ]* 7.3 Write property test for rich move evaluation prompt completeness
    - **Property 9: Rich move evaluation prompt completeness**
    - Add to `tests/test_coaching_prompts.py`
    - Test: for any ComparisonReport, the formatted prompt contains user move, best move, eval drop, classification, NAG, best_move_idea; missed_tactics present when non-empty; refutation_line present when non-null
    - **Validates: Requirements 8.2**

- [-] 8. Integrate coaching protocol into Coach pipeline
  - [x] 8.1 Update `src/chess_coach/coach.py` with branching logic
    - Update `Coach.__init__` to detect if engine is a `CoachingEngine` with `coaching_available`
    - Update `explain()`: when coaching available, call `engine.get_position_report(fen)` → `build_rich_coaching_prompt()` → LLM; otherwise existing flow
    - Update `evaluate_move()`: when coaching available, call `engine.get_comparison_report(fen, move)` → `build_rich_move_evaluation_prompt()` → LLM (single engine round-trip replaces two UCI analyses); otherwise existing flow
    - Update `play_move()`: when coaching available, use `get_comparison_report()` for user move eval + `engine.play()` for engine response + `get_position_report()` for engine move explanation; otherwise existing flow
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 9.1, 9.2, 9.3, 14.3_

  - [ ]* 8.2 Write unit tests for Coach pipeline integration
    - Create `tests/test_coach_integration.py`
    - Test `explain()` uses rich prompt when coaching available, existing prompt when not
    - Test `evaluate_move()` uses comparison report when coaching available, two UCI analyses when not
    - Test `play_move()` branching for coaching available vs UCI fallback
    - Mock `CoachingEngine` with `coaching_available=True/False` to test both paths
    - _Requirements: 7.1, 7.3, 7.4_

- [x] 9. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- The protocol specification document (`docs/coaching-protocol.md`) already exists — tasks reference it but do not recreate it
- Each property test references a specific correctness property from the design document
- All 13 correctness properties are covered across the test sub-tasks
- Checkpoints at tasks 2, 5, and 9 ensure incremental validation
