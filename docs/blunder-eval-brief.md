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

Property 3 is the important one. A horizon problem shrinks with depth. This does not. That
points at the **leaf evaluation**, not the search.

## Leading hypothesis (unverified)

**The binary we use is hand-crafted-eval only, and Blunder's rating may come from NNUE.**

Evidence, all circumstantial:

- `C:/src/blunder/build/dev/blunder.exe` exposes no `EvalType` UCI option. Full option
  list: `Hash`, `Book`, `BookFile`, `Mobility`, `Tempo`, `MultiPV`, `Skill`,
  `UCI_LimitStrength`, `UCI_Elo`.
- `scripts/bench-config.json` distinguishes `blunder-hce` from `blunder-nnue` via
  `options: {"EvalType": "nnue"}`, so the distinction is real and expected to be settable.
- No `.nnue` weights file anywhere under `C:/src/blunder` (only polyglot opening books).
- A tapered HCE — material, PSQT, mobility, tempo — predicts exactly this pattern: sound
  tactics because the search finds them, crude positional judgement because the static
  terms are thin, and no improvement with depth because the error is at the leaves.

**Check this first, it is cheap.** Which evaluator does the `dev` preset build? Is there an
NNUE-enabled build or weights file we should be pointing at? If chess-coach has been
running HCE while the 2500 figure was measured with NNUE, that reconciles everything and
this reduces to a configuration fix.

Two secondary things worth a look if the evaluator question comes back "HCE is expected":
the `Mobility` and `Tempo` terms are the only tunable eval knobs exposed, and a
mis-scaled mobility term is a classic source of over-pessimism in quiet positions.

## Doing it properly

The comparison above answers chess-coach's question, not Blunder's. To evaluate Blunder
fairly, equalise resources rather than depth, because depth is not comparable across
engines with different pruning:

1. **Equal nodes.** Both engines at a fixed node count (e.g. 200k, 1M). Removes hardware
   and search-speed differences and is the cleanest control for "is the evaluation
   better".
2. **Equal time.** Both at a fixed movetime (e.g. 1s, 5s). Matches how ratings are
   actually established.
3. **Static eval only.** Compare the leaf evaluation directly, with search removed or
   minimised — Stockfish has an `eval` command; if Blunder has an equivalent, this
   isolates the evaluation function, which is where properties 1–3 above point. This is
   the most diagnostic of the three.

Suggested acceptance question: at equal nodes, does Blunder's signed error on quiet
positions stay near +90cp, or collapse toward zero? If it stays, the evaluation function
is the problem. If it collapses, chess-coach simply under-resourced the engine and should
change its own configuration.

Also worth widening: 44 positions from one game, 20 of them quiet, is enough to see an
effect this size but not to characterise it. A standard quiet-position suite would be
better.

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
