# Chess Coach — Known Issues

Tracked issues discovered during development and testing.

## Engine Issues

### BUG-001: Engine only reaches depth 9 despite requesting depth 18
- **Observed**: Analysis of starting position with `depth=18` returns
  `depth=9` after ~90s, then times out.
- **Impact**: Shallow analysis produces weak evaluations. Engine thinks
  `e3` is best in the starting position (should be `e4` or `d4`).
- **Root cause**: Xboard `analyze` command didn't reliably reach target
  depth. The UCI protocol uses `go depth N` which properly requests the
  full depth.
- **Debug data**: `"lines": [{"depth": 9, "score_cp": 96, "pv": ["e3", ...]}]`
- **Status**: FIXED — resolved by UCI protocol migration (Phase 10).
  `UciEngine.analyze()` sends `go depth {depth}` and parses standard
  UCI `info` lines reliably.

### BUG-002: Engine analysis returns empty lines for some positions
- **Observed**: `analyze_position` for
  `rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq - 0 1`
  returns `"lines": []` after 90s.
- **Impact**: LLM gets an empty "Engine analysis:" section and
  hallucinates. Coaching text is fabricated with no grounding.
- **Root cause**: Xboard thinking line parser was failing silently.
  UCI `info` lines use a standard format that parses reliably.
- **Status**: FIXED — resolved by UCI protocol migration (Phase 10).
  `UciEngine._parse_info_line()` handles standard UCI output.

### BUG-003: Engine plays Na6 (b8a6) — a terrible move
- **Observed**: `engine.play()` returns `b8a6` (Na6) as Black's
  response to 1.d4 and 1.e4. Na6 is a rim knight move that violates
  basic opening principles.
- **Impact**: Games against the engine are not realistic or useful
  for coaching.
- **Root cause**: Xboard `sd` + `go` commands weren't working
  correctly. UCI `go depth N` + `bestmove` parsing is reliable.
- **Status**: FIXED — resolved by UCI protocol migration (Phase 10).
  `UciEngine.play()` uses proper `go depth` and reads `bestmove`.

### BUG-004: eval_after always returns 0cp
- **Observed**: After any user move, `raw_eval_after_cp` is 0,
  making every opening move look like a 96cp inaccuracy.
- **Impact**: Move classification is broken. `d4` and `e4` are
  classified as "inaccuracy" when they're among the best moves.
- **Root cause**: Downstream of BUG-002 — Xboard post-move analysis
  returned no lines, so `score_cp` defaulted to 0. With UCI returning
  proper analysis lines, eval_after is now correct. The eval negation
  (`eval_after = -raw_eval_after`) is also properly implemented.
- **Status**: FIXED — resolved by UCI protocol migration (Phase 10).

## LLM Issues

