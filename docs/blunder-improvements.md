# Blunder Engine — Improvement Requests from Chess-Coach

Issues and feature requests observed while integrating Blunder with
chess-coach via the coaching protocol. Ordered roughly by impact.

## Bugs / Calibration Issues

### BLUNDER-001: Eval breakdown doesn't sum to overall eval ⚠️ OPEN

- **Observed (2026-03-16)**: After 1.e4, `eval_cp=0` but breakdown
  sums to `-28` (mat=-24, mob=-24, ks=15, ps=5). Previously the
  numbers were even more off (eval=-236, mob=-240).
- **Improved**: The magnitude is much smaller now (off by 28cp vs 226cp
  before), but the sign is still wrong (breakdown says -28, eval says 0).
- **Impact**: Template coaching shows "roughly equal" (correct from
  eval_cp) but the breakdown components tell a different story.
- **Expected**: Breakdown components should sum to (or be close to)
  the overall eval_cp.

### BLUNDER-002: Mobility score seems miscalibrated ✅ IMPROVED

- **Previously**: Mobility was -240cp after 1.e4 — wildly dominant.
- **Now (2026-03-16)**: Mobility is -24cp after 1.e4 — much more
  reasonable and proportional to other components.
- **Status**: Mostly fixed. No longer dominates the eval breakdown.

### BLUNDER-003: Only 1 PV line returned despite multipv 3 ⚠️ OPEN

- **Observed (2026-03-16)**: `coach eval fen <FEN> multipv 3` returns
  only 1 line (with actual moves and depth 15). Previously returned
  3 entries but lines 2-3 were empty stubs.
- **Improved**: The single line now has real data (depth, moves, eval).
- **Still needed**: Multiple distinct PV lines for comparing candidate
  moves. This is key for "what was missed" coaching.

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
