# Blunder Engine — Improvement Requests from Chess-Coach

Issues and feature requests observed while integrating Blunder with
chess-coach via the coaching protocol. Ordered roughly by impact.

## Bugs / Calibration Issues

### BLUNDER-001: Eval breakdown doesn't sum to overall eval ✅ FIXED

- **Fixed (2026-03-16)**: Blunder now computes eval_cp as the sum of
  breakdown components. New fields `tempo` and `piece_bonuses` added.
  After 1.e4: eval_cp=0, breakdown=-24+-24+15+5+28+0=0. Matches.
- **Chess-coach**: EvalBreakdown dataclass already supports the new
  fields with defaults for backward compatibility.

### BLUNDER-002: Mobility score seems miscalibrated ✅ IMPROVED

- **Previously**: Mobility was -240cp after 1.e4 — wildly dominant.
- **Now (2026-03-16)**: Mobility is -24cp after 1.e4 — much more
  reasonable and proportional to other components.
- **Status**: Mostly fixed. No longer dominates the eval breakdown.

### BLUNDER-003: Only 1 PV line returned despite multipv 3 ✅ FIXED

- **Fixed (2026-03-16)**: MultiPV now returns all requested lines with
  actual moves, independent depths, and eval scores. Root causes were
  TT cutoff at root and abort flag not reset between PV iterations.

## Fixed Issues

### BLUNDER-009: "Pawn storm detected" false positive ✅ FIXED

- **Previously**: After 1.e4, king safety said "pawn storm detected."
- **Now**: Says "king uncastled, still has castling rights, missing
  e-pawn shield" — accurate, no false pawn storm.

### BLUNDER-007: King safety description is static ✅ IMPROVED

- **Previously**: Always said "king partially sheltered, missing
  e-pawn shield" regardless of position.
- **Now**: Descriptions are more position-aware — "king uncastled,
  still has castling rights" vs "king displaced to e2" etc.

### UCI_LimitStrength / UCI_Elo / Skill ✅ ADDED

- Blunder now supports `Skill` (1-20), `UCI_LimitStrength`, and
  `UCI_Elo` (500-2500) for adjustable play strength.
- Coaching protocol commands (`coach eval`, `coach compare`) always
  run at full strength regardless of the Skill/Elo setting.

### Opening Book ✅ ADDED

- Blunder supports `BookFile` UCI option for Polyglot opening books.

## Feature Requests (still open)

### BLUNDER-004: Pawn structure false positives

- **Status**: Needs re-testing with current Blunder version.

### BLUNDER-005: Threat descriptions could be more specific

- **Observed**: Threats like "Bc4 can give check" don't specify the
  actual move (Bxf7+) or the real target (f7 pawn, not the king).
- **Suggestion**: Include the move in UCI notation and the actual
  target square/piece being threatened.

### BLUNDER-006: Expose tactical motif labels

- **Status**: Blunder now returns some tactics (discovered attacks
  observed in testing). Forks, pins, skewers may still be missing.
- **Suggestion**: Expand detection to cover common patterns from
  the search tree.

### BLUNDER-008: Threat map is too verbose

- **Status**: Chess-coach now filters client-side (only shows pieces
  under attack). Blunder could add a `threat_map_summary` field
  to reduce JSON size. Blunder has started returning a summary
  string which chess-coach displays as "Board tensions."

## Future Protocol Extensions

- **MultiPV top lines**: The most impactful missing feature. Needed
  for comparing candidate moves and "what was missed" coaching.
- **NNUE eval component exposure**: Accurate breakdown calibration.
- **"Why not" analysis**: Explain why the engine rejects a move.
- **Positional feature extraction**: Passed pawns, open files,
  outposts, weak squares.
- **Critical moment detection**: Flag volatile positions. Currently
  `critical_moment` is always `false`.


## Protocol Evolution: Structured Data over Descriptions

**Goal**: Blunder should return structured facts; chess-coach owns the
coaching voice and wording.

**Current state**: Blunder returns both raw data (scores, squares) AND
human-readable description strings (e.g. `"king uncastled, still has
castling rights, missing e-pawn shield"`). Chess-coach currently passes
these descriptions through to the coaching text.

**Problem**: Every wording change requires an engine rebuild. The
descriptions can't adapt to coaching level (beginner vs advanced),
language, or context (early opening vs middlegame).

**Proposed change**: Blunder returns structured flags and chess-coach
generates all user-facing text. Example for king safety:

```json
// Current (Blunder returns description)
"king_safety": {
  "white": {
    "score": -15,
    "description": "king uncastled, still has castling rights, missing e-pawn shield"
  }
}

// Proposed (Blunder returns structured flags)
"king_safety": {
  "white": {
    "score": -15,
    "castled": false,
    "castling_rights": true,
    "missing_shield_files": ["e"],
    "open_files_near_king": [],
    "pawn_storm": false,
    "description": "..."  // kept for backward compat, chess-coach ignores it
  }
}
```

Chess-coach then decides what to say based on context:
- Early opening + not castled → say nothing (normal)
- Move 10+ and not castled → "Consider castling soon"
- King exposed + open file → "Your king is vulnerable on the open e-file"

**Migration**: Keep `description` field for backward compatibility.
Add structured flags incrementally. Chess-coach starts ignoring
descriptions and generating its own text from flags.
