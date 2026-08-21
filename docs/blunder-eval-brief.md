# Brief: is Blunder's static evaluation weak on quiet positions?

For a Kiro session in the Blunder repo. Written from chess-coach's measurements; the
question it raises belongs to Blunder.

## The claim, scoped honestly

**What we measured:** chess-coach's shipping configuration — Blunder via the `coach
compare` protocol at **depth 8** — against **Stockfish 18 at depth 22**, on 44 positions
from one game.

**What that supports:** the numbers chess-coach feeds its coaching layer are far from the
best available estimate of truth, in a consistent direction, on a identifiable class of
position.

**What that does NOT support:** any statement about Blunder's playing strength, or that
Blunder is a weak engine. Depth 8 vs depth 22 is not a fair fight and was never intended
as one. **Do not treat the numbers below as an engine-strength comparison.** See
"Doing it properly" for the controls a real evaluation needs.

## The signature to explain

Signed error = Blunder's eval drop minus Stockfish's, for the side that moved. Positive
means **Blunder thinks the move cost more than it did**.

| condition | signed error | mean abs | n |
|---|---|---|---|
| quiet positions, Blunder depth 16 | **+92 cp** | 109 | 20 |
| concrete positions, Blunder depth 16 | +18 cp | 64 | 23 |
| quiet, Blunder depth 8 | +76 cp | 103 | 20 |
| concrete, Blunder depth 8 | **+3 cp** | 59 | 23 |

"Concrete" = the move is a capture, gives check, is made in check, or the engine reports a
tactical motif. "Quiet" = none of those.

Four properties, all measured:

1. **Directional.** Blunder systematically overestimates how much a quiet move costs.
   Eight of the ten largest errors are in this direction.
2. **Class-specific.** On concrete positions at depth 8 the signed error is +3cp —
   essentially unbiased. The problem is confined to quiet positions.
3. **Not depth-sensitive.** Going from depth 8 to depth 16 moved Blunder *closer* to the
   reference on 18 positions and *further* on 20. Label agreement went 24/43 to 25/43.
   No convergence with search depth.
4. **Not a reporting bug.** The `coach compare` protocol and plain UCI, on the same binary
   at the same depth, differ by signed −2.6cp. The protocol reports faithfully.

Property 3 is the important one. A horizon problem shrinks with depth. This does not,
which locates the disagreement in the **leaf evaluation** rather than the search — and
that is consistent with a hand-crafted evaluation being a coarse instrument on quiet
positions, without anything being broken. See the reframe below.

## A hypothesis we already killed

Our first guess was that chess-coach runs an HCE build while Blunder's 2500 figure came
from NNUE, which would have reduced all of this to a configuration mistake on our side.

**Wrong.** Per Blunder's author: the 2500 rating is HCE, release build. HCE *is* the rated
evaluator, and dev vs release is a latency difference at fixed depth, not a strength one.
So there is no wrong-evaluator explanation available. Recorded here so nobody spends time
re-deriving it.

## The reframe that follows, and it may be the whole answer

If HCE at release is a genuine 2500, then **playing strength and per-position evaluation
accuracy are not the same quantity**, and chess-coach conflated them.

An engine earns a rating over whole games, where search depth compounds, tactical
opportunities are found, and evaluation errors partly cancel across many moves. None of
that requires the static evaluation of an arbitrary quiet position at depth 8 to be within
a pawn of the truth. A tapered hand-crafted evaluation — material, PSQT, mobility, tempo —
is a coarse instrument for exactly the judgement chess-coach leans on hardest, and
Stockfish's NNUE is enormously better at it essentially by construction.

Under that reading the measurement is not a defect report at all. It is chess-coach
discovering that "2500 Elo" never implied "trustworthy per-position verdicts", which is an
architectural mistake on our side, not a bug on Blunder's.

**This is the first thing to decide, because if it holds, most of the rest is moot.** If
an HCE engine is doing what HCE engines do, then no Blunder-side work fixes chess-coach,
and chess-coach has to stop asking the engine for judgements it cannot supply.

## What we are NOT prescribing

How to investigate this is Blunder's call, in Blunder's repo, with Blunder's tooling.
We deliberately do not recommend an instrument, a suite, or a method — an earlier draft of
this brief did, and that was overreach from a caller that does not know the codebase.

Two constraints on interpreting our numbers, which are the only things we do insist on:

1. **Our comparison used unequal search depth** (Blunder 8 and 16 versus Stockfish 22) and
   is therefore not a fair engine comparison. Whatever controls make it fair — equal
   nodes, equal time, static eval only — are for Blunder to choose.
2. **Do not go looking for a bug to match our numbers.** We already lost time on a stale
   binary theory that way. The finding may well have no defect behind it, per the reframe
   above.

Sample size caveat: 44 positions from one game, 20 of them quiet. Enough to see an effect
of this magnitude, not enough to characterise it.

## Data

- `output/bias_v31_stockfish.json` — per-turn Blunder depth 8 (coach protocol) vs
  Stockfish depth 22, with FEN-derived move, phase, concreteness, and both best moves.
- `output/fair_v31_abcd.json` — the same 44 turns four ways: coach protocol depth 8,
  plain UCI depth 8, plain UCI depth 16, Stockfish depth 22.
- `output/depth_sweep_v31.json` — Blunder at depths 8/10/12/14, with classification and
  chosen best move at each depth.
- Positions come from `output/coach_review_v31/transcript.json` (`fen_before` +
  `student_move_san`).

Reference used: Stockfish 18, official release via winget, `Threads 2`, `Hash 256`,
`depth 22`.

## Worst quiet-position disagreements

Blunder depth 16 minus Stockfish depth 22, worst first. These are the positions to explain.

| ply | move | Blunder d8 | Blunder d16 | Stockfish d22 | error |
|---|---|---|---|---|---|
| 30 | `Bc4` | 878 | 859 | 294 | +565 |
| 34 | `Ke2` | 413 | 457 | 72 | +385 |
| 1000 | `e5` | 323 | 355 | 5 | +350 |
| 20 | `Kd1` | 673 | 726 | 422 | +304 |
| 60 | `Kf3` | 180 | 248 | 20 | +228 |
| 52 | `Nc3` | 184 | 207 | 2 | +205 |
| 40 | `Kf3` | 143 | 179 | 22 | +157 |
| 46 | `c6` | 144 | 213 | 64 | +149 |
| 78 | `Ke5` | 0 | 34 | 181 | −147 |
| 26 | `Bd4` | 67 | 68 | 197 | −129 |

Note ply 1000: an eval drop of 355cp at depth 16 on a move the reference scores at 5cp.
That one position, if explained, probably explains the class.
