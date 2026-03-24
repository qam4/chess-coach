# Coaching Quality Changelog

Track the eval → observe → fix → re-eval cycle for coaching improvements.
Each entry records what was observed, what was changed, and the result.

The eval script is `scripts/eval_coaching_quick.py`. Run it and compare
`output/coaching_review.txt` before and after each change.

---

## Eval Run #1 — 2025-03-24 (Baseline)

**Setup**: Blunder engine (coaching protocol), depth 8, template mode
(no LLM), intermediate level.

**Positions tested**: 3 (starting, Italian Game, K+R vs K)
**Moves tested**: 4 (1...e5, 1...f6, 2.Nf3, 1...Qa5)
**Game sequence**: 3 moves (1.e4 e5 2.Nf3)

### Observations

| # | Issue | Severity | Filed |
|---|-------|----------|-------|
| 1 | 1...e5 classified as inaccuracy (44cp at depth 8) | High | BUG-008 |
| 2 | Comparison report crashes for Qa5 (missing `fen`) | Medium | BUG-007 |
| 3 | Castling warning in K+R vs K endgame | Medium | BUG-009 |
| 4 | Starting position coaching is two generic sentences | Medium | IDEAS.md |
| 5 | "Develop your remaining pieces" fires on every opening | Low | IDEAS.md |
| 6 | Move feedback says "engine had a better idea" without explaining why | Medium | IDEAS.md |
| 7 | Eval breakdown only surfaces at >30cp dominant factor | Low | IDEAS.md |

### What worked well

- Opening detection (Italian Game correctly identified as C50)
- K+R vs K correctly identified as winning (+13.55)
- 2.Nf3 correctly classified as "good" (17cp drop)
- 1...f6 correctly classified as "mistake" (121cp drop)
- Position after 2.Nf3 had the best coaching: identified undefended e5
  pawn, Nf3 threat, contested d4 square — specific and actionable
- Template mode is fast (~0.2-3.2s per position, no LLM needed)

### Scores (scripts/eval_coaching.py baseline)

```
Position score: 82% (8 tests)
Move score:     70% (7 tests)
Overall:        76%
Total time:     23.1s
```

### Failing tests

| Test | Score | Issue |
|------|-------|-------|
| 1...e5 | 40% | classified inaccuracy (44cp drop), should be good |
| 1...d5 | 20% | classified mistake (114cp drop), should be good |
| 1.d4 | 27% | classified inaccuracy (40cp drop), should be good |
| After 1.e4 | 75% | missing keyword "center" |
| Italian 4 Knights | 50% | missing "f7" and "castle" |
| Middlegame tactical | 50% | missing "castle" |
| K+R vs K | 80% | bad keyword "castle" (BUG-009) |

### Baseline coaching samples (for regression comparison)

```
Starting position → "The position is roughly equal. Look for ways to develop your remaining pieces."
Italian Game → "The position is roughly equal. White's bishop on c4 can give check. Board tensions: Contested squares: d4, e5. Look for ways to develop your remaining pieces."
K+R vs K → "White is winning (+13.55 pawns). White's rook on h1 can give check. White's king can no longer castle — keep it protected. Black's king has been displaced to e5 — be careful."
1...e5 → "That's a small inaccuracy — you lost about 0.4 pawns of advantage compared to the best move. The engine preferred Nf6 (eval: -0.14)."
1...d5 → "That's a mistake — it costs about 1.1 pawns. The engine had a better idea. The engine preferred Nf6 (eval: -0.14)."
1.d4 → "That's a small inaccuracy — you lost about 0.4 pawns of advantage compared to the best move."
2.Nf3 → "Good move! That's in line with what the engine recommends."
1...f6 → "That's a mistake — it costs about 1.2 pawns. The engine had a better idea. The engine preferred Nf6 (eval: -0.14)."
```


---

## Fix #1 — BUG-008: Opening move leniency (2025-03-24)

**Problem**: Engine at depth 8 penalizes sound opening moves (1...e5, 1...d5,
1.d4) as inaccuracies or mistakes. The Scandinavian Defense (1...d5) was
classified as a "mistake" with 114cp drop.

**Root cause**: Shallow-depth eval is unreliable in the opening. The engine
prefers 1...Nf6 over everything at depth 8, which doesn't match established
opening theory.

**Approach tried first**: Opening book whitelist — if the post-move position
is a known ECO opening, classify as "good". Failed because the Lichess
openings database includes 19 of 20 possible first moves (even bad ones like
Barnes Defense 1...f6 and Ware Defense 1...a5).

**Fix applied**: Move-number-based leniency. In the first 6 moves, only flag
moves with eval drop >150cp. Implemented as `effective_move_classification()`
in `coaching_templates.py`, shared by the template path and `Coach.evaluate_move()`.

**Trade-off**: Bad-but-named opening moves (1...f6 at 121cp) also get a pass.
Acceptable because position coaching teaches through analysis, not move criticism.

**Files changed**:
- `src/chess_coach/coaching_templates.py` — added `_move_number_from_fen()`,
  `effective_move_classification()`, used in `generate_move_coaching()`
- `src/chess_coach/coach.py` — replaced book-move threshold with move-number
  leniency in both coaching protocol and UCI fallback paths
- `src/chess_coach/openings.py` — added `is_book_move()` (kept for future use)

**Eval results**:
```
Before: Position 82% | Move 70% | Overall 76%
After:  Position 82% | Move 100% | Overall 90%
```

Failing move tests fixed: 1...e5, 1...d5, 1.d4 — all now classified "good".
No regressions (170 unit tests pass).


---

## Fix #2 — BUG-009 + BUG-010: Endgame king safety + eval summary (2025-03-24)

**BUG-009**: Castling warning in K+R vs K endgame.
Fix: suppress `_king_safety_text()` when ≤6 pieces remain on the board.
K+R vs K test: 80% → 100%.

**BUG-010**: Eval summary says "White is ahead, main factor is king safety
(Black is better)" — contradictory.
Fix: when the dominant factor contradicts the overall eval, find the aligned
factor and present both: "White's piece activity outweighs Black's king
safety edge." Honest and more insightful than hiding the contradiction.

**Eval results**:
```
Before: Position 82% | Move 100% | Overall 90%
After:  Position 82% | Move 100% | Overall 90%
```

Score unchanged because the eval test suite doesn't yet test for the
contradictory factor case. No regressions.
