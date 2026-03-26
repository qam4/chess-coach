# Coaching Philosophy

Design principles for chess-coach's advice quality, derived from
real-world testing on mobile (March 2026).

## Core Insight

The engine knows *what* is best but not *why* in human terms. Our job
is to translate engine data into actionable advice that helps the player
improve — not just report numbers.

## What Good Coaching Looks Like

A real coach would say: "Your biggest issue right now is your
undeveloped kingside. Get that knight to f3 and castle. The center
is stable so you have time."

That's: prioritized (one thing, not everything), actionable (specific
move suggestion), and contextual (explains why it's safe to do it now).

## Current Pipeline (Play Mode)

```
User plays a move
│
├─ Step 1: coach compare (FEN_before, user_move)
│  → ComparisonReport: classification, eval_drop, best_move_idea,
│    missed_tactics, top_lines
│  → Generates: "Good move" / "Inaccuracy" / "Blunder"
│  → Data: overall cp only, NO eval breakdown
│
├─ Step 1b: coach eval (FEN_after_user_move) [NEW]
│  → PositionReport with full eval breakdown
│  → Diff with previous position → "your move improved mobility
│    but weakened king safety"
│  → Priority coaching: what matters most right now
│
├─ Step 2: engine.play(FEN_after_user_move)
│  → Engine picks its response move (at reduced Elo)
│
├─ Step 3: coach eval (FEN_after_engine_move)
│  → PositionReport: full breakdown, threats, hanging pieces,
│    pawn structure, king safety, top lines, tactics
│  → Generates coaching text about the resulting position
│
└─ Returns: user_feedback + move_impact + engine_move + coaching_text
```

## Threat Relevance

Not all threats are worth mentioning. A bishop "can give check" is
technically true but useless if the bishop would be captured.

### Threat tiers:

1. **Hanging pieces** — always real, always urgent. If a piece is
   undefended and can be taken, say so.

2. **PV threats** — the engine plans to execute these. But telling
   the player "watch out, you can't stop this" isn't helpful.
   Instead: focus on minimizing damage or finding counterplay.
   "Your position is under pressure on the kingside — look for
   counterplay on the queenside."

3. **Non-PV threats** — the engine found something better, but these
   are still dangerous if the player doesn't see them. These are
   the most coachable: "Be careful not to allow Bxf7+ — keep your
   f-pawn defended." Actionable prevention advice.

4. **Theoretical threats** — moves that are legal but the engine
   would never play (e.g., a check that loses the piece). Skip these.

## Eval Breakdown Diffs

Comparing eval breakdowns before and after a move tells the story
of what the move actually did:

```
Before: mobility +10, king_safety -5, pawn_structure 0
After:  mobility +35, king_safety -5, pawn_structure -10

→ "Your move improved piece activity (+25cp) but weakened your
   pawn structure (-10cp)."
```

This is more useful than "your move lost 10cp" because it explains
*what* changed, not just the net result.

## Priority Coaching

Don't dump everything on the player. Pick the 1-2 most important
things, in this order:

1. **Immediate material threats** — hanging pieces, undefended material
2. **Preventable threats** — non-PV threats the player can stop
3. **Biggest positional weakness** — the worst eval component
4. **Improvement direction** — what the engine's top line suggests

## What We Don't Do (Yet)

- Compare to the "best" move's breakdown (requires extra engine call,
  and over-indexes on one specific move)
- Explain *why* the engine's move is better in human terms (hard
  without understanding chess concepts at a deeper level)
- Track patterns across games (player profile / weakness detection)
- Adapt advice to the player's actual skill level over time

## Open Questions

- How much does the extra `coach eval` call cost on mobile? (~1-3s
  at depth 8 — acceptable if the coaching quality improves noticeably)
- Can we use the PV line themes to generate better "what to focus on"
  advice? The themes are engine-generated strings — quality varies.
- Should we cache the previous position's report to avoid re-evaluating
  it? (The engine already evaluated it on the previous turn.)
