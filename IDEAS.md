# Chess Coach — Ideas Bank

A living document for feature ideas, improvements, and research directions.

## Performance

- [ ] Lower default engine depth in play mode (depth 12 for casual play)
- [ ] Stream LLM responses via SSE so text appears incrementally
- [ ] Use a smaller/faster model for simple move feedback (1-3B params)
- [ ] Profile the full pipeline to identify actual bottlenecks
- [ ] Cache engine analysis for repeated positions
- [ ] Batch the two LLM calls (user feedback + engine explanation) into one
      prompt to halve the LLM round-trips per move
- [ ] Pre-analyze: while the user is reading coaching text, start analyzing
      likely next positions in the background

## Richer Engine Data for the LLM

- [ ] Feed top 3 lines to the LLM instead of just the best move (needs MultiPV / UCI)
- [ ] Include material balance in the analysis text
- [ ] Detect and report hanging pieces (pieces attacked but not defended)
- [ ] Detect immediate threats (checks, captures, forks, pins, skewers)
- [ ] Report pawn structure characteristics (isolated, doubled, passed pawns)
- [ ] Detect king safety issues (exposed king, missing castling rights)
- [ ] Compare user's move to top-N engine lines to explain *what was missed*
- [ ] NAG-style move annotations (!, !?, ?!, ?, ??, !!) computed from eval
      deltas — more granular than the current good/inaccuracy/blunder buckets.
      Could also be emitted by Blunder directly if it adds annotation support

## Engine Intelligence — Making Blunder the Expert

- [ ] UCI protocol support (Phase 10, enables MultiPV and richer info lines)
- [ ] Extract tactical motifs from engine lines (fork, pin, skewer, discovered attack)
- [ ] Use engine eval swings across moves to identify critical moments
- [ ] Even with NNUE eval, the PV lines themselves encode tactical/strategic ideas
      — the LLM can interpret *why* a sequence is good from the moves alone
- [ ] Research: can we probe NNUE intermediate features for positional concepts?
      (king safety score, piece mobility, pawn structure score, etc.)
- [ ] Research: Blunder-specific extensions — can Blunder expose eval breakdown
      by component (material, mobility, king safety, pawn structure)?

## Teaching Mode

- [ ] Teach common openings: detect the opening played, explain its ideas
- [ ] Opening book integration: name the opening being played ("Sicilian Defense,
      Najdorf Variation") and explain its typical plans for both sides
- [ ] Tactical puzzles: extract positions from games where a tactic exists,
      let the user try to find it, then explain
- [ ] Pattern recognition: "this is a pin", "this is a back-rank weakness"
      — detect patterns from engine lines + board state, label them
- [ ] Positional lessons: use engine eval to find positions where strategy
      matters more than tactics, explain the long-term plan
- [ ] Blunder review: after a game, highlight the 3 worst moves and teach
      what the user should look for in similar positions
- [ ] Endgame training: detect endgame type (K+P vs K, rook endgames, etc.)
      and provide specific endgame principles
- [ ] "What would you play?" mode: hide the engine's move, let the user guess,
      then reveal and compare — active learning beats passive reading
- [ ] Spaced repetition: track positions the user got wrong, resurface them
      later as puzzles until they stick

## Play Mode Improvements

- [ ] Ponder: let the engine think during the user's turn so it responds faster
      (engine predicts the user's likely move and pre-computes its reply)
- [ ] Engine difficulty levels (beginner/intermediate/advanced via depth limit)
- [ ] Add randomness to engine play at lower levels (pick from top-N moves)
- [ ] Let user choose time control or depth for the engine
- [ ] Show engine "thinking" — display candidate moves being considered
- [ ] Game clock / time controls for more realistic play

## UI / UX

- [ ] Board themes (wood, marble, tournament green)
- [ ] Piece set options (Merida, Alpha, Leipzig)
- [ ] Move animations and sound effects
- [ ] Responsive layout improvements for mobile/tablet
- [ ] Keyboard shortcuts (arrow keys for move navigation, etc.)
- [ ] Dark/light mode toggle
- [ ] Export game as PGN
- [ ] Import PGN / paste a game to review
- [ ] Eval graph: plot eval over the course of a game (like lichess)
- [ ] Highlight critical moments on the eval graph (blunders, turning points)
- [ ] Pre-move: let the user queue a move while the engine is thinking

## Future Features (from spec)

- [ ] PGN game review (User Story 9)
- [ ] Interactive follow-up questions about a position (User Story 10)
- [ ] Game navigation (forward/backward through loaded PGN)

## Research Questions

- How much chess knowledge can an LLM extract from just PV lines + eval scores?
- Can we fine-tune a small model specifically for chess coaching?
- What's the minimum engine data needed for the LLM to stop hallucinating?
- Can NNUE eval components be exposed without modifying the engine binary?
- Would a hybrid approach work: engine for tactics, LLM for strategy/explanation?
- Could we use Lichess/FICS game databases to build a training set of
  "position + good explanation" pairs for fine-tuning?
- What's the sweet spot for model size vs coaching quality vs response time?
- Can the LLM learn to calibrate its language to the user's actual skill level
  over multiple games (adaptive coaching)?

## Requires Blunder Engine Changes

Things that go beyond what UCI/Xboard protocols support — would need custom
commands or a custom protocol extension in Blunder itself.

- [ ] Expose NNUE eval breakdown by component (material, mobility, king safety,
      pawn structure) — UCI only gives a single cp score
- [ ] Tactical motif detection (fork, pin, skewer, discovered attack) — the
      engine sees these implicitly but doesn't label them
- [ ] Threat map: which squares/pieces are attacked, by what, and how many
      times — useful for the LLM to explain danger
- [ ] "Why not" analysis: given a candidate move, explain why the engine
      rejects it (what refutation does it see?) — not a standard UCI feature
- [ ] Positional feature extraction: passed pawns, open files, outposts,
      weak squares — engine knows these but doesn't report them
- [ ] Custom protocol extension or JSON-based API for richer coach ↔ engine
      communication beyond UCI's `info` lines