### BUG-005: LLM hallucinates when engine data is missing
- **Observed**: When engine analysis is empty, the LLM fabricates
  analysis. Examples:
  - Claims Na6 "attacks the pawn on e4" (it doesn't)
  - Says Na6 is on a "central square" (a6 is the rim)
  - Describes "pawns on d4 and d5" in the starting position
- **Impact**: Coaching text is misleading and teaches wrong concepts.
- **Root cause**: The prompt doesn't instruct the LLM to refuse when
  data is missing. The LLM fills gaps with plausible-sounding but
  incorrect chess analysis.
- **Fix**: Add guardrails to the prompt: "If engine analysis is empty
  or incomplete, say so. Do not invent analysis."
- **Status**: FIXED — guardrails added to SYSTEM_PROMPT in prompts.py

## Performance Issues

### BUG-006: Play mode takes 6-8 minutes per move
- **Observed**: Full pipeline per move:
  - `evaluate_move`: ~290s (2 engine analyses + 1 LLM call)
  - `engine.play`: ~1s
  - `explain_engine_move`: ~100s (1 engine analysis + 1 LLM call)
  - `final_analysis`: ~90s (1 engine analysis)
  - Total: ~480s (8 minutes)
- **Impact**: Unusable for interactive play.
- **Breakdown**: 4 engine analyses × ~90s + 2 LLM calls × ~15-100s
- **Potential fixes**:
  - Lower depth for play mode (depth 12 or less)
  - Reuse the pre-move analysis from `evaluate_move` in
    `explain_engine_move` (currently re-analyzes the same position)
  - Skip `final_analysis` (redundant — we already have eval)
  - Batch the two LLM calls into one prompt
- **Status**: PARTIALLY FIXED —
  1. Eliminated 2 redundant engine analyses per move (reuse eval_after
     analysis in explain_engine_move, skip final_analysis). Pipeline
     now does 2 engine analyses + 1 engine play + 2 LLM calls instead
     of 4 analyses + 1 play + 2 LLM calls.
  2. LLM streaming added (commit 8823d00) — text appears incrementally
     so perceived wait time is lower even if total time is similar.
  3. UCI engine is faster than Xboard for the same depth.
  Remaining opportunities: lower play-mode depth, batch LLM calls,
  background pre-analysis while user reads coaching text.

## Coaching Quality Issues

*Found during coaching eval run (2025-03-24, scripts/eval_coaching_quick.py)*

### BUG-007: Comparison report fails for some moves (missing `fen` field)
- **Observed**: `engine.get_comparison_report()` for `Qa5` from the
  starting position raises `CoachingValidationError: missing required
  field: fen`. The engine returns a comparison report without the `fen`
  key.
- **Repro**: FEN `rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1`,
  move `d8a5`.
- **Impact**: Play mode crashes when the user plays certain moves.
  The web UI would show an error instead of coaching feedback.
- **Root cause**: Likely an edge case in Blunder's `coach compare`
  command — possibly triggered by unusual queen moves from the back rank.
  Needs investigation in the engine protocol layer.
- **Status**: OPEN

### BUG-008: Mainline opening moves classified as inaccuracies/mistakes
- **Observed**: At depth 8, the engine penalizes well-known opening moves:
  - 1...e5 → inaccuracy (44cp drop vs Nf6)
  - 1...d5 → mistake (114cp drop vs Nf6) — Scandinavian Defense
  - 1.d4 → inaccuracy (40cp drop vs e4)
  All three are among the most popular moves in chess history.
- **Impact**: Misleading coaching — tells students that perfectly good
  opening moves are mistakes. Undermines trust in the coach. This is
  the single biggest quality issue, responsible for 3 of 3 failing
  move tests in the eval suite (overall score drops from ~90% to 76%).
- **Root cause**: Two factors:
  1. Depth 8 is too shallow for reliable opening eval — engine
     preferences are volatile and don't match master-level play.
  2. The 50cp "skip LLM" threshold is too tight for opening moves
     where eval differences between top moves are noise.
- **Potential fixes**:
  - Widen the skip threshold for early moves (first 5-6 moves) to
    ~80-100cp, since opening eval at low depth is unreliable.
  - Use the opening book to whitelist known good moves — if a move
    leads to a recognized opening position, don't call it an inaccuracy.
- **Status**: FIXED — opening leniency: in the first 6 moves, only
  flag moves with eval drop >150cp. Implemented via
  `effective_move_classification()` in `coaching_templates.py`, used
  by both the template path and `Coach.evaluate_move()`.
  Trade-off: genuinely bad opening moves like 1...f6 (121cp) also
  get a pass in the first few moves. This is acceptable — the position
  coaching will teach through analysis rather than move criticism.

### BUG-009: Castling warning in K+R vs K endgame
- **Observed**: In a K+R vs K position (FEN `8/8/8/4k3/8/8/8/4K2R w - - 0 1`),
  the coach says "White's king can no longer castle — keep it protected."
- **Impact**: Nonsensical advice. There are no pieces to threaten the
  king in a K+R vs K endgame. Confusing for students.
- **Root cause**: The `_king_safety_text` template fires based on
  castling rights being absent, without checking whether the position
  is an endgame where castling is irrelevant.
- **Fix**: Add a piece-count guard — suppress castling warnings when
  total material is below an endgame threshold (e.g., ≤1 major piece
  per side, or ≤10 total pieces on the board).
- **Status**: FIXED — suppress king safety warnings when ≤6 pieces
  remain on the board. Added piece-count guard at the top of
  `_king_safety_text()` in `coaching_templates.py`.


### BUG-010: Eval summary reports contradictory factor
- **Observed**: "White has a clear advantage (+1.68 pawns). The main
  factor is king safety (Black is better)." — contradictory.
- **Impact**: Confusing coaching. Says White is ahead but the "main
  factor" favours Black.
- **Root cause**: `_eval_summary` picked the factor with the largest
  absolute value without checking whether it aligned with the overall
  eval direction.
- **Status**: FIXED — when the dominant factor contradicts the eval,
  find the factor that does explain the advantage and present both:
  "White's piece activity outweighs Black's king safety edge."
