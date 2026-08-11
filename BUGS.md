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
- **Status**: FIXED (prompt constraint) — added a strict grounding rule to
  `SYSTEM_PROMPT_V2` (shared by the position-coaching and move-eval rich
  prompts): *do not narrate "and then..." move sequences or follow-up
  variations unless those exact moves appear in the engine lines above;
  explain the plan/idea in words instead — a made-up line is the most
  misleading error you can make.* The "Stay grounded" bullet in all three
  move-eval instruction blocks (best/sound/inferior) now names "follow-up
  move sequences" explicitly. Regression test
  `tests/test_prompts.py::test_rich_prompts_forbid_invented_continuations`.
  Live look (qwen3:14b, guidance on, 6 move-feedback scenarios): none narrated
  an invented continuation; feedback stayed on the named move + one principle.
  **Deferred (deliberately): the deterministic checker extension.** Flagging a
  fabricated multi-move line at the fidelity checker's precision-first bar is
  hard: telling apart a *fabricated variation* ("exd4, then Ne3+, Nc3") from
  *legitimate prose mentioning two moves* ("exd4 was fine, and later O-O")
  needs understanding the checker doesn't encode. Playing the line forward
  false-positives on plans that skip the opponent's replies; requiring a match
  to an engine PV false-positives on ordinary two-move mentions. Either erodes
  trust, which this checker refuses to do, so the frontier judge (which already
  catches the "legal-but-unsupported" case) stays the backstop for it.

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
- **Status**: FIXED (checker extension) — `verify.py` gained three
  precision-first checks, each anchored to an explicit square or a legal
  capture move so it never guesses which piece/square a loose phrase means:
  - `piece_type`: a capture described as taking the wrong piece (e.g. "capture
    the pawn with dxe3" when dxe3 takes a knight). Fires only when the legal
    captures named in the text agree on a single victim type; the "win(s)"
    verb is excluded so the "wins a pawn" material idiom is not misread.
  - `pawn_structure`: "isolated pawn on <sq>" when a friendly pawn stands on
    an adjacent file (isolation computed from the board).
  - `geometry`: a piece "on <sq> ... central" (or "central … <piece> on
    <sq>") when <sq> is outside the central region (files c–f, ranks 3–6) —
    catches the `Kc1` "central" case. Plan-talk ("central control", "fight for
    the center") is not flagged because it lacks the piece+square anchor.
  The "supporting the knight on b1 (no knight there)" case was already caught
  by the existing `placement` check. All three are **diagnostic-only** (they
  populate `ObjectiveResult.fidelity_counts` and flow through the game-coaching
  eval's per-turn counts automatically, but do NOT feed `factual_score`, which
  stays comparable across runs) — the same treatment as `off_menu`/
  `unsound_move`. Tests: `tests/test_fidelity.py` (positive + false-positive
  guards for each). Bounded recall by design (only explicit, anchored claims);
  the frontier judge `grounded` criterion remains the backstop.


## Coaching-Quality Issues (found via the game-coaching test RE-RUN, 2026-08-05)

*After fixing BUG-013/14/15 we re-ran the end-to-end game-coaching pairwise
(qwen3:14b, sonnet judge via kiro-cli) on a fresh seed (2 games, 60 coaching
scenarios). Both arms now carry the BUG-013/14 prompt fixes, so any recurrence
or new defect shows up in the per-move critiques. Mining the 60 rationales
surfaced one clear regression (BUG-016) and two issues worth tracking.*

### BUG-016: Sound-move affirmation suppressed a genuinely better move (regression from BUG-014)
- **Observed**: On `Qd4` (`d1d4`), an engine **inaccuracy** (37cp drop) where
  the clearly better idea was `Kf1` (king safety), the coach affirmed the move
  and **omitted the better move** — flagged by the judge in BOTH games
  (g1p16, g2p16, both ties: "both responses incorrectly praise an inaccuracy
  as solid/safe without mentioning the missed king safety move (Kf1)").
- **Impact**: The student is told a borderline inaccuracy is fine and never
  learns the stronger idea — the opposite failure of BUG-014 (there, the coach
  invented a correction; here, it withholds a real one).
- **Root cause**: BUG-014's `_MOVE_EVAL_INSTRUCTIONS_SOUND` told the coach to
  "do NOT suggest a different or better move" for any move within the sound
  eval-drop band. But a *sound-but-not-best* move (by definition not the top
  move) has a genuinely better move available — the engine best, already shown
  in the prompt — and the instruction wrongly suppressed it. (The exact-best
  BEST branch is correct: there, no better move exists.)
- **Not the cause / explicitly avoided**: coupling the branch to the engine's
  `classification` label. Blunder's inaccuracy/mistake thresholds are the
  engine's to change, so the coach's logic must not depend on them. The branch
  stays keyed on our own client constant `SOUND_MAX_DROP_CP` applied to the raw
  `eval_drop_cp` measurement.
- **Status**: FIXED — rewrote `_MOVE_EVAL_INSTRUCTIONS_SOUND`: affirm the sound
  move and teach its idea, and *if the engine's top move differs, briefly point
  it out and its idea as a refinement — affirm first, never imply the move was
  bad*. Keeps BUG-014's intent (no fabricated corrections; the exact-best case
  still forbids inventing a better move) while restoring grounded better-move
  teaching for sound-but-not-best moves. Regression test
  `tests/test_prompts.py::TestPlayedBestMove::test_sound_move_affirms_but_may_note_stronger_move`
  and the branch-aware property test updated. All logic remains client-side
  (no dependency on the engine's classification label).

### BUG-017: Ungrounded positional justifications persist (broader than BUG-013)
- **Observed**: The losing arm still invented ungrounded *positional* claims on
  eval-drop-0 moves — "opening lines for the bishop", "far superior to
  alternatives" (g1p12, g2p12) — distinct from the invented *move
  continuations* BUG-013 constrained.
- **Impact**: Confident positional assertions the engine data does not support.
- **Why open**: BUG-013's rule targets "and then…" move sequences; free-form
  positional justification is harder to constrain in the prompt without
  over-suppressing legitimate explanation, and the deterministic checker can't
  judge positional claims. The frontier judge catches it; a prompt tightening
  needs care not to make coaching vaguer.
- **Status**: ACTIVE (un-parked 2026-08-05 — revisit trigger met). The coach
  report card (single-mode holistic review) flagged fabricated/ungrounded causal
  analysis as **the single most damaging problem**, with ~5 cited instances
  (e.g. "Bc4 allows Black to capture on d4" — invented; "a3 supports d4" — wrong
  square; "a2 is isolated" offered as a3's reason — guessed) corroborated by 13
  deterministic off_menu/unsound violations in the transcript. That is the
  "flagged often" bar we set, so this is now a real blocker and the next
  coaching lever: constrain the coach strictly to engine-stated facts (eval
  drop, specific squares, concrete move consequences) and forbid inventing
  causal chains it cannot verify. Measured before/after with the report card
  (same seed), one lever at a time. (Was PARKED 2026-08-05 as low-frequency; the
  report card promoted it.)

### BUG-018: Isolated-pawn misidentification still generated (detection ≠ prevention)
- **Observed**: The coach wrote "isolated pawn on c4" where it was factually
  questionable (g1p42), even though BUG-015 added a `pawn_structure` check for
  exactly this.
- **Impact**: A wrong structural label in otherwise fluent prose.
- **Why it happened**: the move-feedback prompt fed the board *placement*
  (piece locations) but no pawn-structure facts — the `ComparisonReport` carries
  none — so the coach guessed isolation. (The position-coaching prompt already
  had an engine-based `--- Pawn Structure ---` section; the move-eval prompt did
  not.)
- **Status**: FIXED (prevention) — added a board-derived pawn-structure
  grounding block to `build_rich_move_evaluation_prompt`:
  `coaching_phrases.describe_pawn_structure_from_board(board)` lists each side's
  isolated and doubled pawns computed directly from `python-chess` (a pawn is
  isolated when no friendly pawn is on either adjacent file; a file is doubled
  with ≥2 friendly pawns). Deliberately board-derived, **not** from the engine's
  `PawnFeatures` or any engine-tunable label — same grounding idea as the
  placement block that stopped piece-location hallucinations. The block always
  lists both sides (including an explicit "none") so the model is told what is
  NOT weak, too, and won't invent an isolated pawn. The BUG-015 `pawn_structure`
  checker remains the deterministic backstop. Tests:
  `tests/test_coaching_phrases.py` (isolated+doubled, the not-isolated-with-
  neighbor case, empty/pawnless) and
  `tests/test_prompts.py::test_move_eval_prompt_grounds_pawn_structure`.
  Note: passed pawns were left out for now (isolated + doubled cover the
  observed error; passed-pawn detection is more involved).


## Engine Issues (found via the coach report card, 2026-08-10)

### BUG-019: Comparison `top_lines` came from the wrong search (FIXED 2026-08-11)

**The original diagnosis below was WRONG and is kept for the lesson.** There was
no missing ply and no PV corruption. The real cause was a single stale reference
in the engine, and the "two Black moves in a row" was one mis-sided castle.

**Root cause** (`blunder/source/MoveComparator.cpp:102`): `compare()` bound a
`const auto&` to `search.get_multipv_results()`, which returns a reference to
`Search::multipv_results_`. The post-user-move search further down calls
`search.search()` again, and every search clears and reassigns that vector
(`Search.cpp`: `clear()`/`resize()`, then `multipv_results_ = depth_results`).
So partway through `compare()` the reference silently began pointing at the
*second* search's single-PV result. For every move that was not the engine's
best — 30 of 44 turns in a real game — this corrupted four fields at once:

- `top_lines` held the post-move line instead of the pre-move MultiPV lines,
  while `CoachJson::serialize_top_lines` (correctly) assumed they were relative
  to `report.fen` and so attributed every move to the wrong side. For castling,
  `move_to_uci` picks hardcoded coordinates by side, so a **White** castle was
  emitted as `e8g8` — a well-formed move for the wrong colour. That is the
  entire "missing White ply": patch index 7 of the reported line back to `e1g1`
  and all 10 moves replay.
- `pv.theme` was computed by replaying a post-move line on the pre-move board.
- `critical_moment` was **always false** (it needs >= 2 lines; the second search
  runs with multipv 1).
- `missed_tactics` was **always empty** (both sides of the diff became the same
  vector).

`best_move_idea` was NOT affected — `describe_best_move` ignores its `pv_moves`
parameter, and its other inputs were still correct.

**Second, independent bug in the same function**: the best line's tactics were
detected *after* `board.do_move(user_move)`, and `detect_tactics` reads
side-to-move and the piece bitboards from the board it is handed — so even with
the reference fixed, `missed_tactics` would still have been wrong.

**Engine fix**: take a copy instead of a reference, and compute the best line's
tactics before the user's move is applied. Verified before/after on the same
probe: non-best moves went from 1 line (post-move base, identical to
`refutation_line`, `critical_moment` always false, `missed_tactics` always
empty) to 3 lines from the pre-move base, with real eval spreads and a correctly
identified missed fork `('fork', ['c7','a8','e8'])`. Blunder's own suite: 2414
assertions pass.

**Client impact this had been hiding**: our renderer assumed the post-move base
always, so on the 14 turns of a 44-turn game where the student *did* play the
best move, every line failed to replay and was dropped — the coach received a
`--- Top Engine Lines ---` header with nothing under it on 19 of 44 turns, while
the grounding instructions told it to use only facts from that section. After the
fix all 19 carry lines. The renderer now picks each line's base by trying the
pre-move position first (so an older engine binary still works), only emits the
header when a line actually renders, and states which position each line starts
from. Guard added: a test asserting the section is omitted rather than left empty.

**Also fixed alongside**: `PVLine` had no depth field, so
`serialize_top_lines` reported each line's `depth` as `pv.moves.size()` — the
move count. `PVLine` now carries the iterative-deepening depth it came from,
verified to track the requested depth independently of line length.

**Lesson**: the original entry proposed fixing PV extraction, which was not
broken. The symptom (an unreplayable move) was two steps removed from the cause
(a stale reference), and the intermediate step (side attribution) turned a
correct move into a plausible-looking wrong one. Reading `serialize_top_lines`
was what settled it: the serializer's assumptions document the intended contract.

---

**Original (incorrect) diagnosis, for the record:**
- **Observed**: `get_comparison_report` on the starting position with the
  student move `g1f3` returns a top line whose moves cannot all be replayed:
  `['b8c6', 'b1c3', 'g8f6', 'e2e3', 'e7e6', 'f1d3', 'c6b4', 'e8g8', 'b4d3',
  'c2d3']`. Walking it from the position after `g1f3` (Black to move) gives
  `c6b4` (Black) immediately followed by `e8g8` (Black castling) — **two Black
  moves in a row**, i.e. a missing White ply. Replay: 7 of 10 moves legal from
  the correct base position, 0 of 10 from the pre-move position.
- **Impact**: the client cannot render the tail of the line. Before it was
  fixed, our SAN converter degraded to raw UCI for the remainder, so
  coordinates like `e8g8 b4d3 c2d3` reached the coach, which then parroted a
  coordinate and invented what the move did (this is how the ply-8 "the
  opponent plays f6g4, gaining a strong central pawn" error arose — the correct
  SAN is `Nfg4`, a knight move).
- **Likely cause**: PV extraction from the transposition table without
  verifying move legality along the reconstructed line — a classic source of
  PV corruption (a TT hit splices in a move from a different position/parity).
- **Client-side mitigation (done)**: `prompts._uci_line_to_san` now TRUNCATES a
  line at the first unreplayable move (appending `...`) and never emits raw
  coordinates; a line whose first move does not replay is omitted entirely.
  A `prompt_uci_leaks` metric in the report card and a sentinel test guard
  against regressions. So the coach no longer sees the corrupt tail — but the
  engine is still sending it.
- **Proposed engine fix**: validate each PV move against the running position
  while extracting the PV and stop at the first illegal move, so the engine
  emits a short valid line instead of a long corrupt one.
- **Status**: superseded — see the corrected analysis above. PV extraction was
  never at fault; the "likely cause" (transposition-table splicing) was a guess
  and it was wrong.

### BUG-021: `eval_drop_cp` reports mate scores as centipawns (OPEN, low priority)
- **Observed**: a move that allows mate yields `eval_drop_cp` of ~100046, since
  `eval_drop_cp = best_eval - (-mate_score)` and the mate score is ~99999.
- **Impact**: cosmetic for now. The classification (`blunder`) is correct, our
  own severity bands treat it as the largest drop, and the coach is forbidden
  from mentioning centipawn numbers, so no student sees it. It would matter if
  anything ever averaged or plotted eval drops.
- **Not fixed**: changing the representation would alter classification inputs;
  it needs a deliberate decision on how to express mate distance separately.

### BUG-022: `critical_moment` cannot see catastrophic alternatives (OPEN, by design?)
- **Observed**: in a position where the student's move loses to mate but the
  engine's top three moves are all roughly equal (evals 47 / 26 / -29),
  `critical_moment` is false, because it measures only the spread between the
  best and third-best line.
- **Assessment**: arguably correct — the flag asks "does it matter which good
  move I find here?", and the answer is no. But the name suggests something
  broader, and the metric cannot distinguish "many moves are fine" from "many
  moves are fine and one is fatal".
- **Not fixed**: this is a definition question, not a defect. Left for a
  deliberate decision rather than changed unilaterally.