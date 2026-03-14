# Blunder Engine — Improvement Requests from Chess-Coach

Issues and feature requests observed while integrating Blunder with
chess-coach via the coaching protocol. Ordered roughly by impact.

## Bugs / Calibration Issues

### BLUNDER-001: Eval breakdown doesn't sum to overall eval

- **Observed**: Starting position after 1.e4 returns `eval_cp: -236` but
  the top line eval is `-10 cp`. The breakdown shows `mobility: -240`,
  `material: 0`, `king_safety: 15`, `pawn_structure: -24`.
- **Impact**: The LLM gets a misleading overall eval and describes a
  near-equal opening as "complex and unbalanced." The coaching text
  quality depends heavily on accurate eval data.
- **Expected**: Overall eval should be close to the top line eval, and
  the breakdown components should roughly sum to the overall eval.
- **Positions tested**: `rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1`

### BLUNDER-002: Mobility score seems miscalibrated

- **Observed**: Mobility component dominates the eval breakdown in
  opening positions where both sides have similar piece activity.
  Starting position after 1.e4: `mobility: -240 cp` (Black to move).
  Italian Game position: `mobility: 220 cp` (White to move).
- **Impact**: The LLM over-emphasizes mobility in its explanations
  because the number is disproportionately large compared to other
  components.
- **Expected**: In roughly equal positions, mobility should be a
  smaller component, not 5-10x larger than material/king safety.

### BLUNDER-003: Only 1 PV line returned despite multipv 3

- **Observed**: `coach eval fen <FEN> multipv 3` returns 3 entries in
  `top_lines`, but lines 2 and 3 have `depth: 0`, `moves: []`, and
  just copy the eval from line 1.
- **Impact**: The LLM can only explain one candidate move instead of
  comparing alternatives. MultiPV is key for "what was missed" coaching.
- **Expected**: All 3 lines should have actual PV moves and independent
  eval scores at the requested depth.

## Feature Requests

### BLUNDER-004: Pawn structure detection for e-file after 1.e4

- **Observed**: After 1.e4, Black's pawn structure reports `doubled: ["e"]`
  in the Italian Game position — but Black doesn't have doubled e-pawns
  (e5 and e7 are on different ranks, and e7 hasn't moved yet in some
  lines). This may be a false positive in the pawn structure analysis.
- **Impact**: LLM tells beginners about "doubled e-pawns" that don't exist.

### BLUNDER-005: Threat descriptions could be more specific

- **Observed**: Threats like `"Bc4 can give check"` are useful but don't
  specify the path (Bxf7+ is the actual threat, not just "check"). The
  `target_squares` field says `["e8"]` but the real target is f7.
- **Suggestion**: Include the move in UCI notation and the actual target
  square/piece being threatened, not just the king square.

### BLUNDER-006: Expose tactical motif labels

- **Observed**: `tactics: []` is always empty in positions where clear
  tactics exist (e.g., Italian Game has Bxf7+ sacrifice ideas, pins
  on the e-file after d3).
- **Impact**: The LLM has to guess at tactical themes from PV lines
  instead of getting labeled motifs from the engine.
- **Suggestion**: Detect common patterns from the search tree — forks,
  pins, skewers, discovered attacks, back-rank threats. Even basic
  detection (piece attacks two higher-value pieces = fork) would help.

### BLUNDER-007: King safety description is static

- **Observed**: White's king safety always says "king partially sheltered,
  missing e-pawn shield" after 1.e4, even in positions where White has
  castled. The description seems template-based rather than position-aware.
- **Suggestion**: Make descriptions reflect the actual position — castled
  vs uncastled, pawn storm proximity, open files near the king.

### BLUNDER-008: Threat map is too verbose for coaching

- **Observed**: The threat map returns data for every occupied square
  (32+ entries). Most entries show `net_attacked: false` and aren't
  interesting for coaching.
- **Suggestion**: Either (a) only return squares where `net_attacked`
  is true or where there's a meaningful attacker/defender imbalance,
  or (b) add a `summary` field that lists only the interesting squares.
  Chess-coach currently filters client-side but it inflates the JSON.

## Future Protocol Extensions

These are from IDEAS.md — things that would need Blunder changes:

- **NNUE eval component exposure**: Break down the NNUE eval into
  interpretable features (material, mobility, king safety, pawn
  structure) with accurate calibration.
- **"Why not" analysis**: Given a candidate move, explain why the engine
  rejects it (what refutation does it see?). Not standard UCI.
- **Positional feature extraction**: Passed pawns, open files, outposts,
  weak squares — the engine knows these but doesn't report them.
- **Critical moment detection**: Flag positions where the eval is
  volatile (large swings between candidate moves). Currently
  `critical_moment` is always `false`.
