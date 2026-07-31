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
- **Root cause**: The move `d8a5` (Qa5) is actually illegal in this
  position — the d7 pawn blocks the queen's path. The engine correctly
  returns an error response (`"type": "error"`, `"code": "invalid_move"`),
  but `parse_coaching_response` didn't check the `type` field and passed
  the error data to `validate_comparison_report`, which failed with a
  confusing "missing required field: fen" message.
- **Status**: FIXED — `parse_coaching_response` now checks for
  `"type": "error"` and raises `CoachingProtocolError` with the engine's
  error code and message. The original test case was invalid (illegal move).

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
  **Update (2026-07-02, client-side-coaching-text):** the piece-count
  guard is now the shared `coaching_phrases.king_safety_relevant()`, so
  BOTH the template and the LLM-prompt king-safety sections suppress
  endgame king-safety noise consistently. King-safety commentary is also
  now composed from the engine's structured fields (`king_square`,
  `castling_status`, `missing_shield_files`, `open_file_near_king`,
  `pawn_storm`) rather than the prose `description`.


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

### BUG-011: Coach attributes the opponent's pieces to the student (perspective confusion)
- **Observed**: `chess-coach explain` on a Black-to-move position after
  1.e4 e5 2.Qh5 (FEN
  `rnbqkbnr/pppp1ppp/8/4p2Q/4P3/8/PPPP1PPP/RNB1KBNR b KQkq - 1 2`,
  `--level beginner`). The coaching text told the student "your queen is
  on h5" and that it "pins your opponent's king to their own rook on h8".
  Qh5 is **White's** queen; the side to move (the student) is Black, and
  h8 is Black's own rook. The coach narrated White's pieces and threats
  as if they belonged to the student.
- **Impact**: Actively misleading coaching. The student is told their
  opponent's attacking piece is their own and that they are threatening
  their own king/rook. Undermines trust and teaches the wrong mental
  model of whose turn/threats are whose. Likely affects any position
  where the side to move is the one under threat.
- **Root cause**: CONFIRMED (diagnosed by code inspection of
  `build_rich_coaching_prompt` and `RICH_COACHING_PROMPT_V2` in
  `prompts.py`). The prompt never states, in natural language, whose turn
  it is or which color the student is playing. Side-to-move is present
  ONLY as the active-color field inside the FEN string
  (`Position (FEN): ...`). Meanwhile every other signal points at White:
  the engine data sections are rendered in absolute color terms
  ("White: Qh5 can give check ..."), and `Overall evaluation: {eval_cp}`
  is White-relative by engine convention (+0.17 favors White) without
  saying so. With no explicit perspective anchor, the LLM (especially a
  small model like qwen3:8b) latches onto the salient White-labeled
  threats and positive eval and narrates from White's side, attributing
  White's pieces to the student. The same gap exists in
  `RICH_MOVE_EVALUATION_PROMPT_V2`.
- **Proposed fix**: Derive side-to-move from the FEN and state it
  explicitly in the prompt, e.g. "It is Black to move. You are coaching
  the player with the Black pieces. The evaluation is from White's
  perspective (positive favors White)." Consider presenting threats and
  eval from the student's perspective as well. Add a unit test asserting
  the built prompt names the side to move; validate live that the
  perspective confusion is gone.
- **Repro**: `chess-coach explain
  "rnbqkbnr/pppp1ppp/8/4p2Q/4P3/8/PPPP1PPP/RNB1KBNR b KQkq - 1 2"
  --level beginner` with qwen3:8b.
