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

## Hybrid Coaching: Template Engine + LLM Voice

The LLM audit (scripts/eval_models.py) showed that small models (1.7b-4b)
hallucinate chess facts — wrong piece locations, nonsensical eval
interpretations, invented tactics. Larger models (8b) are more accurate
but too slow for interactive play (~34s per response on CPU).

The insight: the LLM is bad at deterministic facts but good at tone and
narrative. Split the work:

### Layer 1: Template Engine (Python, instant, always accurate)
Generate factual coaching text directly from the structured engine data.
No LLM needed. Covers:
- Opening identification ("This is the Italian Game, C50")
- Eval summary ("White is slightly better, +0.43 pawns")
- Hanging pieces ("Your e4 pawn is undefended — Nf6 can take it")
- Threats ("White's bishop on c4 targets f7")
- Best move explanation ("Nc3 develops a piece and protects e4")
- Move classification ("Your move was good / an inaccuracy / a blunder")
- Pawn structure notes ("Black has doubled e-pawns")
- King safety warnings ("Castle soon — your king is exposed")

This layer is deterministic, zero-latency, and never hallucinates.

### Layer 2: LLM Voice (optional, adds personality)
Take the template output and rephrase it in a coaching tone adapted to
the student's level. The LLM prompt becomes:
"Rephrase this chess coaching text for a beginner: [template output]"

This is a much easier task — even a 1.7b model can rephrase text without
inventing chess facts. The prompt is shorter, so it's faster too.

### Benefits
- No-LLM fallback: if Ollama isn't running, users still get accurate
  coaching from templates alone. Just less conversational.
- Faster: template output is instant. LLM rephrasing is faster than
  full generation because the prompt is shorter and the task is simpler.
- More accurate: facts come from code, not the model's imagination.
- Testable: template output can be unit-tested against expected strings.
- Gradual migration: start with templates for the most common patterns,
  fall back to full LLM generation for edge cases.

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

- [ ] Board arrows on coaching hover: when the user hovers over a coaching
      line like "White's bishop on c4 can give check on f7", draw a c4→f7
      arrow on the board. The structured coaching data already has source
      and target squares from threats/tactics. Needs SVG overlay inside the
      board container (not document body — that causes scroll bugs).
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

## Innovative / Differentiators

Ideas that go beyond what existing chess tools offer.

### Counterfactual Coaching
Don't just say "Nf3 is best." Play out the user's intended move AND the
engine's move 5-6 moves deep, side by side. Let the LLM narrate where the
lines diverge: "In your line, Black gets a passed pawn you can't stop. In
the engine's line, the knight controls d5 and that never happens." Teaches
*what you're not seeing*, not just *what's correct*.

### Socratic Mode
Don't give the answer. Ask questions: "What pieces are undefended?" "What
happens after Bxf2+?" Guide the user to find the move themselves. The engine
holds the answer key, the LLM plays the teacher who won't give it away.
This is how real coaches work — no software does it.

### Concept Tagging Across Games (Player Profile)
Track recurring mistakes across multiple games. "You've missed 4 back-rank
tactics in your last 10 games." "You consistently struggle in rook endgames."
Build a player profile over time and target coaching at actual weaknesses.
Turns a position analyzer into a coach that knows *you*.

### Engine Debate
Run analysis at two depths (or settings). When they disagree, have the LLM
explain both sides: "Quick analysis likes Qxd5 for the pawn. Deeper analysis
sees Black's devastating attack after ...Bxh2+." Teaches the user to think
deeper, not just follow instructions.

### Narrative Game Commentary
After a game, generate a story — not move-by-move annotations but a narrative
arc: "The opening was solid until move 12 where the game shifted. White's
knight sacrifice on f7 was the turning point..." Grandmaster commentary
style, not computer annotation style.

### Structured Learning Path — "Zero to Not Bad"
A curriculum that takes a complete beginner to a competent club player,
using the engine + LLM as a personal tutor.

Philosophy: NOT "find mate in 3" puzzle grinding. The goal is building
intuition and fundamentals that make you play the right moves in any
situation — understanding *why*, not memorizing *what*.

- **Stage 1 — Rules & Piece Movement**: Interactive lessons on how pieces
  move, capture, and special rules (castling, en passant, promotion).
  Puzzles: "Can the knight reach this square?"
- **Stage 2 — Don't Hang Pieces**: Focus entirely on not leaving pieces
  undefended. Engine detects hanging pieces, LLM explains why they're
  vulnerable. Drill until the user stops blundering material.
- **Stage 3 — Piece Activity**: Which pieces are doing nothing? Which
  squares are strong? Teach the user to ask "is this piece useful here?"
  every move. Engine evals show the difference between active and passive
  pieces.
- **Stage 4 — Pawn Structure Awareness**: Isolated pawns, doubled pawns,
  pawn chains, passed pawns. Not theory — just "this pawn is weak because
  nothing defends it" and "this pawn is strong because it can't be stopped."
- **Stage 5 — King Safety Intuition**: When is your king safe? When is it
  in danger? Teach the user to feel when an attack is coming before it
  lands. Engine eval swings near the king are the signal.
- **Stage 6 — Trading & Simplification**: When to trade pieces, when to
  keep them. "You're up material — trade everything and win the endgame"
  vs "You're attacking — keep the queens on." Engine lines show the
  consequence of each choice.
