# Coach report card — progression log

The **coach report card** is a single-mode holistic review (not an A/B): it
plays one real game, coaches every student move with the shipping config while
timing each generation, appends curated endgame/tactic positions for phase
coverage, then a frontier reviewer (claude-sonnet-4.6 via kiro-cli) returns one
verdict — a **0–10 score against the VISION "bridge" standard** plus honest
critique and phase-fit. It answers "is the coach the teacher we envisioned?".

- Tooling: `scripts/eval_coach_review.py` (driver) + `src/chess_coach/eval/coach_review.py` (pure core).
- Run: `--seed 7` fixes the game so successive runs are a clean before/after.
- Artifacts live under `output/` (gitignored); results are recorded here.

## Ledger — what the judge flagged, what we did, what happened

Newest last. One row per finding, so the loop is auditable: a review names a
problem, we make one change, we measure, and the row records whether it worked —
including the changes that did not, and the findings that turned out to be about
our own measurement rather than the coach. Detail for each is further down.

| # | Judge flagged | What we changed | Outcome | Verdict |
|---|---|---|---|---|
| 1 | Generic, recycled advice | Removed the always-on "CHESS PRINCIPLES" crib | Score +0.7, fabrication counts flat | kept |
| 2 | Fabricated causal chains ("Bc4 allows Nxd4") | Grounding rule forbidding unverifiable causes | No measurable effect — negative constraints do not work on this model | **reverted** |
| 3 | Same tone for a slight slip and a blunder | Severity tiers from our own eval-drop bands | Violations 13 -> 6 | kept |
| 4 | Verbose for the content delivered | Per-tier word limit + `max_tokens` | Replies shortened as designed | kept |
| 5 | Refutations too vague | State the full refutation line | Move-salad; `illegal_move` 0 -> 5 | **reverted** |
| 6 | (same) | Opponent's *single* first reply + opponent-aware checker | `illegal_move` -> 0 | kept |
| 7 | Leads with principle, not position | Reorder prompt: position before principle | Cost accuracy — placement/piece_type doubled | **reverted** |
| 8 | Wrong captured piece in opponent replies | Compose the captured piece from the board | Corrected a hallucination at zero cost | kept |
| 9 | Best move explained generically | Voice the engine's `best_move_idea` | Necessary but insufficient — the label has only 10 distinct values | kept |
| 10 | Closing maxims are interchangeable | Named principle + "next time you see X" hook | Kept on the judge's direct recommendation | kept |
| 11 | Coach parroted coordinates and invented what the move did | Correct SAN base position + truncate, never emit coordinates | Prompt leaks 27/44 -> 0/44 | kept |
| 12 | Coach misattributed whose move it was | Numbered SAN (`5...Nfg4 6.f4`) | Violations 8 -> 6, `piece_type` -> 0 | kept |
| 13 | Best-move "why" still a category label | Compose a board-derived clause (item 3) | Specificity 34% -> 52% (corrected figures) | kept |
| 14 | Guidance is abstract prose the model echoes | Instantiate each theme with the fact that fired it (item 4) | Cleanest fidelity of the series; teaching effect unmeasured | kept |
| 15 | (our finding) 30% of best moves had no description | Clauses for quiet moves: open file, mobility, castling, extra defender (Change A) | Coverage 70% -> 89% | kept |
| 16 | (our finding) Coach handed an EMPTY engine-lines section on 19/44 turns | Root-caused to a stale reference in the engine; fixed blunder + per-line base in the client | Empty sections 19 -> 0, rendered lines 25 -> 131; fidelity flat | kept |
| 17 | "Catastrophic square-naming failure — 0% novel squares" | Nothing in the coach: this was our own metric handed over without saying which direction was good | Re-judged the identical transcript: became **strength #2**, "the 66% board-fact voicing and 0% invented squares are exactly right" | **was our bug, not the coach's** |
| 18 | Same three lessons all game (counted by hand, twice) | Measured it: `lesson_concentration_rate` (4th design; two earlier ones deleted) | 82% (v17) -> 57% (v20) -> 68% (v21); judge now cites the number and confirms it independently | kept |
| 19 | Closing question recycled; "one of three templates" | Compose the closing lesson from what the move verifiably DOES, instead of letting the model pick | Bogus hooks gone ("fork opportunity" on a move that forks nothing: 3 turns -> 0); no closing repeats more than twice; concentration 68% -> 66% (metric under-reports, see below) | kept |
| 20 | Composed lessons are phase-blind (endgame taught as opening) | Phase-gate the lesson table: endgame rook-behind-passed-pawn, king as attacker, etc. | **Did not land.** Distinct lessons 11 -> 18 and top-3 coverage 57% -> 30% in the prompt, but only 2/18 endgame turns mention a passed pawn and none mention promotion or the king as a fighting piece — the model paraphrases the lesson back into its own vocabulary | kept (free, no fidelity cost) but ineffective |
| 21 | (our finding) The judge itself was wrong on 5 of 5 per-ply factual claims | Switched the default judge to `claude-opus-5` | On the same transcript opus-5 got 2 of 2 right and found two real defects the checker misses | kept |
| 22 | Coach text incoherent at ply 28 ("your opponent plays e3 … your pawn on e3 is undefended") | Name the piece, not the bare square: `"threatens your pawn on e3"` via a new `_describe_target` | v24: ply 28 reads correctly | kept |
| 23 | Our own centrality clause downgraded a more central king move (ply 1002) | Suppress the king-walk clause unless it beats the student's move (`rival_uci`) | Clause gone from the prompt — but the model now fabricates "closer to the center" unprompted | kept, insufficient |
| 24 | "Endgame: most turns, worst pedagogy, and it is inverted" — king safety preached on plies 52, 60, 76, 1000, 1002; a centralized king called "exposed" | `excludes_features` on guidance entries; `principle.exposed_king` excludes `phase:endgame` | The entry was in all five prompts, now in none — replaced by passed-pawn / king-activity / open-file guidance | kept |
| 25 | Ply 36: "capturing the undefended bishop on b4" when `bxc4` took a knight — and the checker said nothing | Widened `_CAPTURE_CLAIM_RE` to allow up to two words (adjectives) between the article and the piece noun | The check now fires on ply 36; "wins a pawn" idiom and "takes control of the bishop's diagonal" still clean | kept |
| 26 | (v25) Same endgame complaint again, because the guidance entry was only one of three sources of "king safety" | Drop the engine's king-safety idea label in endgames (keeping any verified clause), and remove the hardcoded "is my king safe?" example from the PEDAGOGY block | **v26: landed.** King-safety frames on endgame achievement lines 8 -> 0, and the coach's own endgame text 4/18 turns -> **0/18**. Lesson concentration 57% -> **45%** (series best), composed-fact 61% -> 66%, real violations flat at 2, score 4.3 -> 4.5. The judge's endgame complaint changed from "inverted / actively wrong" to "shallowest" | kept |
| 27 | (our finding, while checking v25) Two checker false positives at ply 60 | `Be6` naming a piece that already stands there is no longer read as a move; a capture claim attributed to the opponent is no longer judged against the victim of OUR named move | Both gone; the 2 remaining text-level violations in v25 are real coach errors | kept |
| 28 | (blind audit) Manufacturing fault on moves that were fine — classed **harmful**, not imperfect: 10 of 44 turns, at drops of 0-17cp | New `equal` tier under 25cp that withholds the alternative from the prompt entirely, describing the student's own move instead | All 10 turns now on a no-comparison tier; prompt-side verified, output unmeasured (needs v27) | kept, unmeasured |
| 29 | Harness bookkeeping voiced as a chess reason ("the evaluation spread shows it was a key decision", plies 12/18/24) | Stop passing the engine's `critical_reason` — its only format is "eval spread between best and Nth-best line is Xcp" — while keeping the critical-moment flag | Eval-spread text in the prompt: 20 turns -> 0 | kept, unmeasured |
| 30 | (our finding) The score never discriminated between coach versions | Rebuilt the ask as a per-category rubric with gates, derived externally (rubric v2), and re-judged the **identical** v26 transcript under both asks | Old ask 4.5, new rubric **2/10** — pre-gate weighted 4.3, capped by the fidelity gate on one false claim at ply 36. The two asks agree on quality and disagree on what to do about it | kept |
| 31 | (rubric v2) One false board claim makes everything else worth nothing — "nothing else you do can score above 2/10 while ply 36 is possible" | **next** — wire the existing fidelity check into the send path (regenerate once, then a composed fallback) | — | open |
| 32 | (rubric v2) The prompt orients around the engine's best move, so the model explains why THAT move is good and reverse-engineers a lesson from it | **next** — supply the cause of the student's loss as a first-class composer field and key the takeaway to it | — | open |
| 33 | (v27) Verified the three shipped fixes | `equal` tier, no eval bookkeeping, fidelity gate on the send path — all measured in output | Comparisons on fine moves **7/7 -> 0/7**; eval talk 6 turns -> 1; gating violations **2 -> 0**. Gate fired exactly once (ply 40) and fell back to composed text. Pre-gate rubric score **4.3 -> 5.2**; old ask still 4.5 | kept |
| 34 | (v27, rubric v2) The gate fired on an **ownership** error our checker cannot see: ply 44 "your own bishop on b4" when b4 is Black's | **next** — add an ownership check, and put a side tag on every composed fact ("developed minors: Bb4" has none) | — | open |
| 35 | (our finding) The composed fallback prints raw evals (`eval -12.9 -> -14.3`), a listed defect, and the coach parroted the new "What your move achieves:" header verbatim at ply 0 | **next** | — | open |
| 36 | Lesson concentration regressed 45% -> 55%: cues got blunter ("a check" for "a check that forces an answer"), mean cue length 4.0 -> 3.88 words | **next** — cue sharpening | — | open |
| 37 | (v28) Ownership check landed | Gates the send path; fired on ply 44 and fell back to composed text | Ownership violations **1 -> 0**. Ungated rubric score 5.2 -> **5.7**; concentration 55% -> 50%, recycled 18% -> 15%. Still 2/10 gated | kept |
| 38 | (v28, rubric v2) The gate fired on a **third** class: relationship geometry — "Ke2 helps protect your pawn on g2" (e2 covers f2), "Ke3 supports your passed pawn on d5" (e3 does not touch d5) | **next** — one general check for the family (X defends/protects/attacks Y), not a fourth patch | — | open |
| 39 | (our finding, retraction) The eval fix was HALF a fix and the header rename FAILED | Raw evals 1 -> 0, but pawn-unit costs remain and the judge flagged them under Stance. Header echoes went **0 (v26) -> 6 (v27) -> 8 (v28)** — renaming a label does not stop it being copied | eval: partial; header: **reverted in effect, needs removing not renaming** |
| 40 | (our finding) `off_menu` 1 -> 3, and one is our own fallback template naming `d5`; the judge called that same text unusable ("no owner or purpose") | **next** — the fallback is what a student sees when we distrust the model; it should be our best composed sentence, not our worst | — | open |
| 41 | (v29) The relation check closed the family | One geometric check over defends/protects/supports/guards | Gating violations **2 -> 0**. Header echoes **8 -> 0** (removing the label worked where renaming failed), pawn units **2 turns -> 0**. Ungated score 5.7 -> 5.05 — truth up, repetition down | kept |
| 42 | (v29, rubric v2) The gate fired on two classes **already on the backlog since v24/v26**, not a new one: mate called "a check" (ply 1003) and intent the coach cannot know (ply 38, "aimed to develop your king's bishop" with no bishop on the board) | Terminal-move check added, gating the send path, plus a mate branch in the composed fallback | Both landed. Terminal check catches ply 1003 in **all four** stored runs; intent check catches ply 38 in all four. Zero false positives over ~176 turns after one was found and fixed | kept |
| 43 | (our finding) Repetition regressed while truth improved: concentration 50% -> 57%, recycled 15% -> 17%, Stream Behaviour 4 -> 3, plies 74/78 word-for-word identical and 64 a near-copy | **next** — the judge's SMALL stream fix, which it predicts takes concentration to ~30% | — | open |
| 45 | (v30) Both new checks held: zero gating violations left in the shipped text, ply 1003 now reads "That's checkmate — Ra8# ends the game" and ply 38 no longer invents a bishop | Terminal + intent checks | Fallbacks 3 -> 5, as predicted before the run. Ungated 5.05 -> 5.6; concentration flat at 57% | kept |
| 47 | (owner question) **The harness never called the coach.** It rebuilt the pipeline, so the shipping rule that keeps the coach SILENT on good moves was never on its path — it coached all 44 turns where the product coaches 17 | Harness now calls `Coach.evaluate_move`, taking prompt/latency from the debug callback and the engine reports from the result. ~40 lines and 6 imports deleted | **Retracts three reports.** The "byte-identical plies 74/78" defect is on 0cp turns no student sees; "43 of 44 turns get commentary" describes the harness; concentration is computed over turns that never ship. Third drift of the same root cause | kept |
| 48 | (fell out of 47) **The coach is silent on checkmate.** `Ra8#` has a 0cp drop, so the skip rule suppresses it entirely | A game-ending move now always speaks — mate, stalemate or draw — on both the coaching and the fallback path so they cannot disagree | Ra8# went from 0.0s (silent) to 7.5s (coached). The model then described mate wrongly, the terminal check caught it, and the student read "That's checkmate — Ra8# ends the game" plus the rook-mate lesson. **The two fixes only work together**: the skip rule makes it speak, the check makes it true | kept |
| 49 | (fell out of 47) The judge credited the silence unprompted — "restraint on near-best moves is a real virtue and it has it" — a shipped behaviour never once credited before, because the harness hid it | — | — | noted |
| 50 | **v31 — first run measuring what actually ships.** The gate did NOT fire for the first time in five runs | Nothing new: this is v30's coach, measured honestly | **2/10 -> 5.7/10.** Every category up. Concentration **57% -> 18%**, recycled phrasing **16% -> 4%**, fidelity violations 3 -> 1, all with no change to the coach — the repetition problem was mostly the harness | kept |
| 51 | (v31, our finding) **Two real mistakes get no comment at all**: ply 6 `Ng5` (91cp) and ply 8 `b3` (138cp) are silent, because the opening rule suppresses anything under 150cp in the first six moves — and `Ng5` is the move the reviewer has repeatedly blamed for losing a knight later | **next** | — | open |
| 52 | (v31, rubric v2) "Fidelity is one flagged claim from capping the whole score at 2 — the margin is thin, not comfortable." Its top recommendation: stop gating speech on eval drop, gate it on whether a teachable engine-checkable feature exists (MEDIUM) | Measured the candidate detectors before building them | **Rejected.** No free board signal recovers the silenced turns: `critical_moment` catches 1 wanted turn at the cost of 12 unwanted; loose-piece and material-winning-capture fire 0/6 and 0/5 wanted; ply 6 is invisible to all of them | closed — measured and rejected |
| 53 | (our finding, retraction of row 51) The 150cp opening leniency is **not** arbitrary or obsolete. `0d0d664` added it for BUG-008: at depth 8 the engine scores book moves as mistakes. Still true, and worse than recorded — Ruy Lopez Morphy `...a6` = 110cp, Sicilian `1...c5` = 109cp, both "mistake", while the genuinely bad `1.f3` = 52cp | Nothing — the proposed change (150 -> 50) would have the coach criticise the Sicilian | **Proposal withdrawn.** Book exemption also fails: ECO names bad openings (Damiano, Grob, Barnes, Borg all `is_book_move=True`), and an eval cap cannot separate them — sound and bad populations overlap 52..110 at depth 8 and 65..114 at depth 12 | closed — keep the rule |
| 54 | (our finding) Depth sweep, all 44 v31 turns at depths 8/10/12/14: speak/silence decision **never** changed; label changed 5/44; recommended best move changed 10/44 (ply 4 gives four different moves at four depths). Instability tracks **concreteness**, not phase — quiet 22.9cp mean swing vs concrete 3.6cp | Nothing yet | Reassuring at the time, and **void** — see row 56. Self-consistency is not correctness | superseded |
| 55 | (our finding, retraction of the row-54 reading) I retracted `Ng5` as "not a mistake" because Blunder's own deeper search kept lowering it (91 -> 24). Stockfish 18 depth 22 says **115cp**. Blunder moved *away* from the truth with depth | Nothing — this was a reasoning error on our side | **Retraction retracted.** `Ng5` is a real mistake and the reviewer was right about it all along. Conversely `b3` (138cp) is only 54cp by Stockfish, so it is *not* a mistake. Both halves of row 51 are dead, for opposite reasons | closed |
| 56 | (our finding) **Blunder vs Stockfish 18 on all 44 turns.** Our label disagrees with the reference on **20 of 44**. Disagreement concentrates where we talk: on the 18 turns the coach spoke, mean absolute error 139cp, signed **+122cp**, best-move agreement **4/18**. At least 7 of those 18 criticised a move Stockfish scores good or near-good | Nothing yet — diagnosis first | **The `equal`-tier work (row ~44) fixed the coach, not the cause.** We stopped the model inventing faults on good moves; the *input* still said they were bad moves | open — top item |
| 58 | (Blunder session, answering row 57) **No Blunder defect.** Its HCE has no KPK rule, no key squares, no endgame draw-scaling; only repetition and the fifty-move rule. Static leaf on the drawn KPK position recomputed from source at ≈+230..258. Search makes it *worse* because the passed-pawn rank bonus `{15,36,57,78,99,120}` and the king endgame PSQT (peak ~+199) both grow as the PV walks the pawn up, so every leaf looks more winning | Nothing — diagnosis only, Blunder's tree untouched | Confirmed at **equal nodes** (1M each): Blunder +351 and climbing, Stockfish 0..2. Latency is *not* the constraint — the dev build does ~3M nps and reaches depth 15 on that endgame in under 20ms. "Giving it a second per position produces a stable number, not a truer one." **Kills raising `coaching_depth` permanently** | closed |
| 59 | (our finding, retraction of a retraction) I told the owner the KPK draw is invisible to static eval in **both** engines, so the fault lay in Blunder's search rather than its leaf eval. Wrong: attempt 1's +2.85 was Stockfish's **classical** eval; its default **NNUE** static eval prints +0.01, final **+0.00** | Nothing | **The original leaf-evaluation framing was right and my walk-back was wrong.** Both the claim and its retraction rested on one unreplicated measurement each — the recurring error on this thread | closed |
| 60 | (Blunder session, source-verified) **Blunder's reported cp are NOT conventional centipawns and are not normalized at all.** `PIECE_VALUE_BONUS` pawn = **124 (MG) / 206 (EG)** — Stockfish-classical-derived piece values. The taper is `(mg*p + eg*(PHASE_MAX-p))/PHASE_MAX`, so one pawn slides continuously 124 -> 206 by phase. No division, no `/100`, no WDL mapping anywhere on the UCI path (`Search.cpp:441` prints `pvline.score` verbatim); the `tanh(score/400)` in `MCTS.cpp:236` is the MCTS value head and unrelated. No `UCI_NormalizeToPawnValue` equivalent | Nothing — this is a fact to know, not a defect | **All our historical cp figures are in Blunder units, ~1.2–2x conventional.** So our 50/100/150 thresholds are tighter in real terms than they look | closed |
| 61 | (our finding, **retracting my own row-60 claim from an hour earlier**) I claimed roughly half the quiet-position error was a unit-scale problem, from a single-constant best fit of k=1.91 against the 2.06 implied by the endgame pawn. **The phase-aware test refutes it.** Per-phase empirical slopes are endgame **0.79**, middlegame **1.88**, opening **0.76** against source-predicted 2.06/1.24/1.24 — contradictory and inverted. Phase-aware conversion scores **worse** (60.8 mean error) than a flat /2.06 (50.0) | Nothing | A flat divisor helps only because Blunder's errors are positively biased and dividing any inflated distribution shrinks it toward truth. That is curve-fitting, not calibration, and it will not transfer. **The disagreement is mostly not scale.** Labels barely move under any conversion: 23/43 raw, 24/43 at /2.06, 24/43 phase-aware, 25/43 at flat /1.42 | closed |
| 62 | (our finding) So "stop grading moves and quoting costs" survives every twist: raw, calibrated, and phase-calibrated all leave a 50–60cp residual against a strong reference, wider than our 50/100 label bands | **next** — stop asserting magnitude | — | closed by row 63 |
| 57 | (our finding) Ruled out our own plumbing and depth as causes. Coach protocol vs plain UCI at the same depth: signed **−2.6cp** (no systematic misread; 22cp of multipv nondeterminism). Depth 8 -> 16 buys **one** extra matching label (24/43 -> 25/43) and moves Blunder *closer* to the reference on 18 positions, *further* on 20 | Nothing — hands off to Blunder | Residual is a genuine **static-evaluation** disagreement: quiet +92cp signed at depth 16, concrete +18cp. No depth convergence = leaf eval, not horizon. King-move sub-hypothesis tested and **rejected** (endgame king moves are the best case, +18 vs +69) | open — Blunder-side |
| 46 | (v30, rubric v2) Both survivors were claims about the **opponent's** move — an exemption we created deliberately and forgot. Ply 46 "the opponent plays Bb7+": a real move from a line starting 24.a3, and the student's own c6 blocks the diagonal it checks along. Ply 14 "Nxc4, winning a pawn" when c4 holds a bishop — contradicted two sentences later in the same message | `opponent_reply` check: push the student's move, then verify the reply's legality, its claimed check, and what it captures | Catches both plies in **all five** stored runs — the coach makes these same two errors every time — and fires nowhere else across ~220 turns | kept |
| 44 | (owner observation) Every report card has replayed **one identical game** — verified byte-identical across v26-v29 — so no check had ever been tried on a second game, and the checks can now REPLACE what a student reads | `scripts/eval_check_breadth.py`: five FIXED games, no randomness, no judge | **Zero false positives and zero leaks across all five.** Four games at 0-6% fallback; one quiet Queen's Gambit at 21%, and all three of its flagged claims verified as **real coach errors** | kept |
| 63 | (closing rows 56/62) The coach asserted a precision it does not have: eval figures, an eval drop labelled "centipawns" when the unit is not centipawns, the engine's `classification`, its `nag`, per-candidate `cp`, per-line `depth`/`cp`, pawn-unit costs in the templates, and a "?? Blunder" badge in the web UI | Withheld all of it, rather than instructing against it (rows 2/39/41 say only withholding works on this model). Severity now reaches the student as the board-verified consequence — what the opponent's reply wins — and reaches the model only as tier tone plus word limit. Material is counted from the board in points; the standing is one of four coarse words | **Prompt-side: 18/18 spoken turns carried a magnitude -> 0/18**, re-rendered through the engine on the v31 positions. 79 occurrences of "centipawns" and 18 each of `Evaluation drop` / `Classification:` / `Annotation:` -> zero. **Output side, v32: 11/18 spoken turns graded or priced the move -> 0/12.** Withholding was sufficient; no gating check needed | kept |
| 66 | (v32, and a **correction to my own first reading of it**) `graded_or_priced` came back 3 and I nearly reported the change as having failed. All three were false positives: the regex matched `5 pawn` in "the e5 pawn", `2 pawn` in "your a2 pawn", `7 pawn` in "the h7 pawn" — a square's rank digit reading as a quantity. The mirror image of the `_SQUARE_RE` bug at row 17, in a metric written specifically to be able to fail | Guarded every digit with `(?<![a-h])`, and narrowed the pawn form to fractional figures or figures attached to cost language, so "wins 2 pawns" (a material count, checkable) is not a price. The four missed cases are now in the must-not-flag list | Corrected: **v31 11/18, v32 0/12**. The v31 hits are all genuine and all the same sentence — "That was a serious mistake" x7, "This was a serious blunder", "This was a critical mistake" x3 — i.e. the model faithfully echoing v31's own tier text, which said "This was a serious mistake — say so directly and plainly" | kept |
| 67 | (v32, **the run is confounded and it is worth more than the run was**) The Blunder binary we ran against reports **normalized** centipawns — roughly half the old values — and it changed between v31 and v32. Provenance unknown: the change is uncommitted in the Blunder tree (`NORMALIZE_TO_PAWN = 200` in `Constants.h`, sources touched 09:46-09:57 on 2026-08-24, `build/dev/blunder.exe` built 09:58 the same day), and the product owner did not make it. That repo also has a modified spec tasks file and stray `build_err.txt` / `make2.out`, so probably an agent session in the Blunder repo. **Do not record it as anyone's decision until someone confirms it** | Nothing on our side. Found from the data first: six plies that spoke in v31 went silent in v32, each with its drop almost exactly halved — 66->33, 67->34, 72->36, 53->27, 58->29, 60->30 — crossing below `SOUND_MAX_DROP_CP` and flipping "inaccuracy" to "good". Then confirmed against the engine directly rather than from the source diff: the brief's KPK position at depth 16 gave `score cp 355 nodes 122039` in the pre-change session log and `score cp 178 nodes 122039` from this binary. **Identical nodes, identical PV, half the score** — the search is untouched and only the output scale moved, which is exactly what the code comment claims | **The coach went from 18 spoken turns to 12 with no coaching change.** The threshold shift predicted when normalization was discussed, now observed: our 50/100/150 bands were calibrated on inflated units and are ~2x more lenient against normalized ones. v32 is therefore NOT a clean before/after for anything eval-derived (speak/silence, tier mix, `composed_fact_rate`, fidelity counts). The output-side grade result IS attributable, since the prompt carries no number at any scale | open — thresholds need re-deriving |
| 64 | (our finding, **retraction of row 28**) The `equal` tier never withheld the alternative. Row 28 recorded it as withheld "from the prompt entirely"; only the achievement line and the engine's idea label ever were. `Best move: d4` was rendered unconditionally, and the top-lines section named the engine's move again — both sitting three lines above the instruction "Do NOT offer an alternative… there isn't one", i.e. a negative constraint over data we supplied ourselves | Made both conditional on the tier. The second leak was found by the new cross-surface test, not by reading the code | Prompt-side verified: on the no-comparison tiers the engine's move now appears nowhere. **Row 28's "prompt-side verified" claim was wrong** and its output result was never measured either | kept |
| 65 | (our finding) Both `DROPPED_PARTIAL` entries in `engine_trust` closed, and one of its own entries corrected | `critical_reason` came off the position prompt (already off the move prompt); the dead v1 rich templates that still rendered `best_move_idea` were deleted. `test_engine_trust` now asserts **no** partial drops remain, inverted from asserting these two did | Zero partial drops. Separately: my first pass recorded `best_move_idea` as fully dropped — **wrong**, reading a real rendered prompt showed it still trails the composed clause as a theme label by design (rows 9/13). Re-recorded as `USED_UNVERIFIED` with what compensates | kept |