- **Status**: FIXED — found during Phase 9 manual verification.
  `_format_perspective(fen)` in `prompts.py` now injects an explicit
  "Side to move: <color>. You are coaching the player with the <color>
  pieces ... translate engine White/Black labels to the student's
  perspective" line into both rich prompts, and the eval line states it is
  White-relative. Regression tests added in `tests/test_prompts.py`.
  Live re-verification on the repro position (qwen3:8b) confirms the
  inversion is gone: the coach correctly treats the student as Black and
  White as the opponent ("your pawn on e5 is hanging", "your opponent's
  queen is aiming to take it"). Any remaining inaccuracies in the model's
  wording are LLM-output quality (measured by the eval harness), not code
  defects, and are out of scope for this tracker.

### BUG-012: CLI crashes with UnicodeEncodeError when stdout is not UTF-8
- **Observed**: `chess-coach check` (and other commands that print ✓ / box
  drawing) aborted with
  `UnicodeEncodeError: 'charmap' codec can't encode character '\u2713'`
  on Windows whenever stdout was not an interactive UTF-8 console — e.g.
  output piped/redirected, or running in CI logs (which default to
  cp1252 on Windows runners).
- **Impact**: Any redirected/captured run of the CLI on Windows crashed
  before doing useful work; would have broken CI and the kiro-monitor
  output capture.
- **Root cause**: The CLI emits Unicode (check marks, box-drawing, emoji)
  via `click.echo` / rich, but the standard streams inherit the OS code
  page (cp1252 on Windows) when not attached to a UTF-8 console.
- **Status**: FIXED — `main()` in `cli.py` now reconfigures
  `sys.stdout`/`sys.stderr` to `encoding="utf-8", errors="replace"` at
  startup, so Unicode output works regardless of the console code page.

## Coaching-Quality Issues (found via the end-to-end game-coaching test)

*All three below were surfaced by the new end-to-end game-coaching eval
(`scripts/eval_game_coaching_pairwise.py`, spec
`.kiro/specs/game-coaching-eval/`) on its first live run (2026-07-30):
Blunder played two full games at ~1350/1500 Elo, the coach (qwen3:14b)
gave move-feedback on all 40 student moves, and a frontier judge
(claude-sonnet-4.6 via kiro-cli) critiqued each. Reading the 40 judge
rationales — not the win/loss tally — is what exposed these. This is
exactly the "surface bugs the curated position benchmarks miss" value the
game test was built for. These are LLM-output quality issues (the eval
harness measures their rate); the value is the pattern, not single
anecdotes.*

### BUG-013: Coach invents ungrounded follow-up lines
- **Observed**: On several *correct* moves the coach grounded the named
  move fine, then padded with **fabricated continuations not in the
  engine data**. Judge examples: on `exd4` it invented "Ne3+ / Nc3 king
  attacks not supported by the position"; on `Qxf6` it invented a "warning
  about gxf6 counterplay" and "Ne4 plans" with no basis.
- **Impact**: Teaches wrong concrete lines — the worst kind of coaching
  error (a confident, specific falsehood). Toward the north star, the
  "concrete sound action" half of the bridge must be engine-grounded.
- **Why the fidelity checker misses it**: `check_coaching_fidelity`
  validates the *named move* against the board/menu, but a fabricated
  *multi-move continuation* ("...then Ne3+ and Nc3") isn't a single named
  move it evaluates.
- **Proposed fix**: constrain the prompt to not narrate continuations
  beyond what the engine top-line provides, and/or extend the checker to
  flag multi-move sequences whose later plies are illegal/unsupported.
- **Status**: OPEN.

### BUG-014: Coach second-guesses a move that was already the engine's best
- **Observed**: When the student played the **engine's top move** (e.g.
  `Bc4`), the coach still "implies the move is merely solid and hints at a
  better alternative" and "invents a distinction between the student's
  move and the 'best move'" — when they are the same move.
- **Impact**: Undermines trust and teaches a false "you could have done
  better" on a best move. Directly contradicts the engine ground truth.
- **Likely cause**: the move-feedback prompt / `evaluate_move` path does
  not tell the model when the student's move *is* the best move, so it
  manufactures a correction anyway.
- **Proposed fix**: when `classification == good` and the student's move
  equals the engine best (eval drop ~0), instruct the coach to affirm and
  teach the idea behind it — never to invent a superior alternative.
- **Status**: FIXED — `build_rich_move_evaluation_prompt` now branches on how
  the played move scores in the engine's multi-line PV, in three cases:
  - **exact top move** (`user_move == best_move`) →
    `_MOVE_EVAL_INSTRUCTIONS_BEST`: affirm, "there is no better move here — do
    NOT suggest a different/better move".
  - **sound move** (eval drop from best within `SOUND_MAX_DROP_CP`, i.e. it
    scores well in the PV but is not the single top move) →
    `_MOVE_EVAL_INSTRUCTIONS_SOUND`: affirm it as a strong choice and teach the
    idea; do NOT nitpick or push the engine's marginally-preferred line (it
    does not claim "no better move exists", since the top line is slightly
    higher).
  - **otherwise** (dubious/blunder) → the existing "what was missed / why best
    is stronger" gap framing.
  This broadens the original exact-best fix so the coach does not second-guess
  ANY move that scores well in the multi-line PV, not just the single best.
  Regression tests in `tests/test_prompts.py::TestPlayedBestMove` (best, sound,
  inferior) and the branch-aware property test
  `test_move_prompt_contains_instructions_and_data`.

### BUG-015: Piece-type / square misidentification in coaching prose
- **Observed** (reconfirms the BACKLOG "relational falsehoods" gap, with
  fresh live instances): captured **knight described as a pawn** (`dxe3`);
  `Kc1` called "central" (it is queenside); a `c4` pawn called "isolated"
  when it is not; "supporting the knight on b1" when no knight is there.
- **Impact**: Wrong board facts in otherwise fluent coaching.
- **Why partly uncaught**: the objective checker now catches "piece on
  square" placement and developed/undeveloped claims, but not piece-type
  labels on captures, adjacency/geometry claims ("central"), or pawn
  structure adjectives.
- **Proposed fix**: extend the objective fidelity checks to piece-type on
  captures and a few geometry/pawn-structure adjectives; keep the judge
  `grounded` criterion as the backstop.
- **Status**: OPEN.