- **Stage 7 — Basic Endgames**: K+R vs K, K+Q vs K, king and pawn
  endgames. Concrete, engine-verifiable, and the area where beginners
  throw away the most wins.
- **Stage 8 — Opening Principles**: Not memorizing lines — learning
  principles (control center, develop pieces, castle early, connect rooks).
  Engine evaluates whether moves follow principles, LLM explains the *why*.
- **Stage 9 — Pattern Recognition**: Common tactical and positional
  patterns that arise naturally in games — not artificial puzzles but
  "you had this pattern in your last game and missed it."
- **Stage 10 — Putting It Together**: Play games against the engine at
  calibrated difficulty. Post-game review focuses on the current stage's
  concepts. Advance when the user consistently demonstrates understanding.

### Player Strength Profile
Track the user's understanding across fundamental dimensions over time:

- **Dimensions**: material awareness, piece activity, pawn structure,
  king safety, trading decisions, endgame technique, opening principles,
  tactical vision, time management
- **Per-dimension rating**: based on how often the user's moves align with
  engine recommendations *in positions where that dimension matters*
  (e.g., king safety rating based on moves in positions with attacking
  chances)
- **Weakness detection**: "You play well in open positions but struggle
  in closed positions" / "Your endgame technique is strong but you miss
  tactics in the middlegame"
- **Progress over time**: visual dashboard showing improvement per
  dimension across weeks/months
- **Targeted practice**: automatically generate or select positions that
  exercise the user's weakest dimensions
- **ELO estimate**: derived from game results + dimensional ratings,
  but the dimensions are what matter for coaching

### Adaptive Difficulty
The engine adjusts its play style to the user's level — not just weaker,
but making *human-like* mistakes at the right level. Play openings the user
needs to practice against. Create positions that test their weak spots.

## Future Features (from spec)

- [ ] PGN game review (User Story 9)
- [ ] Interactive follow-up questions about a position (User Story 10)
- [ ] Game navigation (forward/backward through loaded PGN)

## Coaching Quality — Eval-Driven Improvements

*Tracked via eval runs (scripts/eval_coaching_quick.py). Each item links
to the eval observation that motivated it.*

### Template coaching is too thin in quiet positions
- **Observed**: Starting position and post-1.e4 both produce only
  "The position is roughly equal. Look for ways to develop your remaining
  pieces." — two sentences with no real guidance.
- **Why it matters**: A beginner gets zero actionable advice. The coach
  should at least mention center control, development, or king safety
  as general principles when there's nothing tactically urgent.
- **Idea**: Add a "general principles" fallback section to
  `generate_position_coaching` that fires when no threats, hanging
  pieces, or tactics are detected. Content varies by coaching level:
  beginner gets "control the center," advanced gets "improve your worst
  piece."

### "Develop your remaining pieces" fires too often
- **Observed**: The `_best_move_text` fallback triggers on almost every
  opening position because the best move is usually a piece development.
  It's the same sentence every time.
- **Why it matters**: Repetitive advice teaches nothing. Users tune it out.
- **Idea**: Either vary the text (rotate between several development
  hints) or replace it with more specific guidance based on *which*
  piece should develop and *where* (e.g., "Your dark-squared bishop
  is still on its starting square").

### Move feedback doesn't explain *why* a move is bad
- **Observed**: For 1...f6 (a genuine mistake), the coach says "The
  engine had a better idea" but doesn't explain that f6 weakens the
  king diagonal and blocks the knight.
- **Why it matters**: The whole point of coaching is teaching the *why*.
  "The engine had a better idea" is what Stockfish already tells you.
- **Idea**: For the template path (`generate_move_coaching`), add
  heuristic explanations for common mistake patterns:
  - Pawn moves that weaken king safety (f3/f6, g3/g6 without fianchetto)
  - Moves that block piece development
  - Moves that lose control of key squares
  The comparison report already has `missed_tactics` and `refutation_line`
  for tactical mistakes — this would cover positional mistakes.

### Eval breakdown is underused
- **Observed**: The `eval_breakdown` (mobility, king_safety,
  pawn_structure) only surfaces in `_eval_summary` when the dominant
  factor is >30cp. In many positions it could add useful color.
- **Idea**: Lower the threshold or always mention the top factor when
  the position isn't dead equal. "White's advantage comes mainly from
  better piece mobility" is useful even at +0.40.

### Context-inappropriate advice in endgames
- **Observed**: Castling warnings, development advice, and opening
  principles fire in endgame positions where they're irrelevant.
- **Idea**: Add a position-phase detector (opening/middlegame/endgame
  based on piece count and move number) and gate template sections
  accordingly. Endgames should focus on king activity, pawn promotion,
  and technique — not castling.

### Opening moves penalized too harshly
- **Observed**: 1...e5 called an inaccuracy at depth 8. See BUG-008.
- **Idea**: Use the opening book as a whitelist. If a move leads to a
  known opening position, treat it as "good" regardless of the engine's
  shallow eval. The current code already checks `lookup_fen` and uses
  a 150cp threshold for book moves, but it checks the *post-move*
  position — the move itself (e5) might not be in the book while the
  resulting position is. Needs investigation.

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