| 69 | **v33 — the clean read the confounded v32 could not give.** Same seed-7 game, corrected thresholds, normalized engine | Nothing new: this is v32's coach with the bands converted (row 68) | **Spoken turns 18 -> 12 -> 18: fully restored.** The magnitude change holds on the full turn set, not just the reduced one: turns grading or pricing the move **11 (v31) -> 0 (v32) -> 0 (v33)**, prompt magnitude leaks 18 -> 0 -> 0. And v32's two apparent regressions were the engine confound, now confirmed as such: fidelity violations 1 -> 4 -> **1**, composed-fact rate 34% -> 20% -> **34%**, both back to v31 exactly. Judge 4.0/10 on the v1 ask, inside its established 3.5-4.5 noise band and not read as signal | kept |
| 70 | (v33, **a real regression, and it is the cost of row 63**) Lesson concentration over SPOKEN turns went **44% (v31) -> 83% (v33)**: the closing lesson is about "attack" on 9 of 18 turns. The judge found it independently and specifically — "one lesson, five times, with no escalation and no memory" — and **its per-ply claim checks out**: plies 20, 30, 38, 44 and 46 all say "attacking their undefended bishop on b4", with `a3` recommended on four of them | Nothing yet — diagnosis first | Every one of those sentences is **true**; this is not a fidelity problem. The driver is that the engine recommends `a3` five times (the bishop really does sit undefended on b4 all middlegame), our composer describes it identically each time, and the takeaway is keyed to that same clause. Hypothesis, unverified: the row-63 tier rewrite ("Describe what the stronger move does; that is the lesson") tightened the closing onto the achievement clause, which is why v31's closings varied where v33's do not. Note the headline `lesson_concentration_rate` **understates this** — it divides by all 44 turns including the 26 silent ones, reading 18% vs 34% where the spoken-turn figures are 44% vs 83% | open — next item |

| 71 | (v34, and **a retraction of row 70's numbers**) The lesson-memory ladder shipped: teach it, name the recurrence, then stop. But measuring it exposed **two defects in the metric I used to report row 70**, and the corrected figures tell a smaller story | Fixed both: (a) `lesson_concentration` ranked terms with `Counter.most_common`, whose ties fall in insertion order — and insertion came from iterating **sets**, whose order is hash-randomized per process, so the SAME transcript scored 72% and 83% on separate invocations. Now a total order (count desc, then term). (b) `_TEMPLATE_WORDS` did not contain `worth`/`remembering`, which is the frame **our own composer** puts round every takeaway — so those two ranked as two of the three "most common lessons" and the metric was reporting our boilerplate back as repetition. Caught by a test asserting six turns teaching six things must score below six teaching one; it returned 1.0 for both | **Stable figures: v31 56%, v33 72%, v34 50%.** So the regression was 56 -> 72 (16 points), not the 44 -> 83 I reported, and v34 improves on both. **Row 70's numbers are withdrawn**; its finding — that the coach taught one lesson five times — stands, because it was verified against the transcript by hand, not from this metric | kept |
| 72 | (v34, **the fix is partial and the metric flattered it**) Concentration measures the CLOSING SENTENCE only. What the judge actually named was "attacking their undefended bishop on b4" appearing five times — and that is the **achievement clause in the body**, which the ladder does not touch. Checked in v34: plies 20, 30, 38, 44 and 46 all still say it | Nothing yet | The ladder governs the takeaway and the takeaway alone, so a metric scoped to the last sentence records a 22-point win while the sentence the reviewer complained about is unchanged. **Measured the thing I changed rather than the thing that was wrong.** Also found: `compose_safe_move_feedback` ignores the ladder entirely, so when the gate fires the retired lesson ships anyway — visible at v34 ply 46, the fifth telling | open — two follow-ups |

| 73 | (row 72's two follow-ups) The lesson ladder governed the closing sentence only, and `compose_safe_move_feedback` ignored it entirely | Put the **achievement clause** — the body sentence the reviewer actually counted — on the same three-step ladder: state it, say it is the same idea, then stop explaining and just name the move. The third rung returns `''`, which reuses the existing redirect that stops the tier instructions pointing at a line that is no longer there. And the composed fallback now takes the lesson count, so the safety net cannot ship a retired lesson when the gate fires | Verified prompt-side by replaying the five real v34 plies through a live engine: b4 clause **full -> flagged -> dropped -> dropped -> dropped**, takeaway **teach -> name -> silent -> silent -> silent**. One bug found in the doing: keying the clause on the *rendered* line let the repeat through, because that line appends the engine's `best_move_idea` and the label varied ("pawn structure — improving pawn position" vs "piece activity — improving piece placement") where the sentence did not. Now keyed on the board-derived clause alone. Output side unmeasured — needs a v35 | kept, unmeasured |

| 74 | (v35, rubric v2) **We have been reading the wrong dial for ten runs.** Every score v26-v35 came from the v1 ask, which this ledger already recorded as unable to discriminate between coach versions (row 30). Re-judged v33 and v35 under v2 | Nothing yet — measurement only | **Both 2/10, both capped by the FIDELITY gate**; uncapped they are 5.2 and 5.1. The full uncapped series is 4.3 -> 5.2 -> 5.7 -> 5.05 -> 5.6 -> 5.7 -> … -> 5.2 -> 5.1: it rose once across v26-v28 and has been flat inside noise for seven runs, currently BELOW v31. The judge, unprompted, in both reviews: clearing fidelity is "the largest single move available" and "the only change that can be", worth roughly 2 -> 5. **Everything else we improve is invisible under the cap** | kept |
| 75 | (the pattern behind row 74, owner's observation) We have been gated at 2 in v26, v27, v28, v29, v30, v33 and v35. Each time a check was added and closed that class, and a NEW class of fabrication appeared: wrong owner (v27) -> false defence geometry (v28) -> mate called a check + invented intent (v29) -> impossible opponent reply (v30) -> **invented attack geometry (v35)**. Five checks, five closed classes, a sixth class each time | Built the sixth: attack-claim geometry. Two holes, both real. `_check_opponent_reply` skipped any bare pawn move (`clearly_a_move` required a piece letter or an "x"), so "the opponent plays a5" was read as an ordinary square reference; and nothing verified what a reply ATTACKS, only its legality and what it captures. Bare tokens are now promoted to moves by an explicit play verb, and the claimed attack is checked EXACTLY against the position after the reply | Catches v35 ply 60 — *"the opponent plays a5, attacking your rook on e1 and winning it"*, where a5 is empty, the pawn is on a7, and a pawn on a5 could only ever attack b4, which holds Black's own rook. Fires on the identical error in v33 and v34 too, and **nowhere else in ~172 coached turns**. Gates. Pinned by a test over every stored transcript | kept |
| 76 | (our finding, the strategic one) The checks are a net under a model that keeps inventing causal claims. Six nets later it still invents, and the uncapped score has not moved in seven runs — so the treadmill, not the individual check, is the thing to question | **next** — stop the model authoring causal claims at all: only voice a "because" we composed and verified, otherwise name the move and the principle with no reason attached. Removes the category instead of policing instances, and it is the judge's own top recommendation in both v35 reviews | — | open — the actual root cause |

## Measurement philosophy (what to trust)

**You cannot check LLM prose by matching words against it.** That is the whole
reason the end-to-end frontier review exists: its written critique is the real
check on whether the coaching teaches anything. The numbers are here to anchor
that review in facts and to catch regressions.

Every number we keep answers a question that can be checked, and they come in two
kinds.

**Checked against the position.** The fidelity counts (`off_menu`,
`unsound_move`, `illegal_move`, `placement`, `piece_type`) come from `verify.py`,
which pulls move tokens out of the text and parses them against the real board.
Those can tell us the coach was *wrong*. `prompt_uci_leaks` checks our own
rendered prompt. Latency, `empty_feedback` and the phase / move-quality mixes are
plain counts.

**Checked against our own prompt.** `composed_fact_rate` (the coach named a square
we gave it) and `unsourced_square_rate` (it named one we did not). Both are facts
about our own data rather than guesses about meaning. Neither says whether the
sentence around the square is true or worth reading.

**One metric was deleted rather than kept with a caveat.**
`principle_connection_rate` looked for a word from a hardcoded list within 120
characters of a square, meaning to catch a principle stated abstractly instead of
applied to the position. It could not: words like "material", "capture",
"exchange" and "center" appear in essentially any chess sentence, so **all 44
responses** in the v19 transcript contained one, 95% contained a square, and it
reported 91% against that 95% ceiling. It also passed on prose written
specifically to fail it — *"Nf3 is a good move. In general, development matters a
lot in the opening."* Nothing was wrong with the code; the idea was wrong, and a
number that always says yes is worse than no number, because someone will cite it.
Whether the coaching bridges a principle to a position is the frontier review's
question.

**Do not maximize any of the rest either.** Every one can be improved by padding
the output with square names, which would make the coaching worse while the
numbers looked better.

**The 0–10 score is noise-dominated at n=1** and must NOT be the optimization
target either. Proof: five runs of the *identical* game (seed 7) with
monotonically refining prompts scored **3.5 → 4.2 → 4.5 → 4.5 → 3.5** — a ~1-point
band, and the last run (lever 4) scored *below baseline* despite outputs that are
demonstrably better differentiated.

So a lever is accepted or rejected on: the board-validated counts, direct reading
of the outputs, and the review's prose critique. Never on a rate alone. A rate
that moves is a hint to go and read something.

All runs below: qwen3:14b coach, sonnet judge, seed 7, 44 coached turns
(10 opening / 16 middlegame / 18 endgame; 23 good / 9 inaccuracy / 8 mistake /
4 blunder).

## Progression

| # | change | judge score | off_menu | unsound | placement | kept? |
|---|--------|:-----------:|:--------:|:-------:|:---------:|:-----:|
| baseline | shipping config (guidance on) | 3.5 | 8 | 4 | 1 | — |
| lever 1 | remove always-on opening "CHESS PRINCIPLES" crib from `SYSTEM_PROMPT_V2` | 4.2 | 8 | 5 | 1 | **yes** |
| lever 2 | add grounding rule: don't invent causal chains ("allows/supports/weakens") | 4.5 | 9 | 4 | 1 | **reverted** |
| lever 3 | severity-tiered response (tone + length by eval-drop band; no filler sign-offs) | 4.5 | **4** | **2** | 2 | **yes** |
| lever 4 | enforce per-tier length (word limit + max_tokens) in builder/Coach/driver | 3.5 | 4 | 2 | 1 | **yes** |
| lever 5 | tiers demand the concrete consequence (state the refutation line) | — | 7 | 6 | 1 | **reverted** |
| lever 6 | concrete consequence done right: first reply only + opponent-aware checker | 4.5 | **3** | 2 | 1 | **yes** |
| lever 7 | position→principle ordering (prompt directive; refined to anchor to data) | — | 4 | 3 | 2 | **reverted** |
| lever 8 | opponent's-reply block states the captured piece (composed from board) | 4.5 | 3 | 2 | 1 | **yes** |
| lever 9 | good-move tiers voice the engine's best_move_idea, not a generic principle | 4.5 | 3 | 2 | 1 | **yes** |

**Lever 1 (kept).** The static crib was injected on every turn and drove
recycled generic advice ("develop your pieces / is my king safe?") even in the
endgame. Removing it lifted the holistic score (+0.7, directional) with **zero
change to deterministic fidelity** and no regression; low-risk (the pedagogy
guidance layer still supplies a principle). Kept.

**Lever 2 (reverted).** A bare "don't invent cause-and-effect" grounding rule
did **not** measurably reduce fabrication — off_menu 8→9, unsound 5→4 (flat),
and the judge still cited hallucinated justifications. +0.3 is within noise.
No demonstrable benefit, so it was reverted to keep the prompt lean (a negative
result is a valid finding: qwen3:14b doesn't reliably follow a negative
constraint on causal reasoning the way it followed the concrete "no `and
then...` continuations" rule).

**Lever 3 (kept).** Severity-tiered move feedback — the response's directness
and length scale with the eval-drop band (best/sound → short affirmation;
inaccuracy → brief redirect; serious → direct "lead with the cost", no
cushioning), keyed on OUR own bands (`SOUND_MAX_DROP_CP`/`DUBIOUS_MAX_DROP_CP`),
never the engine's label (BUG-016). Score flat (+0.3, within noise) but the
**trustworthy signal moved: off_menu + unsound roughly halved (13 → 6)** — the
tighter, tiered responses give the model fewer openings to ramble into off-menu
/ fabricated recommendations — and the judge now lists calibrated severity as a
*strength*. Kept (measurable deterministic benefit, no regression), unlike
lever 2. What it did NOT fix: the model under-delivers on the *length/depth*
part from prompt text alone — still ~3-5 sentences on best moves, still opens
with "Great job!", still platitudes on blunders. The judge's new #1: enforce
depth differentiation by quality + phase (blunders longest/most specific;
top-moves one sentence) and give opening moves a *named opening concept*. Two
future levers: (a) enforce length/depth (prompt text isn't enough — likely
per-tier generation limits); (b) opening-specific content.

**Lever 4 (kept — on direct evidence, NOT the score).** Per-tier word limit +
`max_tokens`, wired into the prompt builder, the runtime `Coach`, and the
report-card driver, via a shared `_move_feedback_tier` helper (bands are our
own, per BUG-016). Direct inspection confirms it did its job: best-move replies
dropped to ~23–35 words (from ~100+), blunder replies stayed longer and got
more concrete ("Kd1 … allows Black to capture your knight on g5"); no
truncation; deterministic fidelity held (off_menu 4 / unsound 2). The judge
score fell to 3.5 — but that is the noise band (see above), contradicted by the
direct evidence, so lever 4 is kept.

**Lever 5 (reverted — backfired).** Sharpening the tiers to "state the
Refutation Line explicitly" made the coach dump the raw multi-move PV as
move-salad — ply 20: "After Kd1, Black plays fxg5, fxg5, Ne5, Bb2, d6, Bxe5,
dxe5, Nd2" — *worse* than lever 4's clean "allows Black to capture your knight
on g5", and `illegal_move` spiked 0 → 5 (off_menu 4→7, unsound 2→6). Two
insights it surfaced:
1. **It re-opened BUG-013.** "Voice the line" fights the "don't narrate
   `and then...` continuations" rule; the model recites a long, partly-garbled
   PV.
2. **The illegal_move spike is largely a checker artifact.** The coach now
   names the *opponent's* reply ("Black plays fxg5"), but the fidelity checker
   validates every named move against the pre-move position where it's the
   *student* to move — so a correctly-attributed opponent reply is flagged
   illegal. The checker can't tell "opponent's punishing reply" from "a move I
   recommend the student play."

The concrete-consequence direction is still right (ply 34's "After Ke2, Black
plays ...Qa5, targeting your king" is exactly it), but it needs a **proper
design, not a prompt tweak**: (a) name only the opponent's *single immediate
reply* (the first move of the refutation line), tersely — never the whole PV;
(b) make the checker **opponent-move-aware** so a correctly-attributed reply
isn't counted illegal. Deferred as a small feature.

**Lever 6 (kept — the proper concrete-consequence feature).** Three parts that
fixed what lever 5 broke: (a) `_format_refutation_line` renders only the
opponent's FIRST reply (a single move), never the PV; (b) the SERIOUS tier
voices that one reply and forbids listing a sequence; (c) the fidelity checker
is opponent-move-aware (`_attributed_to_opponent`) so a correctly-attributed
"the opponent plays X" reply isn't counted as an illegal student move. Result —
the best deterministic run of the series and the lever-5 regression gone:
**illegal_move 5 → 0, off_menu 7 → 3** (lowest yet), unsound 6 → 2. Qualitatively
the move-salad is gone and blunders now name the single concrete consequence
("the opponent plays fxg5, winning material"; "exd4, winning a pawn"). Graceful
degradation when no refutation is available (ply 34 hedged rather than
fabricating). Kept.

**Lever 7 (reverted — costs accuracy).** A prompt directive to lead with the
concrete position point flipped the ordering nicely (blunders opened with "your
opponent plays fxg5, winning material") but pushed the model to assert more
board facts than it can ground: fidelity regressed (raw: illegal_move 0→1,
placement/piece_type 1→2). Refining it to "only from the data shown, don't
invent" fixed the worst (illegal_move back to 0, off_menu down) but the
accuracy-critical categories stayed doubled (placement 1→2, piece_type 1→2).
Per the rule "do not sacrifice accuracy," reverted.

**Lever 8 (kept — the Layer-1→Layer-2 lesson, proven).** After lever 7 showed a
prompt directive can't add concreteness without inventing, lever 8 does it the
composed way: `_refutation_capture_clause` computes what the opponent's reply
captures — reading the piece off the board *after* the student's move — and the
"Opponent's reply" block states it verbatim ("capturing your knight on g5").
Result: deterministic fidelity identical to the clean v6 baseline (off_menu 3,
unsound 2, placement 1, piece_type 1, illegal 0) — **zero accuracy cost** — while
blunders gained a concrete, verified consequence. Decisive evidence: at ply 30
the model's own guess in earlier runs was "winning a pawn"; the composer
computed the truth (a white **bishop** sat on d4, captured by ...exd4) and the
coach voiced "capturing your bishop on d4." **The composer corrected a model
hallucination at no cost — exactly the pattern below.**

**Lever 9 (kept).** The good-move tiers (best/sound/inaccuracy) now tell the
coach to voice the engine's `best_move_idea` — the "What the best move achieves"
field already in the prompt — instead of a generic principle. Composed, not
derived, so accuracy-safe by construction. Good moves became position-specific
("Nc3 focuses on rapid development, activating a knight toward the center";
"Bc4 develops a bishop to a strong, active square, prepare for castling")
rather than "develop your pieces". Fidelity stayed at the clean baseline except
placement 1→2 — a single count within the series' 1↔2 noise band and not
attributable at n=1 (voicing an engine field shouldn't cause a placement
error). Kept.

## The pattern across levers (the strategic lesson)

Sorting the levers by outcome reveals a sharp, consistent rule:

- **KEPT — levers 1, 3, 4, 6:** each either removed noise (drop the crib) or
  **composed/constrained a verified fact deterministically and had the LLM
  voice it** (severity bands from our eval-drop, per-tier length, the opponent's
  first reply rendered from the refutation + an opponent-aware checker).
- **REVERTED — levers 2, 5, 7:** each **asked the LLM to *derive* more** via a
  prompt directive — "don't fabricate causal chains" (no effect), "state the
  refutation line" (move-salad), "lead with the concrete point" (invented
  facts). All regressed or did nothing.

**Conclusion: we have hit the ceiling of prompt-directing the local model toward
more concreteness. Every further teaching gain has to move the concreteness OUT
of the LLM's derivation and INTO deterministic Layer-1 composition — compose the
verified point, hand it over, and let the LLM only *voice* it.** That is the
"Layer 1 facts → Layer 2 voice" principle, and it is what every kept lever
already does.

## Stable qualitative findings (across all runs — the real signal)

1. **Generic recycled principle.** A small rotating set of platitudes
   ("develop knights and bishops", "king safety", "improve your pawn
   structure") repeats regardless of position — one generic lecture
   masquerading as 44 lessons. Lever 1 helped but did not eliminate it.
2. **Flat severity + uniform verbosity.** Blunders and best moves get the same
   warm opener ("Great job / It sounds like you were aiming to…") and the same
   4–6 sentences. A −878cp blunder feels identical to a 0cp best move. The
   judge promoted this to its **#1 highest-leverage change** by run 3: a
   *severity-tiered response protocol* (blunder → direct "this was a serious
   mistake, here's why it loses" + fix; good move → one short affirmation + one
   idea; inaccuracy → brief redirect).
3. **Fabricated / off-menu causal claims.** ~13 deterministic off_menu/unsound
   per run, plus invented mechanisms ("Bc4 allows …capture on d4", "a3 supports
   d4"). Stable; not fixed by lever 2's prompt rule. Likely needs a stronger
   mechanism than a negative instruction (e.g. constraining named moves to the
   menu / a repair pass) — revisit after severity tiering.

## Next: extend the composed-lead approach

Levers 8 and 9 delivered the concrete lead on both sides (verified captured
piece on blunders; the engine's idea on good moves). One accuracy-safe
extension remains, plus the bigger deferred item:

- **Non-capture refutations:** when the opponent's reply is a strong non-capture
  (a check, a fork, a quiet killer), the capture clause is empty. Consider
  composing the motif (from the engine's tactic/threat data for that reply) so
  those blunders also get a concrete "why", not just the move.

Deferred companion (bigger, and likely necessary): opening-specific *content*
(named openings / plans) fed as data — the opening phase stays the most generic
and needs real content, not ordering. This is a knowledge/engine-feature build,
not a prompt change.

## Architecture review (2026-08-10) — the design critique, and the action list

After ten levers we hit the ceiling of interpreting an *output-only* judge: the
report-card reviewer never saw the prompt, the composers, the pedagogy layer, or
the lever history, so it kept re-proposing things we had already reverted. So we
built `scripts/eval_architecture_review.py` (+ `build_architecture_review_prompt`),
which hands a frontier model the **internals** — the exact rendered prompt, an
architecture summary, the hard constraints, and this lever log — and asks for a
DESIGN critique. Its verdict was materially more useful than any output review.

**Soundness:** the architecture is right and "Layer 1 composes verified facts /
Layer 2 voices them" is the correct load-bearing design (every kept lever
confirms it). The ceiling is not the architecture — it is **how much we still
leave the model to derive.**

**The architectural flaw it named (new, and a root cause we had not identified):**
the **pedagogy YAML layer is doing double duty it cannot do**. It is both the
content source ("what principle applies here") and the teaching scaffold ("how to
connect it to this position"), but a YAML entry can only supply an *abstract*
principle. The prompt therefore hands the model generic prose, and — quoting —
*"you cannot prompt your way out of this because the abstract text IS what the
model anchors to when the position-specific signal is weak."* That explains the
recycled-template problem we fought from lever 1 onward, and why levers 2/5/7/10
kept producing a *new* template rather than fixing it.

**Second root cause:** `best_move_idea` is a **category label**, not a fact
("piece activity — improving piece placement"), so voicing it can only produce
category sentences. Lever 9 was right to wire it in and wrong to stop there.

**A concrete bug it caught:** non-capture refutations get **no** composed
description (levers 6/8 handled captures only). On ply 8 the PV first move was
`f6g4` (a knight move); the coach said "gaining a strong central pawn" and our
`piece_type` counter fired.

### Baseline for the new metrics (item 1 — DONE, measured on the v13 transcript)

| metric | value | reading |
|---|---|---|
| specificity rate | **25%** | only 1 turn in 4 names a square/piece beyond the move itself — the "hollow second end of the bridge", quantified |
| principle-connection rate | **39%** | the principle is instantiated on the board in under half of turns; the rest is abstract recycling |
| fidelity by phase | endgame 5, opening 3, middlegame 1 | **overturns the review's guess** that the endgame would be cleanest and the opening worst — composer work should target the ENDGAME first |

That last row is why these metrics matter: a plausible narrative from the
reviewer was wrong, and a zero-noise count caught it. Both rates are the
before-numbers for items 2-4.

### Action items (in execution order)

1. **[metrics] Add deterministic teaching metrics to the report card** — DONE —
   *specificity rate* (does the response name a position-specific square/piece
   beyond the moved piece?) and *principle-to-position connection rate* (does a
   fired principle appear near a square reference?), plus a **per-phase fidelity
   breakdown**. Regex-checkable, zero-noise, and they measure the bridge
   directly — better than the noisy 0-10. Do this FIRST so the remaining levers
   are judged on stable numbers.
2. **[composer] Non-capture refutation description** — DONE (kept, but
   UNMEASURED end-to-end). `_refutation_capture_clause` now describes any
   opponent reply from the board: capture ("capturing your knight on g5",
   en-passant aware), fork ("hitting your queen on g5 and your rook on f4",
   most valuable first), single undefended ("attacking your undefended rook on
   f4"), check-only ("giving check"), else empty (never an invented "why").
   Pawns/king are excluded as named targets — an early version turned a real
   check into a pawn inventory, caught by testing against real boards.
   **Honest caveat:** the seed-7 game contains only **3** refutation-bearing
   turns and **all 3 are captures**, so the new branch never fired and the run
   metrics were byte-identical to v13. Unit tests verify all four branches on
   real positions; the change is strictly additive (empty when nothing is
   verifiable), so it is kept — but no measured game-level win is claimed.
   **Harness lesson:** one game cannot validate blunder/refutation-focused
   levers (3 of 44 turns). Before items 3-4, either run 2-3 seeds per
   measurement or add curated blunder/refutation positions (as we did for
   endgame coverage), or those levers risk the same "no-op / can't tell"
   outcome.

   **2b. [bug] Raw UCI was still reaching the coach — found while validating 2,
   now FIXED.** Chasing "why didn't item 2 move anything" uncovered a much
   bigger defect: a `ComparisonReport`'s `top_lines` describe the position AFTER
   the student's move (they open with the opponent's reply), but
   `_format_comparison_top_lines` converted SAN from `report.fen` (before it).
   The first move was illegal there, and `_uci_line_to_san`'s **silent**
   fault-tolerant fallback emitted the WHOLE line as raw coordinates —
   `f6g4 f2f4 e5c4 ...` — which the coach parroted and then invented a meaning
   for ("gaining a strong central pawn"; the correct SAN is `Nfg4`, a knight
   move). So the documented SAN migration was real but silently degraded in
   exactly one section. Root cause of the *remaining* leaks after the base-FEN
   fix turned out to be an **engine bug** (BUG-019: inconsistent PV, two Black
   moves in a row), so the converter genuinely could not replay the tail.
   Fix, in three parts: (a) correct base position; (b) `_uci_line_to_san` now
   **truncates** at the first unreplayable move with `...` and NEVER emits
   coordinates — an unconvertible first move omits the section entirely;
   (c) two guards, because a log warning is not a guard: a **CI sentinel test**
   (no bare UCI token in any rendered comparison prompt, all tiers) and a
   **`prompt_uci_leaks` metric** in every report-card run's stats.
   Measured: **prompt_uci_leaks 27/44 -> 19/44 -> 0/44**; total fidelity
   violations 9 -> 8; specificity/principle-connection unchanged (25% / 34%).
   **2c. [fix] PV side attribution — DONE, and it worked.** SAN fixed
   readability but not *whose move is whose*: at ply 8 the coach said "the
   opponent plays f4" when `f4` was the student's own (White) move — the second
   ply. A bare SAN sequence hides the alternation, so the model grabbed the
   wrong ply. `_uci_line_to_numbered_san` now renders move numbers from the
   board (`5...Nfg4 6.f4 Nxc4 7.bxc4`), and the section header names which
   colour is the opponent. Scope was verified before building, not assumed:
   this was the ONLY unlabelled multi-move surface (the refutation block,
   tactics, move menu and move fields all already carry attribution, and the
   position prompt has no raw PV since the move-menu work). A separate function
   was added rather than changing `_uci_line_to_san`, to leave the
   just-fixed refutation path untouched. Three off-by-one hazards were checked
   against real boards first: Black-start (`5...`), truncation of the engine's
   corrupt tail (numbering survives), and White-start (no spurious `...`).

   **Measured (v16 -> v17):** the ply-8 sentence is now correct ("the opponent
   plays **Nfg4**"), and the deterministic metrics improved — total violations
   **8 -> 6**, `piece_type` **1 -> 0** (consistent with the mechanism: the coach
   had been misreading which move, hence which piece, belonged to whom),
   specificity 25% -> 27%, principle-connection 34% (flat), leaks still 0. Best
   deterministic result of the series (baseline: 9 violations, 27 leaks).
3. **[composer] Compose the best-move "why" from the board** — DONE, and the
   **biggest single win of the series.** Evidence first: across the 44 turns
   `best_move_idea` had only **10 distinct values** (`king safety —
   repositioning the king` x13, `rook activity — improving rook placement` x8),
   so voicing it could only ever produce category sentences.
   `_best_move_achievement` now prepends a verified board-derived clause and
   keeps the label as the theme; the opponent's-reply and best-move clauses were
   unified into one `_move_effect_clause` (capture / fork / check / attack /
   escaping an attack / defending) so they cannot drift. Coverage was measured
   BEFORE spending a run: **31/44 (70%)** of best moves get a concrete clause;
   the rest return the label unchanged rather than inventing.

   **Measured (v17 -> v18): specificity 27% -> 66%, principle-connection
   34% -> 64%** — both roughly doubled — with **no fidelity cost** (total
   violations flat at 6, placement 1 -> 0, leaks still 0). The prose confirms the
   mechanism: ply 8 went from "Nfg4, gaining a strong central presence" (vague)
   to "Nfg4, **attacking your bishop on c4**" + "Be2, **moving your bishop to a
   safe and active square**"; ply 66 from "repositioning your king for better
   safety" to "repositioning your king to **target the opponent's rook on f4 and
   bishop on g4**". The coach says *why* in board terms because it was handed
   the fact.

   Two guards caught mistakes during the refactor and are worth noting: an
   existing test caught a word-order regression ("undefended your rook"), and
   **mypy caught dead code** the refactor orphaned (an unreachable branch using
   an undefined name). One "failure" was the test being wrong, not the code —
   the b4 bishop really is defended by the f8 bishop.
4. **[pedagogy] Instantiate the guidance block** — DONE (kept; mechanism right,
   measurable gain small). Implemented leaner than the review proposed: instead
   of adding an `instantiation_template` to all 20 YAML entries plus a
   slot-filling mechanism, note that an entry fires *because* a board feature
   was found — so `pedagogy/instantiate.feature_facts(report)` composes the fact
   for that feature and `_render_entry` appends it as `HERE: ...`. No schema
   change, no content authoring, and the fact comes from the report the selector
   already matched against.

   Two self-inflicted bugs caught before running, both the failure mode we keep
   fighting: (a) the first version emitted "you are ahead in material" and "a
   capture is available" **unconditionally** — false in the starting position —
   so facts are now filtered to features actually present, with a regression
   test; a fabricated "fact" is worse than the abstraction it replaces.
   (b) The "pieces still at home" fact was keyed to `phase:opening`, which TWO
   entries share, so it landed on the wrong theme ("center control … HERE: your
   bishops have not moved"); that mapping was dropped — only semantically
   matched facts are emitted. mypy also caught a typing error in the
   wing-majority loop.

   **Measured (v18 -> v19): fidelity is the cleanest of the series — total
   violations 6 -> 5, and BOTH board-fact categories are now zero (placement 0,
   piece_type 0)**; only constraint-adherence violations remain (off_menu 3,
   unsound_move 2). But **principle-connection moved only 64% -> 66% and
   specificity was flat at 66%** — within noise for one run, so no teaching win
   is claimed. Inspection explains why: 39/44 prompts carried an instantiated
   fact, but the model consistently preferred the **move-anchored** fact from
   item 3 over the position-level guidance fact (offered "a fork involving
   d5, c4", it voiced "attacking Black's knight on e5"). For move feedback that
   is arguably correct — the coaching is *about a move* — and item 3's clauses
   are simply more specific. Kept because the mechanism removes abstract-only
   guidance (the named flaw), fidelity improved, and it cannot fabricate.
   **Hypothesis worth testing later:** item 4 should pay off on the
   *position-coaching* path (`chess-coach explain`), where there is no move to
   anchor to — untested here.
5. **[option, not a recommendation] Blunder-only second pass** — a short
   self-critique call on the ~9% of turns that are blunders. Violates the
   one-LLM-call rule and doubles latency there; only pursue if 2-4 leave blunder
   quality unacceptable, with a hard fallback to pass 1.

### Stop doing (per the review)

- **Stop tuning the grounding rules** — lever 2 proved negative constraints on
  this model's causal reasoning have no measurable effect; the section is
  already long.
- **Stop leaning on `best_move_idea` as-is** — replace the label with a composed
  fact rather than voicing it harder.
- **Stop iterating on prompt ordering** — lever 7 showed available facts outweigh
  what the model is told to lead with. Revisit ordering only after grounding
  improves.

## Second architecture review (v3, after items 2b/2c/3/4)

The review script was re-run with the `ARCHITECTURE` summary updated to describe
items 2b/2c/3/4, so the frontier reviewer critiqued the *current* design rather
than the one it had already commented on. Full text: `output/architecture_review_v3/review.md`
(gitignored). Two process notes worth keeping:

- The rendered prompt plus architecture summary blew past Windows' ~32k command
  line limit. No new plumbing was needed: `CliProvider` already pipes the prompt
  on **stdin** when `{prompt}` is omitted from `--judge-command`. The usage
  docstring now says so.
- The first re-run reported "specificity 0% — alarming", which was **a bug in the
  script, not a regression**: it rebuilt `ReviewStats` field by field from the
  saved JSON and silently dropped every metric added after it was written. Fixed
  with `ReviewStats.from_dict` plus a regression test that fails if a field is
  dropped. A measurement harness that silently zeroes a metric is worse than no
  metric, because it invites a "fix" for a problem that does not exist.

**What the review confirmed.** Compose-facts-and-let-the-model-voice-them is the
right architecture; every kept lever obeys it and every reverted lever broke it.
It independently reached the same conclusion as our own item-4 inspection: the
guidance block is now "a third competing fact stream" that loses to the
move-effect clause, at roughly "three-to-one abstract:concrete tokens". It named
**coverage** — the 30% of best moves that still fall back to a bare category
label — as the fundamental remaining limit, not anything architectural.

**Recommended changes, in its priority order:**

- **A — compose the missing 30%.** Extend `_move_effect_clause` with branches for
  quiet improving moves: landing on an open file, centralizing, activating a
  previously blocked piece (legal-move count before vs after). Additive, no LLM
  involvement, and coverage is measurable before spending a run.
- **B — merge guidance INTO the move-effect clause instead of alongside it.**
  Pick the guidance entry whose feature matches the move-effect category and emit
  one teaching point; drop the block when nothing matches. Removes the
  abstract:concrete imbalance without removing the pedagogy layer.
- **C — mark the fallback honestly.** Tag the label-only case
  `[category only — no specific fact]` and instruct the coach to hedge. Today the
  prompt demands specificity while handing over an abstraction, and the model
  resolves that conflict by fabricating.
- **D — compose the takeaway hook** from (move-effect category x guidance theme)
  templates. Deferred by the review itself until A and B are measured; it is
  authoring work, ~20-30 templates.

**Measurement gaps it flagged:**

- `specificity_rate` cannot tell "specific because composed" from "specific
  because the model guessed right". A `composed_specificity_rate` counting only
  squares that appear in a composed prompt field would make the delta between
  the two an explicit hallucination buffer.
- The seed-7 game is too uniform for rare paths (3 of 44 turns carry a
  refutation). Curation should be systematic: one position per
  (move-quality x phase) cell plus a fixture per composer branch. Most of that
  can run as a prompt-rendering regression suite with **no LLM at all**.

**And one item it promoted that we had parked:** the opening is the *worst* phase
(3 fidelity violations vs middlegame's 1) and named openings are composable from
ECO data — a Layer 1 fact, not a prompt directive. That reframes "opening
content" from polish to the highest-violation target.

## Item 4 on the position-coaching path — and the attachment bug it exposed

Item 4's hypothesis was that instantiating guidance with a board fact should pay
off more on the **position-coaching** path than on move feedback, because there
is no move to anchor to. Wiring it there took one line
(`build_rich_coaching_prompt` already holds the `PositionReport`). Measuring it
took three attempts, and the second failure was the actual finding.

**Dead end 1 — a saturated metric.** Scoring the position path with
`is_specific` / `connects_principle` gave **6/6 facts-off vs 5/6 facts-on**. Both
metrics were built for move feedback, where the student's and engine's move
squares are *discounted*; the position path has no such move, so any square
mention passes, and a position explanation always puts a theme word near a
square. The run was discarded rather than reported — a saturated metric cannot
answer the question, and "5/6 vs 6/6" would have read as a regression.

**Dead end 2 — the metric could not find the facts.** Rescoring on "does the
composed fact reach the output" (the review's Gap-1 `composed_specificity_rate`)
**skipped 4 of 5 positions**, because no *selected* entry carried a fact at all.

**The coverage measurement.** Offline, engine only, no LLM — the same discipline
that saved a run on item 3. Over 10 positions: **10 of 30 selected entries (33%)
could be instantiated**, 6 of 10 positions carried a single fact, and every
opening position carried none. So item 4's small gain on move feedback was never
really about the model's preferences; two thirds of the mechanism was not
reaching the prompt.

**Cause, verified rather than guessed.** Entries tie on relevance (each matches
exactly one present feature) and the tie-break — type, then `id` — is blind to
whether a fact exists. In a position with a live threat, the abstract
`center control` beat `answer the threat first`, which would have rendered
"HERE: there is a live threat against f7".

The first fix folded the fact bias into the existing `preferred_features` hook
and reached only 18/30. Instrumenting the misses showed **two soft biases
colliding**: the engine's PV theme `"piece development"` maps to the broad
`phase:opening` feature, so the move-theme bias handed the same +1 to all three
abstract opening entries and cancelled the fact bias out; the `id` tie-break then
picked the abstraction. Fixed by giving instantiability its own `_sort_key` term,
above the theme bonus and below relevance.

| | attachment (selected entries) | positions with >=1 fact |
|---|---|---|
| before | 10/30 (33%) | 6/10 |
| fact bias inside `preferred_features` | 18/30 (60%) | 8/10 |
| fact bias as its own rank term | **23/30 (77%)** | **10/10** |

Still a tie-break: it never admits or drops an entry, and a genuinely more
relevant entry still wins — both have regression tests. The remaining 7 of 30
are positions with fewer than three eligible fact-bearing entries, which is a
content-coverage limit, not a ranking one.

**The transferable lesson** is about the harness, not the coach: two of the three
attempts failed because a metric borrowed from another path could not
discriminate on this one, and a third of the pipeline was silently inert. Before
spending LLM runs, check that the mechanism under test actually fires — the same
mistake as the `ReviewStats` bug that told a reviewer specificity was 0%.

## Correction: the square regex was blind to SAN, so the headline metrics were wrong

Reading the position-path responses turned up a measurement bug, not a coaching
one. `_SQUARE_RE` was `\b[a-h][1-8]\b`, which finds **no square at all** in
`Ra8#`, `Rxc8#`, `Nf3` or `cxd5` — the leading piece or file letter kills the
word boundary. Measured against the move generator, it missed the destination
square of **76.1% of all legal moves**. Two consequences, in opposite directions:

- `connects_principle` missed every case where the coach named a square in SAN,
  so principle-connection was **under**-reported.
- `is_specific` builds its discount set from the move SANs, so that set was
  **empty for every piece move** and nothing was discounted. Coaching that only
  echoed the played/best move's own square was credited as specific, so
  specificity was **over**-reported.

The transcripts are saved, so the corrected numbers cost nothing to recompute
(no LLM, no engine):

| run | specificity (was -> is) | principle-connection (was -> is) |
|---|---|---|
| v17 (before item 3) | 27% -> **34%** | 34% -> **82%** |
| v18 (item 3) | 66% -> **52%** | 64% -> **84%** |
| v19 (item 4) | 66% -> **52%** | 66% -> **91%** |

**Two earlier conclusions have to change.**

1. **Item 3's specificity win was overstated.** The real move is 34% -> 52%, not
   27% -> 66%. Still the largest specificity gain in the series, and the prose
   evidence for the mechanism stands — but a good part of the old jump was the
   coach being credited for repeating the move it was handed.
2. **Item 4 did help the move-feedback path after all.** Principle-connection
   went 84% -> 91%, not the 64% -> 66% we called "within noise" and only kept on
   mechanism grounds. Instantiating the guidance theme with a board fact was
   working; the metric could not see it.

**Then a second audit undercut conclusion 2, and it is the more important
result.** The principle-connection metric turned out to say yes to everything, and
has since been deleted — see the measurement philosophy section. So the 84% -> 91%
move is not evidence that item 4 helped; the question was never being measured.
Item 4 is kept on its mechanism (it removes abstract-only guidance and cannot
fabricate) and on fidelity, not on that number. What can be said is narrower and
honest:

- **Item 3 is a specificity lever and it worked.** On the split, honest metric,
  the rate of turns voicing a fact we composed went **27% -> 52%** (v16 -> v19),
  while the rate of turns naming a square we never supplied stayed at **2-5%** —
  so the gain came from the coach voicing supplied facts, not from inventing.
- **Item 4's effect on teaching quality is unmeasured.** Not disproven, unmeasured.
  It is the frontier review's prose critique that would show it, if anything does.

That also means the architecture review's premise cannot be repaired simply by
substituting a corrected number. It reasoned from principle-connection at 64% and
named YAML coverage as the fundamental limit; the truth is that the metric it
reasoned from never measured anything. Its **Change A (compose the missing
30% of best-move clauses)** survives on independent grounds, because
composed-clause coverage is a deterministic count and specificity is genuinely at
52%. The guidance-merge work (Change B) rested on the 64% figure, so it should be
reconsidered from scratch rather than reprioritized.

**The regex is now validated against the move generator, not by eyeball**, since
that is exactly where the first two attempts went wrong. A test generates every
legal move in a position and asserts the destination square is found; a wider
throwaway sweep over 128,411 legal-move SANs from 60 random games measured the
candidates:

| pattern | legal SANs missed |
|---|---|
| `\b[a-h][1-8]\b` (original) | **76.1%** — every piece move |
| `(?<![a-h])(?<![0-9])[a-h][1-8](?![0-9])` (first fix) | **1.1%** — disambiguated moves: `Nbd7`, `Rae1+`, `Rgg1`, `R1e2` |
| `(?<![a-h][1-8])[a-h][1-8]` (shipped) | **0.0%** |

The first fix looked right on hand-picked examples and was still wrong; the forms
it dropped (`Nfg4`, `Rae1+`, `Rgg1`) occur in the coach's real output. The single
rule "not the second half of a coordinate pair" is both simpler and complete, and
adds no false positives over 41k characters of real coach responses. Castling
contributes no square, deliberately and in both directions.

A second test pins that echoing the move back does not count as specific — which
could not have passed before, because `Ra8#` contributed nothing to either side
of the comparison.

## The honest metric split (2026-08-11)

`specificity_rate` conflated two different things, so it could rise for a good
reason or a bad one. It was replaced by the pair below, both computed against the
prompt the coach actually received:

| run | voiced a fact we composed | named a square we never supplied |
|---|---|---|
| v16 | 27% | 2% |
| v17 | 30% | 5% |
| v18 (item 3) | **52%** | 5% |
| v19 (item 4) | **52%** | 2% |

The first column is the architecture working as designed — compose the fact, let
the model voice it — and it is the rate worth watching. The second is where
fabrication would surface; at 2-5% it is low and flat, which is the reassuring
part of the item-3 result: the specificity gain came from voicing supplied facts,
not from the model getting inventive.

Neither says anything about whether the sentence around the square is true (that
is `verify.py`'s job) or worth reading (that is the frontier review's job). They
are screens.

**And the rule that comes out of this whole episode:** do not maximize any of
these. Every one can be moved by padding the output with square names, which
would make the coaching worse while every number improved. A rate that moves is a
prompt to go and read the output, not a result.

The other rule, from the deleted metric: if a measurement cannot fail, delete it.
Keeping it with a warning attached does not work — the number still gets printed,
still gets quoted in a review prompt, and still gets cited months later by someone
who did not read the warning. That is exactly how the 64% figure ended up
anchoring an architecture review.

## Measuring repetition (2026-08-11) — and two designs that failed first

The reviewer complained twice that the coaching says the same thing every move,
and counted it by hand: "the closing question is almost always one of three
templates", with "can I attack an undefended piece?" on roughly half the game. We
had no measurement for it at all, so every discussion of it was anecdote against
anecdote.

Because the reviewer had produced a hand count, there was something to check a
candidate metric *against* — which is how two plausible designs got caught.

**Attempt 1, repeated wording** (`recycled_phrase_rate`, kept). For each turn,
the share of its five-word windows that already appeared in an earlier turn. Reads
21-27% across five runs and its worst-offending turns overlapped the reviewer's
cited plies only **3 of 12**. Kept, because repeated wording is a real and
separate thing and the number is honest about what it is — but it does not measure
the complaint, because the model rewords freely while teaching the same lesson.

**Attempt 2, distinct closing sentences** (deleted). Scored **95-100%** — saturated
and useless. "Next time you see a fork..." and "next time you see your knight on
the back rank..." are different strings and the same template. Deleted rather than
kept with a warning, per the rule the previous metric taught us.

**Attempt 3, the dominant lesson term** (rejected). Whichever single content word
appears in the most closing sentences. Picks "king", which overlaps the reviewer's
cited plies **0 of 12** — because the complaint was not about one lesson, it was
about *three* covering everything.

**Attempt 4, lesson concentration** (shipped). The share of turns whose closing
sentence contains one of the three most common content words across the game.
Directly encodes the reviewer's claim, and reproduces it:

| run | lesson concentration | recycled phrasing |
|---|---|---|
| v17 | 82% | 25% |
| v18 | 80% | 27% |
| v19 | 68% | 23% |
| v20 | **57%** | 21% |
| v21 | 68% | 22% |

It has the properties the deleted metrics lacked. It is not saturated, it moves
across runs, it can fail, and it agrees with an independent count. It also shows
the lever series did reduce repetition (82% -> 57%) and that v21 gave some back.

**On the word list.** This metric strips template scaffolding and generic English
before counting, which is a hand-authored word list — the thing we just deleted a
metric for. The distinction is worth stating plainly: the old list used keywords to
decide whether prose was *good*, which a keyword cannot know. This list is used to
count *how often the same lesson recurs*. Adding a word to it cannot make the
coaching look better, only make the measurement blunter — and unlike the deleted
metric, the output was validated against a count nobody derived from it.

## Re-judging the same transcript with corrected metrics (2026-08-11)

A clean experiment, because the coach's output was byte-identical: only the stats
block the reviewer is handed changed (directions stated, repetition measured).
Anything that moved is attributable to that block. Artifacts in
`output/coach_review_v21_rejudge/`.

**The previous review's weakness #1 became strength #2.**

Before: *"Catastrophic square-naming failure (66% re-use, 0% novel). A chess
teacher who can't say 'your bishop is hanging on c4' is not teaching chess — it's
paraphrasing prompts."* It was the headline finding and the basis of the top
recommendation.

After: *"Fidelity to engine-supplied facts is solid. The 66% board-fact voicing and
0% invented squares are exactly right. The coach isn't hallucinating piece
locations or phantom threats. This is the floor the product needs, and it holds."*

Same coaching, same numbers, opposite conclusion. The whole complaint was a metric
handed over without its sign — and had we acted on it, the change would have been
"let the model name squares we did not give it", the exact opposite of every lever
that has worked.

**The new #1 weakness is the one we just started measuring**, and the reviewer does
not merely repeat our figure — it verifies it from the transcript with its own
counts: "undefended piece" closing on ten turns, king safety on twelve, open file
on eight. First time a metric we built and a reviewer that had no hand in building
it have independently agreed. Score unchanged at 4.5/10, consistent with treating
it as too coarse to move on.

**Its recommended fix, and why we will not implement it literally:** "track which
principle was used in the last N turns and prohibit repetition in the prompt". The
prohibition half is a negative constraint, which is the one lever category that has
never worked on this model (row 2 of the ledger). The tracking half is sound. So
the composed version: derive the closing hook from the move-effect category we
already compute, so variety comes from the data rather than from an instruction.

**Two cautions about the reviewer itself.** It called the coach "Qwen3-8B" when we
run qwen3:14b — its incidental claims need checking. And it is capable of building a
headline recommendation on a misread number, so the stats block we hand it is part
of the experiment, not neutral scaffolding.

## The judge itself was the unreliable part (2026-08-12)

Two changes were measured against the judge's advice — composing the closing lesson
(v22) and phase-gating it (v23) — and while doing so its per-ply factual claims
were checked against the board for the first time. They did not hold up.

**claude-sonnet-4.6, five specific claims, five wrong.** It asserted twice that
ply 12's `dxe3` "recaptures a pawn, not a knight" and called it a fabrication; the
position has a black knight on e3 and the coach was correct. It attributed the
run's `piece_type` violation to that ply; the violation is at ply 60. It said ply
68's "you captured the undefended rook on f4" was wrong because `Kxf4` is a king
move; capturing a rook with the king is exactly what happened. It said ply 18's
"the opponent threatened f4" was invented; a knight on g6 attacks f4. Earlier it
built its entire headline recommendation on misreading a 0% metric as a defect.

**claude-opus-5 on the same transcript: two claims, both correct, both new.**

- Ply 28: the coach wrote *"your opponent plays e3, winning material because your
  pawn on e3 is undefended."* Verified — e3 holds OUR pawn. The coach has the
  opponent moving onto a square our own pawn occupies and calls it our undefended
  pawn in the same sentence. Incoherent, and the fidelity checker recorded nothing.
- Ply 1002 (white Kf2, pawn d5, black Kf7): the student played Ke3 and the coach
  said the alternative Kf3 "takes it one step closer to the center". Both squares
  are equidistant from the centre by the measure our own composer uses, and e3 is
  the more central file — so the coach downgraded a more central move by claiming
  the alternative was more central. **That one implicates our code**: the
  `king_activity` clause compares from-square to to-square, which is locally true
  and comparatively wrong when set against the student's move.

It also identified something sonnet listed as a strength: our own harness
bookkeeping leaking into the coaching as pseudo-explanation — "the evaluation
spread shows it was a key decision", "the best move was also your move" — on five
turns, occupying the slot where a chess reason belongs.

So `claude-opus-5` is now the default judge in both review scripts, at 2.20x
credits and ~3 minutes against sonnet's 1.30x and ~1 minute. That is cheap next to
a wrong finding: sonnet's phantom ply-12 error cost two investigations, and its
misread metric would have sent us to implement the opposite of what works.

**Also fixed while there:** `--judge-model` and `--judge-command` both named a
model and could silently disagree, with the command deciding — so a run could
record opus-5 while actually being judged by sonnet. The command is now derived
from the model unless explicitly given.

**And the standing rule this produces:** the judge's *structural* observations have
been consistently valuable — phase blindness, template closings, repetition counts,
the bridge critique. Its claims about specific plies are leads to verify, not
findings. Every one that has been checked against the board was wrong under
sonnet; opus-5 is better but the habit stays.

## Two per-ply defects, then the endgame inversion (2026-08-13)

The four fixes opus-5's v24 review produced, in the order they were made.

**Ply 28 — a bare square read as a destination.** The prompt said *"the opponent
threatens e3"*. The model read that as the opponent *moving to* e3, and wrote a
sentence where the opponent plays onto a square our own pawn occupies. Fixed by
naming what is actually there: `_describe_target` resolves the square against the
board and produces `"your pawn on e3"`, falling back to `"the f3 square"` when the
square is genuinely empty. v24 confirms ply 28 now reads correctly.

**Ply 1002 — our clause was comparatively wrong.** `_move_effect` now takes the
student's move (`rival_uci`) and drops the king-walk clause unless the
alternative is actually more central than what the student played. The clause is
gone from the prompt. The model then said "closer to the center" anyway, from its
own vocabulary, with nothing supplied — the same failure mode as the phase-gated
lesson table (row 20): **a fact we hand over gets voiced faithfully; a lesson we
hand over gets paraphrased away, and a lesson we withhold gets invented.**

**The endgame inversion — the structural one.** The judge's sharpest phase note
was that the endgame, with the most turns, had the worst pedagogy *and it was
backwards*: plies 52, 60, 1000 and 1002 all hunted for a "safer square" for the
king, and ply 76 called a centralized king "exposed" and recommended retreating
it. In a rook endgame the king is a fighting piece.

The cause was in our own knowledge base, not the model: `principle.exposed_king`
had no phase condition, so it stayed eligible to the last move of the game.
`GuidanceEntry` gained an optional `excludes_features`, checked in three places
that select entries — the feature path, the ECO path, and the empty-selection
fallback — with the guard validating exclusions against the same closed
vocabulary as inclusions. Verified per-ply rather than in aggregate: the entry was
present in the v24 prompt for all five flagged plies and is absent from all five
now, replaced by `passed_pawn_endgame`, `endgame_king_activity` and `open_file`.

Two implementation notes worth keeping. Adding `excludes_features` as a required
field broke 26 tests; last with a `frozenset()` default it broke none. And an
exclusion has to be applied on *every* path that can select an entry — the ECO
path and the fallback would otherwise reintroduce exactly what the feature path
just excluded.

**Ply 36 — the checker had a hole shaped like an adjective.** The coach wrote
*"wins material by capturing the undefended bishop on b4"* when `bxc4` captured a
knight, and `piece_type` recorded nothing. `_CAPTURE_CLAIM_RE` required the piece
noun to follow the article directly, so any adjective hid the claim. It now allows
up to two intervening words. The bound matters in both directions: "undefended" is
a word **our own composer uses constantly** ("attacking their undefended rook on
f4") and the coach echoes it, so the gap was hiding precisely the errors most
likely to occur — while three-or-more words still means the phrase is about
something else, which keeps "takes control of the bishop's diagonal" unflagged.
Both cases are pinned by tests, along with the "wins a pawn" material idiom that
the excluded `win` verb protects.

## v25 — the fix worked and the complaint stayed (2026-08-13)

Score 4.2 -> 4.3, which is noise. The interesting part is that the judge repeated
the endgame complaint almost verbatim, and was right to.

**The exclusion did exactly what it claimed.** The exposed-king guidance was in the
prompt on 16 of 18 endgame plies in v24 and on 0 of 18 in v25, still correctly
present on the middlegame plies 34-50.

**It was one of three sources.** Two more, both ours, were untouched:

1. **The engine's `best_move_idea` label**, rendered as "What the best move
   achieves: king safety — repositioning the king". Present on 14 turns, 8 of them
   endgame — *the same count in v24 and v25*. This is the loudest source and it
   sits in the highest-value line of the prompt.
2. **A hardcoded example in our own PEDAGOGY block**: `ask yourself: is my king
   safe?`, on every turn of every game, endgames included.

So the source that was easy to see was not the source that mattered. The lesson
generalises: when a review complains after a fix, count how many places produce
the thing complained about before concluding the fix failed.

**What we did.** Dropped the king-safety label in endgame positions using the same
phase heuristic the feature extractor uses (`phase_of_board`), and replaced the
PEDAGOGY example. Deliberately **no substitute label** — swapping one category word
for another is precisely what failed when the lesson table was phase-gated (row
20). On 6 of the 8 affected turns the composer already had a verified clause
("moving your king off e5 where it was attacked", "hitting their rook on f4 and
their bishop on g4" — the engine had mislabelled a double attack as king safety),
so the fact survives and only the frame goes. Only plies 1000 and 1002 lose the
whole line, and that is honest: we have nothing verified to say there.

**A dangling reference the test caught.** Three tier instruction blocks tell the
model to *use "What the best move achieves" shown above*. Removing the line left
that pointing at a section no longer in the prompt — an open invitation to invent
what it would have said, which is how "closer to the center" appeared on a turn
where we supplied nothing. The reference is now redirected when the line is
dropped.

**Two checker false positives, found by checking our own new violations.** v25
reported 4 text-level violations against v24's 2. Reading them:

- `illegal_move: Be6` at ply 60. The coach wrote "the pin on Be6 and f7", using
  `Be6` to mean *the bishop on e6*. Our own composer emits that notation ("Re1 pins
  Be6 to Ke7") and the coach echoed it. The board settles the ambiguity: plain SAN
  onto an occupied square is impossible, so when a piece of the named type already
  stands on the named square the token can only be a reference.
- `piece_type: "capture your knight"` at ply 60. The turn names one SAN capture
  (`Rxh7`, taking a pawn) and the checker applied that victim type to every capture
  phrase — including one about what the *opponent* could capture. Opponent-attributed
  capture claims are now skipped, reusing the same attribution helper the illegal-move
  check already had.

After both fixes, the two remaining violations are real: ply 36 names a bishop for a
knight capture, ply 40 puts the king on an empty f2. **And `piece_type` 1 -> 2 was
the checker improving, not the coach degrading** — ply 36 made the same error in v24
and the old regex could not see it.

**One real defect nothing catches.** At ply 60 the coach says "your opponent can
capture your knight on c3". Verified against the board: after the student's `Kf3`,
Black has **no legal captures at all**. A fabricated refutation, and no check exists
for it.

## v26 — the endgame inversion is gone, and why an empty slot is worse than no slot (2026-08-13)

Accept on every criterion written before the run.

| | v25 | v26 |
|---|---|---|
| king-safety frames on endgame achievement lines | 8 | **0** |
| endgame turns where the COACH says king safety | 4 / 18 | **0 / 18** |
| lesson concentration | 57% | **45%** (series best; was 82% at v17) |
| turns voicing a composed board fact | 61% | 66% |
| real text-level violations | 2 | 2 (identical) |
| judge score | 4.3 | 4.5 |

Two of 18 endgame turns lost the achievement line entirely (plies 1000 and 1002),
exactly as predicted — nothing verified was available to say there.

**The finding worth keeping is the output-side zero.** At ply 1002 we suppressed our
centrality clause and the model promptly invented "closer to the center" from its own
vocabulary. Here we removed the king-safety frame and it was **not** replaced by
anything. The difference is not the model, it is the slot: at ply 1002 the
"What the best move achieves:" header was still in the prompt with the clause taken
out of it, so there was a labelled hole demanding a reason. In v26 the whole line
disappears when nothing is verified.

**So: an empty slot is worse than no slot.** A header with nothing under it is an
instruction to fabricate. That refines the earlier rule (row 20 / row 23) — facts get
voiced, abstractions get paraphrased away, and *blanks get filled in*. It also means
the fix only worked because the dangling-reference problem was fixed alongside it:
three tier instruction blocks still said "use 'What the best move achieves' shown
above", and leaving those in place would have recreated the ply-1002 failure.

**The judge's endgame verdict changed character**, which is the independent
confirmation:

- v24: "most turns, worst pedagogy, and it is inverted… calls a centralized king
  'exposed' and recommends retreating it".
- v25: "the worst fit, and actively wrong in principle… frames it as *King safety
  first*".
- v26: "over-represented but shallowest… Plies 64, 70, 74, 78 are all 'move the piece
  off the attacked square' — that is threat avoidance, not endgame technique."

The inversion is gone. What remains is the hole we knowingly left, i.e. the
"endgame facts, not endgame prose" item. "King safety" now appears exactly once in the
whole review, under *No memory across turns* — flagged at plies 6, 16, 26, 34, 40
without ever saying "this is the fourth time". That is the middlegame, where the frame
is correct, so it argues for cross-turn memory rather than against this fix.

**Also worth noting the concentration drop was not the target.** 57% -> 45% came free:
removing a frame that fitted any position removed one of the three lessons everything
was collapsing onto. The metric moved because the cause moved, which is the first time
that has happened rather than the metric being argued with.

## Rebuilding the ask: same transcript, two rubrics (2026-08-14)

The coach's output and the judge's *ask* are two independent variables and we had
been changing them together. `scripts/eval_coach_rejudge.py` now re-judges a saved
transcript with no coach, no engine and no tunnel, so the ask can be isolated.

Run on the **identical** v26 transcript:

| | old ask (v1) | rubric v2 |
|---|---|---|
| headline | 4.5/10 | **2/10** |
| pre-gate weighted | — | 4.3/10 |
| fidelity | — | 4/10 — **gate fired** |
| diagnosis | — | 4/10 |
| transfer handle | — | 4/10 |
| executability | — | 6/10 |
| load discipline | — | 5/10 |
| stance | — | 6/10 |
| stream behaviour | — | 3/10 |

**The two asks agree on quality and disagree on what to do about it.** 4.3 pre-gate
against 4.5 is the same judgement. The gate is the new information: one false claim
about the board caps everything, because the student cannot detect it.

It fired on ply 36 — `bxc4` described as capturing "the undefended bishop on b4"
when it captured a knight. **Independently confirmed**: our own deterministic
checker flags that exact ply. The judge added a detail we had missed — b4 was still
occupied by that bishop twelve plies later (attacked at 44 and 46, hit by a3 at 48,
captured at 50), so the student would have carried a false board state for a quarter
of the game.

**The recommendation flipped.** Under the old ask, twice, it was cross-turn memory.
Under the rubric it is: verify claims about named pieces and squares *before
sending*, regenerate once, fall back to a composed sentence — noting that we already
run these checks and merely report them to a scoreboard. Cross-turn memory dropped
to being the Stream Behaviour blocker, and was split by cost: a silence rule for
quiet moves and an n-gram duplicate block are SMALL, the recurring-error tally is
MEDIUM.

**It reached the audit's Finding 2 independently**, from the transcript alone:

> The prompt orients around the engine's best move, so the model explains why that
> move is good and then reverse-engineers a lesson from it — which is why the
> student's hanging knight at ply 20 produced a lesson about attacking b4.

Its fix is concrete and cheaper than expected: give the composer the *cause of the
student's loss* as a first-class field (what was left undefended, which defender
moved away, what the moved piece had been doing) and require the takeaway to come
from that field, never from the best move's virtues. MEDIUM, and it observes the
engine data is largely present already.

**It also listed both fixes we shipped the same morning** under "what to remove" —
eval-machinery talk, and inventing a difference on 0cp moves — from a transcript
that predates them. Two independent routes to the same two changes.

**A correction to an earlier claim.** The flat 3.5-4.5 series was described here as
mostly judge re-anchoring noise. That is wrong: the old ask reproduced **4.5
exactly** on a transcript it had already scored 4.5. It is stable within a
transcript; what it fails to do is discriminate *between* coach versions. The
instrument was insensitive, not noisy — same conclusion, different diagnosis.

Raw reviews: `docs/audit/rejudge-v26-{v1,v2}.md`.

## v27 — the gate works, and the fabrication moved house (2026-08-14)

One run, three hypotheses, all three confirmed. Criteria were written before it ran.

| | v26 | v27 |
|---|---|---|
| near-equal turns (<=25cp) staging a comparison | 7 / 7 | **0 / 7** |
| turns voicing eval bookkeeping | 6 | **1** |
| gating fidelity violations in the output | 2 | **0** |
| rubric v2, pre-gate weighted | 4.3 | **5.2** |
| rubric v2, after gate | 2/10 | 2/10 |
| old ask (v1) | 4.5 | 4.5 |
| lesson concentration | 45% | 55% (worse) |
| composed-fact rate | 66% | 59% |
| latency mean / max (s) | 6.5 / 40.7 | 5.3 / 21.7 |

**The gate fired exactly once**, on ply 40 — the same turn that carried the phantom
"king on f2" in v26. It retried, the retry also contradicted the board, and composed
text was sent. Precise rather than trigger-happy, which was the risk.

**A measurement correction, mine.** The first pass reported 1 of 7 comparisons
surviving. That was my own regex matching "covers 5 squares *instead* of 2". The real
figure is 0 of 7.

**The surviving eval-talk turn is the fallback itself.** Ply 40's composed template
reads "That's a mistake — it costs about 1.4 pawns (eval -12.9 → -14.3). Kd3 was
stronger here." Truthful, and it violates a different audit item: eval numbers mean
nothing to a 1200 and train outcome-orientation. The safety net is analyst-era text.

### The finding worth the run: fabrication moved to a class we do not check

Rubric v2 capped v27 at 2/10 again, on a **different** defect. Ply 44:

> Your move, c5, aimed to challenge Black's position but overlooked an immediate
> threat to **your own bishop on b4**.

Verified against the board — `r1b5/ppppkp1p/8/8/1bPP3P/5K2/P1r5/RN4R1 w`, White to
move, so the student is White and the b4 bishop is **Black's**. Our checker passed it
because a bishop really is on b4 and it really is a bishop. The error is *ownership*,
which we do not check at all.

The judge named our own cause, and it checks out: the prompt says "attacking **their**
undefended bishop on b4" in one place and "developed minors: Bb4" in another with no
side tag. Its wording: *"facts reach the model without an owner… so the model guesses
owner."*

So the gate did its job and the model's fabrications relocated. That is the expected
shape of this work — each closed class exposes the next — but it is worth stating
plainly that a gate only gates what it checks.

**Underneath the cap, quality moved.** Pre-gate weighted 4.3 -> 5.2, with Diagnosis
4 -> 5, Transfer Handle 4 -> 5, Load Discipline 5 -> 6. The old ask stayed at 4.5,
which is the fourth run in a row it has failed to discriminate.

**One real regression.** Lesson concentration 45% -> 55%. Variety did not collapse —
30 vs 29 distinct cues, recycled phrasing 19% -> 18% — but mean cue length fell from
4.0 to 3.88 words and the cues got blunter, "a check" replacing "a check that forces
an answer". Fewer distinct content words is exactly what the metric counts. This is
the cue-quality weakness the audit predicted, now with a number on it.

**And one defect I introduced.** At ply 0 the coach echoed the new header verbatim:
its reply opens "What your move achieves: moving your knight from g1 to f3…". A new
label in the prompt became a new thing to parrot.

Raw review: `docs/audit/rejudge-v27-v2.md`.

## v28 — the fix worked, the strategy is on notice (2026-08-14)

The accept criteria were written before the run and one of them was a *strategy*
criterion: "reject if the gate fires on yet another unchecked class — that would mean
the model relocates its fabrications faster than we can close classes." It did. This
is recorded as a reject on the approach, not on the fix.

| | v26 | v27 | v28 |
|---|---|---|---|
| gating violations in output | 2 | 0 | **0** |
| ownership violations | (unchecked) | 1 | **0** |
| **ungated** rubric weighted | 4.3 | 5.2 | **5.7** |
| gated (shipped) rubric score | 2 | 2 | 2 |
| lesson concentration | 45% | 55% | **50%** |
| recycled phrasing | 19% | 18% | **15%** |
| composed-fact rate | 66% | 59% | 61% |
| turns falling back to composed text | 0 | 1 | 2 |

### Three rounds, three classes of falsehood

- v26: the wrong piece named as captured -> piece-type check widened.
- v27: the opponent's piece called the student's -> ownership check added.
- v28: **relationship geometry** — "Ke2 helps protect your pawn on g2" (a king on e2
  covers f2) and "Ke3 supports your passed pawn on d5" (e3 does not touch d5).
  Nothing checks this.

Each check worked on the case it was built for. Each time, the fabrication moved.

**But the relocation has a pattern, and that is the useful part.** All three are the
same shape: the model asserts a *relation between a piece and a square* it cannot
verify — captures what, belongs to whom, protects what. So the next step is one
general check over that family (defends / protects / supports / attacks), not a
fourth special case. If a fourth unrelated class appears after that, the approach
itself needs replacing rather than extending; the candidates are recorded in the
backlog.

### The gate is right as a standard and useless as a progress measure

It has read 2/10 for three consecutive runs while the coaching measurably improved —
ungated 4.3 -> 5.2 -> 5.7, Transfer Handle 4 -> 5 -> 6, Executability 6 -> 6 -> 7,
Stream Behaviour 3 -> 3 -> 4. A number that cannot move is the exact failure that
made the old single 0-10 worthless at 4.5 for fifteen changes.

**So from now on both are reported: gated for "is this shippable", ungated for "did
this round help".** The gate stays as the product standard — a beginner cannot detect
a falsehood, so the reasoning behind it is sound — but it is not the steering signal.

### Two of the four fixes were worse than first reported

Retractions, because the first report of them was wrong.

**The eval fix was half a fix.** Raw evaluations did go 1 turn -> 0, so that part
worked; the earlier claim of "2 turns" was our own regex matching "1.4 pawns". But the
audit names *pawn units* as a defect alongside centipawns, and the judge independently
flagged it under Stance: "the cost is shown to the student in pawns". The parenthetical
was removed and the thing it was parenthetical to was left.

**The header rename failed.** Turns echoing a prompt header: **0 (v26) -> 6 (v27) -> 8
(v28)**. The v27 report said one, because only the ply the judge cited was checked.
Renaming the label achieved nothing — the model copies whatever label it is given, so
the fix is to remove the label, not reword it.

### And the safety net is now a defect source

`off_menu` went 1 -> 3, one of which is our own fallback template emitting "moving d5
reveals Bc8 hitting Rg4" — an off-menu move named by composed text. The judge called
that same sentence unusable: "no owner or purpose". The fallback is what a student sees
precisely when the model is not trusted, so it should be the best composed sentence
available, not the worst.

Raw review: `docs/audit/rejudge-v28-v2.md`.

## v29 — the family closed, and what "one game" has been hiding (2026-08-15)

| | v27 | v28 | v29 |
|---|---|---|---|
| gating violations in output | 0 | 0 (2 visible retroactively) | **0** |
| turns echoing a prompt label | 6 | 8 | **0** |
| pawn units shown to the student | 1 | 2 | **0** |
| **ungated** rubric weighted | 5.2 | 5.7 | 5.05 |
| gated (shipped) | 2 | 2 | 2 |
| lesson concentration | 55% | 50% | 57% |
| recycled phrasing | 18% | 15% | 17% |
| turns falling back to composed text | 1 | 2 | 3 |
| latency mean / max (s) | 5.3 / 21.7 | 5.7 / 48.9 | **4.8 / 9.1** |

**The relation check closed the family.** It fired on ply 1002, the turn it was built
for, and the two relation errors detectable in v28's text are gone from v29's.

**Removing the label beat renaming it.** Echoes 6 -> 8 -> **0**. The rename landed
between the first two, so the earlier claim that it was fixed was wrong twice over:
wrong in effect, and only one of six instances had been checked.

**The gate fired on classes we already knew about.** This is the important
distinction, because the standing reject criterion was "a fourth *unrelated* class":

- **Ply 1003, verified**: `Ra8#` — `board.is_checkmate()` is True. The coach called it
  "a check" and asked whether it "buys me time to develop or improve another piece".
  Logged since v24 as "the coach does not notice the game is over" and never fixed.
- **Ply 38, verified**: FEN `r1b1k3/pppp1p1p/8/6r1/1bPP4/8/P1P1K2P/RN5R w` — White has
  **no bishops at all**. The coach said "h4 aimed to develop your king's bishop".
  Logged at v26 as "intent attribution the coach cannot know".

So the model did not invent a new kind of falsehood; it repeated two we had chosen
not to check. Adding checks is still converging, and the approach stands.

**The honest cost: truth up, repetition down.** Ungated 5.7 -> 5.05, with Stream
Behaviour 4 -> 3 and Transfer Handle 6 -> 5; concentration 50% -> 57%. Three turns now
read as composed text, which is truer and flatter. The judge's own read: eliminating
the ply-38/1003 class "stops the gate firing and takes the overall from 2 to roughly
5", and after that the SMALL stream fix is "the better quality-per-hour buy", predicted
to move concentration from 57% to roughly 30% and recycled phrasing under 10%.

### The measurement has been one game the whole time

Prompted by the product owner asking whether the engine had randomness. It does not,
on this path.

- The 44 student moves are **byte-identical across v26, v27, v28 and v29** (checked).
- `--seed` is written into the trajectory metadata and **never reaches the engine**.
  Blunder exposes no seed option; its randomness lives in the opening book and
  self-play, neither of which this harness uses. So `--seed 8` would replay the same
  game, and this document previously asserted the opposite.

The determinism is *right* for before/after comparison and it is why single-run deltas
have been trustworthy. But it means every conclusion here is drawn from one game, and
the reviewer has said repeatedly that this particular game is not representative — "a
shooting gallery", quiet and positional play "barely tested", the opening never past
ply 10 of theory. Overfitting to it is a live risk, and one that would be invisible
from inside the loop.

Raw review: `docs/audit/rejudge-v29-v2.md`.

## Do the checks generalise? Five fixed games (2026-08-17)

Prompted by the product owner noticing every report card replays the same game. The
concern was precise: changes validated on one game may not hold on another. It matters
more than it used to, because since v27 a failing check does not merely miscount a
metric — it **replaces the coaching a student reads** with composed text. A check that
was subtly too aggressive would be invisible on the fixed game and could quietly turn
the coach into a template elsewhere.

`scripts/eval_check_breadth.py` answers that and nothing else. Five **fixed** games —
no randomness, since randomness would destroy the reproducibility that makes the
harness trustworthy — and **no judge**, because violation and fallback counts are
deterministic. Twelve minutes, zero frontier credits.

| game | fallbacks / coached | rate | checks that fired |
|---|---|---|---|
| control (report-card game) | 1 / 16 | 6% | placement |
| french-quiet | 0 / 17 | 0% | none |
| **queens-gambit-quiet** | **3 / 14** | **21%** | piece_type, ownership |
| student-as-black | 1 / 27 | 4% | illegal_move, pawn_structure |
| stronger-student | 1 / 25 | 4% | placement |

`leaked_after_gate` was **0 on every game**: no false claim reached the student
anywhere.

### The outlier was the coach, not the checks

All three Queen's Gambit rejections were verified against the board:

- **ply 9** — `r1bqk1nr/pp3ppp/n1p5/3Pp3/Q2P4/2b5/PP1BPPPP/R3KBNR w`: c3 holds a **black
  bishop**, and the coach said the capture "captures a pawn".
- **plies 33 and 37** — White to move and the f6 knight is **Black's**; the coach wrote
  "your knight on f6" on both turns, five plies apart.

So the 21% is that game being harder, not the checks over-firing. **Zero false
positives across all five games.**

Two things follow beyond the immediate question. The checks **generalise**: written from
one game, they caught three unseen errors in an opening they were never tuned on — and
the ownership check, added from a single ply-44 case, found two more instances on its
own. That is the strongest evidence so far that the gate-first approach is converging
rather than playing whack-a-mole. And **quiet positional play is harder for the coach**:
the French game produced zero violations while the Queen's Gambit produced three in only
14 coached turns, which is the phase gap the standard audit predicted and the fixed game
cannot show.

**Caveat on the instrument.** The sweep mirrors the SHIPPING skip rules, so it coaches
only turns a user would actually see (good moves get no LLM call). The control game
therefore shows 16 coached turns against the report card's 44. The rates are comparable
— control 6%, v29 7% — but the denominators are not the same, so the control does not
cross-validate the report card's numbers directly.

**And a tooling lesson.** The first version counted violations without keeping the
rejected text, which made the only question that mattered — coach wrong, or check
wrong? — unanswerable without a re-run. It now stores the fragment, the reason and the
FEN, and prints them.

## Discovery vs coverage — and the rule for not drowning in it (2026-08-17)

A design discussion, recorded because it produced more directions than we can run at
once and the *restraint* is part of the conclusion.

### Two mechanisms, two jobs

- **The deterministic checks are COVERAGE.** They run on every turn of every game and
  catch known kinds of falsehood exhaustively. One game or fifty: if the coach makes a
  mistake of a kind we check, we catch it. The breadth sweep proved this — three real
  errors found in a game no check had ever seen.
- **The judge is DISCOVERY.** Its job is to spot kinds we do not check yet. Every one
  of our seven checks exists because the judge found one instance and we generalised it.

Judge finds the class; checks catch every instance.

### The hole

Discovery only sees what the fixed game contains. A kind of falsehood absent from those
44 turns is never discovered — and we now know the Queen's Gambit game is harder for the
coach than the fixed game, yet **nobody has ever judged it**. There could be several
undiscovered classes sitting in games we already generate.

### Randomness belongs here, and only here

Randomness is wrong for measuring change and right for finding bugs — the fuzzing split.
The discipline that makes it safe: **a random run that finds something gets PINNED** as a
fixed case. We already do this by hand — the ply-44 ownership FEN and the ply-26 geometry
FEN are hard-coded tests now. Reproducibility comes from *logging the coordinates* of a
hit, not from the search being deterministic.

Axes worth sampling, and none of them is a grid — sample points, do not enumerate:

1. **Coach level** (`--level`). Verified untested: every report card v1-v29 and all five
   breadth games ran `intermediate`, the default. **This is the largest blind spot**, and
   worse than a normal untested config, because the `beginner` branch instructs the coach
   to *avoid chess notation* — and nearly every check anchors on notation ("piece on
   square", SAN capture tokens). Beginner coaching may be both more error-prone and less
   checkable than the path we have spent thirty runs hardening.
2. **Phrasing** (temperature). Our falsehoods are linguistic — "your knight on f6",
   "helps protect your pawn on g2". At temperature 0 we sample ONE point from the space
   where the bugs live, for a given prompt. Raising it explores that space with no new
   games at all.
3. **Positions** (openings, sides). The obvious axis, and what the Queen's Gambit result
   argues for.
4. **Student strength** (engine Elo). Partly varied: 1350 everywhere, 1650 once.

Cost control: the checks are free, so fuzz wide with them; the judge is expensive and is
the only thing that finds unknown classes, so it gets a bounded sample of turns the
checks called clean.

**And the number of axes is itself a finding.** If beginner-level coaching needs its own
checks, the gate is coupled to a *phrasing style* rather than to truth — which is an
argument for the "allow only what we supplied" approach, because that does not care how
the sentence is written.

### The rule, agreed with the product owner

There are now two competing streams: **improving coverage** (finding new classes) and
**fixing what the checker already told us** (mate detection, intent attribution,
repetition). Running both at once produces a flood and finishes neither.

So: **fixing comes first while the known list is non-empty.** Coverage work is taken one
item at a time, and only when it is cheap and answers a specific doubt. Discovery
findings are logged, not immediately acted on — they join the known list and wait their
turn.

## The harness was not testing the coach (2026-08-18)

The most expensive finding of the project so far, and it came from the product owner
asking a plain question: why does the harness make the coach talk on every move when
the product does not?

### What was wrong

`Coach.evaluate_move` skips the model entirely on good moves — under 50cp drop, and
under 150cp in the first six moves. **Silence is a shipped feature.** The report-card
harness never called `Coach` at all: it rebuilt the middle of the pipeline itself
(fetch reports, select guidance, build prompt, call model, time it), so the skip rules
were never on its path. It coached all 44 student moves.

That is a *reconstruction* of the coach, not the coach. It drifted three times, each
found by accident:

1. **Guidance selection** — mirrored by hand, with a comment warning that otherwise
   "the report card grades a configuration that does not ship".
2. **Output verification** — absent entirely until 2026-08-14. v27 came close to
   measuring a coach with no fidelity gate while the product had one.
3. **The silence rule** — absent, and this one manufactured evidence.

### What it cost

Under shipping rules only **17 of 44** turns get commentary; 27 are silent. So:

- The "plies 74 and 78 are word-for-word identical" defect — quoted in three separate
  reports to the product owner as a real problem — is on turns with a **0cp drop**.
  No student would see either. Neither would ply 64, the near-copy.
- "43 of 44 moves get full-length commentary", a Stream Behaviour complaint worth 10%
  of the rubric weight, describes the harness, not the product.
- `lesson_concentration_rate` is computed over all 44 turns, most of which never ship.
  Recomputed on cues over shipping turns only, the top three cover **21%** of turns
  against 27% over all 44 — and both are far from the 57% the metric reports, because
  it counts shared content words rather than cues.

This is ledger row 17 repeating: the reviewer criticising an artifact of our own
harness, and us acting on it without checking. Three rounds were spent discussing a
duplicate no student can see.

### The fix, and why it is the right shape

The harness now calls `Coach.evaluate_move`. The prompt and generation time come from
the debug callback the coach **already emitted**; the `ComparisonReport` and
`PositionReport` come back attached to the result (`_comparison`, `_position_report`,
alongside the existing `_result_after` precedent), so nothing is re-run and nothing is
reconstructed. Roughly forty lines and six imports deleted.

The rule adopted with the product owner: **everything runs shipping behaviour,
always.** The only variable is how many games.

- **Report card** — one fixed game, shipping behaviour, judged. Measures change.
- **Defect harvesting** — more games, shipping behaviour, deterministic checks only,
  no judge. Finds defects.

An earlier proposal of a "force commentary" mode for harvesting was **rejected**, and
correctly: a defect on a turn that never ships is not worth fixing, and forcing
commentary manufactures exactly the fake material that produced the phantom duplicate.

### Two findings that fell straight out of it

**The judge credited the silence, unprompted:** *"Silence is correctly calibrated on
the genuinely fine moves. Plies 0 and 2 (0cp) and ply 1001 (Ra5+, 6cp) are not worth
interrupting a student for. Restraint on near-best moves is a real virtue and it has
it."* That behaviour has shipped for the entire project and had never once been
credited, because the harness hid it.

**And a real product bug: the coach is SILENT on checkmate.** The curated `Ra8#`
position produces no comment at all, because mate has a 0cp drop and the skip rule
sees only the number. Which reframes the previous round entirely — the mate-labelling
defect (the reviewer's "decisive item", ledger row 42) **only ever existed because the
harness forced commentary on a good move.** In production the coach never said
anything false about mate; it said nothing. Both are wrong, and silence is arguably
worse: a student who has just won gets no acknowledgement the game is over. The
terminal-label check still earns its place — it stops a falsehood when the coach *does*
speak — but the real fix is the skip rule.

### Consequence for the numbers

The score series changes basis: per-turn metrics measured over 44 forced turns are not
comparable with ~17 real ones. v31 onward is a new series, and the ledger says so.

## v31 — the first honest measurement (2026-08-18)

The first run where the reviewer judged what a student actually receives. **A new
series**: per-turn metrics over 18 coached turns are not comparable with the 44 forced
turns of v1-v30.

**The gate did not fire, for the first time in five runs. 2/10 -> 5.7/10.**

| | v30 (forced, 44) | v31 (shipping) |
|---|---|---|
| turns coached / silent | 44 / 0 | **18 / 26** |
| gated score | 2 | **5.7** |
| fidelity | 4 (gate fired) | 5 |
| diagnosis | 5 | 5 |
| transfer handle | 6 | 6 |
| executability | 7 | 6 |
| load discipline | 6 | 6 |
| stance | 6 | 7 |
| stream behaviour | 3 | 5 |
| lesson concentration | 57% | **18%** |
| recycled phrasing | 16% | **4%** |
| deterministic violations | 3 | 1 |
| composed-fact rate | 57% | 34% |
| latency mean | 6.7s | 2.5s |

**Nothing about the coach changed between these two runs.** The repetition problem we
spent three rounds on was mostly the harness: concentration fell from 57% to 18% and
recycled phrasing from 16% to 4% purely by measuring the turns that ship.

The composed-fact drop (57% -> 34%) is real and expected: 5 of the 18 coached turns are
composed fallbacks, which voice no model prose by definition.

**The reviewer credited the silence:** *"Silence discipline is real and valuable — 26 of
44 turns empty, and the engine-top moves at plies 24, 32, 48, 50, 64-78 correctly get
nothing."*

### Two warnings, one from the reviewer and one from us

**The margin is thin.** Its own words: *"Fidelity is one flagged claim from capping the
whole score at 2 — the margin is thin, not comfortable."* 5.7 is not a stable 5.7; it is
2/10 plus one lucky turn.

**And silence has a cost we had not measured: two real mistakes get NO comment.** Ply 6
`Ng5` (91cp) and ply 8 `b3` (138cp) are both silent, because the opening rule suppresses
anything under 150cp in the first six moves. `Ng5` is the move the reviewer has blamed
across several runs for losing a knight later. So the student makes a genuine error and
hears nothing at all — the mirror image of the checkmate bug, from the same cause: **the
decision to speak is made on a number, not on whether there is something to teach.**

The reviewer arrived at the same place independently, and it is now the top item:
*"Stop gating speech on eval drop; gate it on whether a teachable, engine-checkable
feature exists."* Cost MEDIUM — a small detector set over what the composer already
computes (king not castled by move ~10, a loose piece, a hanging piece).

Raw review: `docs/audit/rejudge-v31-v2.md`.

## The engine's numbers are not the truth (2026-08-20)

This started as "why do two real mistakes get no comment" and ended somewhere else
entirely. The short version: the eval drop we build coaching on disagrees with a strong
reference on **20 of 44 turns**, and the disagreement is worst on exactly the turns we
choose to speak.

### What we set out to do, and why it dead-ended

v31's top item was to stop gating speech on the eval drop and gate it on whether there is
something teachable. Before building the detectors, we measured them against the two
turns they were supposed to catch (ply 6 `Ng5` 91cp, ply 8 `b3` 138cp, both silenced by
the opening rule):

| signal | fires on silent turns | wanted | unwanted |
|---|---|---|---|
| `critical_moment` | 13 | 1 | 12 |
| our piece loose | 6 | 0 | 6 |
| opponent wins material | 5 | 0 | 5 |
| uncastled, king central | 4 | 0 | 4 |
| gives check | 2 | 0 | 2 |
| `missed_tactics` | 1 | 0 | 1 |
| `refutation_line` | 0 | 0 | 0 |

Ply 6 is invisible to every one of them. Wiring `critical_moment` in would have taken us
from 18 coached turns to 30 and thrown away the silence that earned v31 its score. The
whole idea is rejected on measurement — see ledger row 52.

### The opening threshold is justified, not obsolete

`0d0d664` added the 150cp opening leniency for BUG-008. That reason still holds, and is
worse than the commit recorded. At depth 8:

| sound book move | drop | | bad but named | drop |
|---|---|---|---|---|
| Ruy Lopez Morphy `...a6` | 110 "mistake" | | Barnes `1.f3` | 52 |
| Sicilian `1...c5` | 109 "mistake" | | Grob `1.g4` | 64 |
| Budapest `...e5` | 87 | | Damiano `...f6` | 136 |
| English `1.c4` | 67 | | Borg `1...g5` | 129 |

Our engine rates the Sicilian as worse than `1.f3`. Lowering the threshold to 50 would
have the coach criticise a student for playing the Sicilian. Proposal withdrawn.

`is_book_move()` — added by the same commit "for future use" — cannot rescue it either.
The ECO set names bad openings: Damiano, Grob, Barnes, Borg, Ware and the Irish Gambit
all return `True`. And no eval cap separates the two populations, which overlap 52..110
at depth 8 and 65..114 at depth 12.

### Concreteness, not phase, predicts whether we can trust a number

Two independent experiments now agree. Depth stability across depths 8/10/12/14:

| group | n | mean swing | max |
|---|---|---|---|
| concrete (capture, check either way, or a detected tactic) | 24 | **3.6 cp** | 42 |
| quiet | 20 | **22.9 cp** | 96 |

And against Stockfish 18 at depth 22, signed error: concrete **+2.8cp**, quiet
**+76.4cp**. The opening looked special only because opening moves are quiet. This game's
endgame was a forcing king-and-pawn race, which is why it was the *most* stable phase.

### The measurement that matters

Stockfish 18 (winget, official release), depth 22, all 44 turns, drop computed as two
White-relative analyses so there is no sign guesswork.

| group | n | mean abs error | median | best-move agreement |
|---|---|---|---|---|
| turns the coach **spoke** on | 18 | **139 cp** | 100 | **4 / 18** |
| turns it stayed silent on | 26 | 35 cp | 11 | 13 / 26 |

Signed error on the spoken turns is **+122cp**: Blunder overstates the cost by more than
a pawn on average, on precisely the turns we act on. This is a selection effect and it is
vicious — we speak *because* the drop is large, and large drops are disproportionately
the engine's own errors. The speak rule is a filter that finds false alarms.

Seven of the eighteen spoken turns criticised a move the reference scores good or nearly
good:

| ply | move | we said | Stockfish |
|---|---|---|---|
| 1000 | `e5` | 323 — blunder | **5 — good** |
| 52 | `Nc3` | 184 — blunder | **2 — good** |
| 42 | `Rg1` | 166 — blunder | **8 — good** |
| 60 | `Kf3` | 180 — blunder | **20 — good** |
| 40 | `Kf3` | 143 — blunder | **22 — good** |
| 34 | `Ke2` | 413 — blunder | 72 — inaccuracy |
| 22 | `Bb2` | 66 — inaccuracy | **0 — good** |

And plies 62, 72, 74, 78 cost 154, 132, 93 and 181cp by the reference; we scored them 17,
38, 0, 0 and said nothing.

**This reframes the `equal`-tier work.** We added a tier that withholds the alternative on
near-equal moves precisely to stop the model manufacturing fault, because an external
audit called that harmful rather than sloppy. That fixed the coach's behaviour. It did not
fix the cause: the engine was telling us these were bad moves.

### It is not our plumbing, and it is not depth

| configuration | labels matching Stockfish |
|---|---|
| coach protocol, depth 8 (shipping) | 23 / 43 |
| plain UCI, depth 8 | 24 / 43 |
| plain UCI, depth 16 | 25 / 43 |

- **Plumbing:** coach protocol vs plain UCI at the same depth differs by signed −2.6cp.
  No systematic misread. (22cp of absolute scatter, and a different best move 17/43 times,
  from running multipv — nondeterminism, not a bug.)
- **Depth:** doubling it buys one label. Depth 16 moved Blunder *closer* to the reference
  on 18 positions and *further* on 20. A coin flip. No convergence with depth points at
  the **leaf evaluation**, not the horizon.
- **Rejected sub-hypothesis:** king moves. Elevated overall (+76 vs +43) but endgame king
  moves are the *best* case (+18 vs +69) and the largest single error is a bishop move.

### What this does and does not touch

**Unaffected:** the fidelity gate. Every gating check reads the board — placement,
ownership, legality, mate, reachability — and none consults the eval. The coach's factual
claims are still checked against truth.

**Compromised:** judgement. Which move to criticise, how much it cost, and which move to
recommend instead. Best-move agreement on spoken turns is 4/18.

**Hypothesis killed (2026-08-20, by Blunder's author):** we guessed we were running an HCE
build while the 2500 rating came from NNUE, which would have made this a configuration
mistake on our side. Wrong — the 2500 figure *is* HCE, release build, and dev vs release
is latency only at fixed depth. There is no wrong-evaluator explanation.

What follows from that is probably the real conclusion: **playing strength and
per-position evaluation accuracy are different quantities, and we conflated them.** An
engine earns a rating over whole games, where depth compounds and eval errors partly
cancel. Nothing about that requires the static evaluation of an arbitrary quiet position
at depth 8 to be within a pawn of the truth. If HCE at release is a genuine 2500, then
Blunder is doing what hand-crafted evaluations do, no Blunder-side fix exists, and the
mistake is architectural and ours: we assumed "2500 Elo" implied "trustworthy per-position
verdicts". It does not.

**Retracted:** the eval-drop columns in this document are Blunder-depth-8 numbers, across
thirty-one runs. Roughly half the labels would read differently against a strong
reference. Any conclusion resting on drop magnitude needs re-reading — including our own
`Ng5`/`b3` claims, twice over (rows 51, 55).

### The fairness caveat, stated plainly

Blunder at depth 8 versus Stockfish at depth 22 is **not** a fair engine comparison, and
nothing here should be read as one. It is a measurement of *our shipping configuration
against the best available proxy for truth*, which is the question chess-coach needs
answered. Whether Blunder is a good engine at equal resources is a different question,
needs equal-node or equal-time controls, and belongs in Blunder's repo. Brief:
`docs/blunder-eval-brief.md`.

Raw data: `output/bias_v31_stockfish.json`, `output/depth_sweep_v31.json`,
`output/fair_v31_abcd.json`.

## Three problems, not one — and two of them are Blunder-side wins (2026-08-20)

A Kiro session run inside the Blunder repo (`kiro-cli chat` with Blunder as its
workspace) answered the brief, and a follow-up analysis of the paired data changed the
diagnosis substantially. The headline from yesterday — "Blunder's evaluation is off" — was
too coarse. There are three separable problems and only one of them is a limitation we
have to live with.

### 1. The units really are non-standard — but that is NOT the explanation

Source-verified in a second Blunder session. `PIECE_VALUE_BONUS` pawn values are **124
(MG) and 206 (EG)**, the Stockfish-classical family. The final score is a phase blend,
`(mg*p + eg*(PHASE_MAX-p))/PHASE_MAX`, so one pawn slides continuously from 124 to 206.
Nothing rescales it: `Search.cpp:441` prints `pvline.score` verbatim, there is no `/100`,
no win-probability mapping, and no `UCI_NormalizeToPawnValue` equivalent. (A
`tanh(score/400)` exists in `MCTS.cpp:236` but that is the MCTS value head, unrelated.)

So a real consequence: **every centipawn figure we have ever recorded is in Blunder units,
1.2 to 2x conventional.** Our 50/100/150 thresholds are tighter in real terms than they
appear.

**But this does not explain the disagreement, and I claimed it did.** I fitted a single
constant, got k=1.91 against the 2.06 implied by the endgame pawn, and concluded half the
error was arithmetic. The phase-aware test kills that:

| phase | empirical best-fit k | source-predicted |
|---|---|---|
| endgame | **0.79** | 2.06 |
| middlegame | **1.88** | 1.24 |
| opening | **0.76** | 1.24 |

The slopes contradict the pawn values and run in the opposite direction. And the
correction the source actually implies performs *worse* than a flat one:

| conversion | mean abs error | labels matching |
|---|---|---|
| raw | 79.3 | 23 / 43 |
| flat ÷2.06 | **50.0** | 24 / 43 |
| flat ÷1.42 (best fit) | 59.4 | 25 / 43 |
| **phase-aware ÷1.24 or ÷2.06** | **60.8** | 24 / 43 |

If this were a unit problem, the source-derived phase conversion would be the best
available correction. It is the worst. A flat divisor helps only because Blunder's errors
are positively biased, and dividing any inflated distribution shrinks it toward truth —
curve-fitting, not calibration, and it will not transfer to new positions.

What survives is the Pearson +0.83 on quiet positions, which is a genuine correlation and
does say Blunder's judgement broadly tracks the reference there. What does not survive is
the claim that the residual is a scale artefact.

Note also the inversion on concrete positions: Pearson +0.22 but Spearman **+0.75**. The
*ordering* is good; a few large magnitude outliers wreck the linear fit.

### 2. A 50–60cp residual — the real limitation, under every conversion

Raw, flat-calibrated and phase-calibrated all leave 50 to 60cp of mean absolute error
against the reference, and label agreement never moves out of the 23–25 of 43 band. Our
label bands are 50 and 100cp wide, so no conversion makes the grading trustworthy.

**The action survives every twist in the diagnosis:** stop grading moves and stop quoting
centipawn costs. Not because the engine is wrong, but because the instrument is coarser
than the distinctions we were drawing with it.

### 3. Missing endgame draw knowledge — no divisor fixes this

Blunder's HCE has no KPK rule, no key squares or opposition, and no endgame draw-scaling.
The only draws it knows are repetition and the fifty-move rule. From the source, on
`8/8/4k3/8/4P3/4K3/8/8 w - - 0 1`:

| term | eg value |
|---|---|
| pawn e4: material 206 + PSQT −13 | +193 |
| kings e3 vs e6, mirror images | 0, cancel |
| passed +57, isolated −20 | +37 |
| tempo | +28 |
| **static leaf** | **≈ +230 to +258** |

And search makes it *worse*, which explains our measured "no convergence with depth". The
passed-pawn endgame bonus by rank is `{15, 36, 57, 78, 99, 120}` and the king endgame PSQT
rewards central, advanced kings (peak ~+199). As the PV walks the pawn up and centralises
the king, both terms grow monotonically, so every leaf looks more winning and minimax
returns a rising score. Search can only overturn a static verdict by reaching a leaf with a
different *recognised* value — a capture, a promotion, a repetition. Against correct
defence no such leaf exists inside the horizon.

Confirmed at **equal nodes** (1M each), which is the fair control: Blunder +351 and
climbing, Stockfish 0 to 2. And `+407 ÷ 2.06 = +198` — scaling cannot turn a draw into
zero, so this is a genuine knowledge gap and independent of problem 1.

### Latency is not the constraint, which kills one option permanently

The dev build runs ~3M nps and reaches depth 15 on that endgame in under 20ms. The bias
lives in the leaf evaluation, so more time buys a *stabler* number, not a truer one.
Raising `coaching_depth` is dead as an idea — cheaper to know than to discover.

### Correction: my retraction was wrong, the original claim was right

I reported that the KPK draw is invisible to static evaluation in both engines, and
therefore that the fault lay in Blunder's search rather than its leaf evaluation.

Wrong. Attempt 1's +2.85 was Stockfish's **classical** evaluation. Its default **NNUE**
static eval prints +0.01, final **+0.00**. So the draw is invisible to Blunder's HCE static
eval and visible to Stockfish's NNUE static eval, and the original leaf-evaluation framing
was correct.

Both the claim and its retraction were made on a single unreplicated measurement. That is
the recurring failure on this thread and it has now produced four reversals
(`Ng5` twice, `b3`, and this one).

### Where this leaves the engine question

**We are not replacing Blunder.** Stockfish's role here is as a *calibration reference*,
which is what a reference engine is for. Two of the three problems are tractable on the
Blunder side and both are already known to its author:

- **normalize the scores** — addresses problem 1, and the ~1.9x we measured is an estimate
  of the factor
- **NNUE, currently unoptimized** — the natural fix for problem 3, since a learned
  evaluation picks up endgame draw structure that no hand-written term encodes. Worth
  measuring as soon as a build exposes `EvalType`; our dev binary does not.

Problem 2 is ours to design around, and does not need a different engine — it needs us to
stop asking for a precision the instrument does not have.

Caveats: 20 quiet positions from one game. The k≈1.91 estimate is rough, and its closeness
to 206/100 is suggestive rather than proof. Correlations on the "spoke" subset are
depressed by range restriction, since that subset is selected on Blunder's own large drops.

Session logs: `output/blunder_session_attempt1.log` (killed on budget) and
`~/.kiro-monitor/runs/blunder_eval/output.log` (the answer).

## Stop asserting magnitude (2026-08-24)

The first change made in response to the Blunder measurement, and the one that was
correct regardless of how the engine question resolves. Rows 63-65.

### What the argument actually licenses

The measurement says the eval **magnitude** is untrustworthy, not that the engine is
useless. Two things survive it and one does not, and the change follows that split
rather than deleting everything eval-shaped:

- **Ordering survives.** Blunder is a genuine ~2500 at choosing between moves, and the
  Blunder session's own advice was to lean on relative ordering. So the candidate menu
  keeps its order and its tags, the "Best move" line stays on the tiers that compare,
  and the top-lines section keeps the moves.
- **Board facts survive**, because they never came from the eval. Material is now
  *counted* from the board in points. The opponent's reply and what it captures is
  computed by pushing the move. These are checkable by the student, which is the
  property the numbers never had.
- **Magnitude does not survive, in any unit.** Not "centipawns" (Blunder's pawn is 124
  MG to 206 EG, so the label was false), not pawns (dividing an unknown unit by 100
  produces another unknown unit — this was the half-fix at row 39), and not the
  engine's `classification`, whose cut points sit on those same units with unknown
  provenance.

### What replaced the severity claim

The interesting part is not the deletion, it is what carries severity instead. The old
`serious` tier opened by naming the size of the error ("this was a serious mistake").
It now opens with the consequence: *"After your move, the opponent's strongest reply is
exd4, capturing your bishop on d4."* That sentence is derived by pushing the student's
move and reading the board, so it is true by construction — and it tells a 1200 more
than "you lost 878 centipawns" ever did.

The `inaccuracy` and `serious` tiers therefore now share an opener. That reads like a
loss of resolution and is in fact the honest consequence of the measurement: the
boundary between them is 100cp on a quantity whose residual against Stockfish 18 is
50-60cp under every conversion tried. The distinction was inside the noise. The tiers
still differ in what they lead with and in word limit (80 vs 120), which is the part
that was never a claim about the board.

### The two findings that fell out

**Row 28 was overstated.** It recorded the `equal` tier as withholding the alternative
"from the prompt entirely". It did not: `Best move: d4` was rendered unconditionally,
and the top-lines section named the engine's move a second time — both above an
instruction reading "Do NOT offer an alternative… there isn't one". So the tier that
was supposed to stop the coach manufacturing fault on good moves was relying on
precisely the negative-constraint pattern rows 2 and 39 measured as ineffective. The
second of the two leaks was caught by the new cross-surface test rather than by
reading the code, which is the argument for having the test.

**A partial drop is a real category, including for me.** `engine_trust` existed because
two earlier drops turned out to be live on a second path. Writing this change I
recorded `best_move_idea` as fully dropped, then rendered a real prompt and found it
still there, trailing the composed clause as a theme label — which is deliberate
(rows 9 and 13), not a leak. Corrected to `USED_UNVERIFIED` with the compensation
named. The register works, provided someone reads the output instead of the diff.

### Measured, and not measured

**Measured, prompt-side.** `scripts/measure_prompt_magnitude.py` re-renders the 18
spoken turns of the v31 game through today's code, using the engine and no LLM, and
compares against the prompts stored in that run's transcript:

| | turns carrying a magnitude | occurrences |
|---|---|---|
| before (as sent on v31) | **18/18** | `centipawns` x79, `Evaluation drop` x18, `Classification:` x18, `Annotation:` x18, bare `N cp` x6 |
| after (same positions, today) | **0/18** | none |

**Not measured: whether the model still does it anyway.** A 14B model can produce "that
was a blunder" from its own pretraining with nothing in the prompt suggesting it, and
this project has three recorded cases of an instruction alone changing nothing. So the
change ships with a falsifier rather than an assumption: `ReviewStats.graded_or_priced`
counts turns where the coach pronounced a grade or put a number on the cost, and
`prompt_magnitude_leaks` guards the prompt side from regressing. Both should be 0. The
regex behind the first is pinned in `tests/test_coach_review.py` against ten sentences
it must catch and nine ordinary coaching sentences it must not — because two metrics in
this module were previously deleted for being unable to fail.

This needs a report card on **qwen3:14b** to settle, and that model is reachable only
over the EC2 tunnel, which is down. Until then: prompt-side landed, output-side open.
If `graded_or_priced` comes back non-zero, the next lever is a check in `verify.py`, not
more prompt text.

### What this deliberately did NOT touch

- **The move-menu tags** (`best`/`sound`/`dubious`/`blunder`) still come from eval-drop
  against the 50/100 thresholds, so a tag inherits the magnitude problem even with the
  number hidden. Re-deriving them means choosing new bands, and choosing bands by hand
  is what produced the current ones.
- **The `describe_eval` standing bands** (30/100/300) have the same defect, more mildly.
  A position at -102 units reads "clear advantage" where deflated it is a slight edge.
  Kept as a judgement that one of four coarse words beats silence, explicitly not as a
  claim that the bands are right — how often they land the wrong side of a boundary is
  not measured.
- **The 150cp opening leniency and `EQUAL_MAX_DROP_CP`**, both of which are band
  questions the backlog says to settle from the Blunder answer rather than by guessing.
- **`eval/judge.py`**, which hands the frontier judge a section headed "Evaluation
  (ground truth)" containing the same untrustworthy numbers. That is a measurement
  surface, not a coach surface, but the label is now known to be wrong — new backlog
  item.

## Re-deriving the thresholds for a normalized engine (2026-08-25) — row 68

Row 67 found the engine's output scale had halved under us and left the coach 2x more
lenient than anyone chose. This is the correction, and the rule it was done under matters
as much as the numbers: **chess-coach does not work around Blunder's shortcomings.**

### What that rule ruled out, and what it ruled in

Ruled in: converting our own constants by the engine's own factor, so behaviour is
preserved. `EQUAL 25->12`, `SOUND 50->25`, `DUBIOUS 100->50`, opening leniency `150->75`,
`objective.EQUAL_THRESHOLD_CP 50->25`, `describe_eval` bands `30/100/300 -> 15/50/150`.
The engine reports `round(raw/2)`, so `<= 12` admits `raw <= 25` — the old band exactly.

Ruled out: widening any band to compensate for the engine being *wrong* rather than
differently *scaled*. The temptation is real and specific — `EQUAL_MAX_DROP_CP` exists
because the coach was manufacturing fault on good moves, and the eval's +122cp bias is
still there, so widening it would visibly help. It would also be chess-coach absorbing an
engine defect into its own constants, where it becomes invisible and permanent. The bias
stays recorded in `engine_trust` with a reinstatement criterion instead.

Also ruled out, and this one was already shipped before the rule was applied: a
board-derived **material count** written to replace the engine's untrustworthy `material`
term. Removed. Piece values are contested knowledge, `pedagogy.features` already confines
its own copy of them to keying guidance "never to evaluate a position", and the backlog's
rejected-directions list names "derive board facts to replace the eval" explicitly.
`PositionReport.eval_breakdown` is now recorded as a real capability gap with nothing
compensating — the coach cannot state the material balance. That is the intended
consequence of the division of labour: a quieter coach until the engine improves. Nothing
is hidden from the model, which still gets every piece in the placement block.

### Verified against the engine, not by arithmetic

Row 53's book positions, re-measured on the normalized binary:

| position | old units | normalized | ratio |
|---|---|---|---|
| Ruy Lopez Morphy `...a6` (sound) | 110 | 55 | 2.00x |
| Sicilian `1...c5` (sound) | 109 | 55 | 1.98x |
| `1.f3` (genuinely bad) | 52 | 26 | 2.00x |

Row 53's finding survives intact: the bad move still scores *lower* than the sound book
moves, so no threshold separates them and the leniency has to sit above 55. 75 does.

And the six plies row 67 found silenced (22, 26, 38, 44, 56, 58) all speak again, at
drops of 33/34/36/27/29/30 against the new `sound` band of 25. **6 of 6 restored.**

### Three latent copies of the thresholds, found by doing this

- The `<= 50` "say nothing about a good move" rule was **hardcoded twice** in `coach.py`
  rather than reading `SOUND_MAX_DROP_CP`, so the coach's central silence rule would have
  kept using pre-normalization numbers while everything else moved.
- `web/server.py`'s SSE play path had a **third copy of the whole ladder** (150/50/100).
- The 150 leniency was duplicated **three times**. Now one `OPENING_LENIENCY_CP`.

The tests are the other half of the lesson. About a dozen assertions hardcoded 50/51/100/
101; every one failed on the rescale and not one of them was telling us anything about the
code under test. They now reference the constants, plus one new assertion that the bands
are *ordered*, which is the invariant that actually holds and which a rescale could break
while every boundary test still passed.

### What this does NOT fix, and the standing risk

Normalization changed the unit, not the accuracy. The drawn KPK position now reads +178
where it read +355; the answer is 0. The ~50cp residual against Stockfish on quiet
positions is untouched, and it is still as wide as the whole `sound` band — so row 62's
conclusion, and the magnitude change built on it, both stand.

**The Blunder change is uncommitted.** These thresholds assume it. If it is reverted or a
clean checkout is built, they become 2x too strict and the coach starts criticising the
Sicilian — BUG-008 all over again. Probe to check with: the KPK position at depth 16 reads
178 normalized, 355 raw.
