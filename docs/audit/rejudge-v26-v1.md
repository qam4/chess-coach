[38;5;141m> [0mSCORE: 4.5/10[0m[0m
[0m[0m
[38;5;252m[1m## STRENGTHS[0m[0m
[0m[0m
[1mThe bridge scaffold is actually there, and occasionally it lands well.[22m Ply 6 is the model turn of the whole transcript: Ng5 instead of O-O, and the coach names king safety, ties it to castling [3mand[23m connecting rooks, then gives a re-usable check ("have I secured my king before opening the center?"). Ply 8 (b3 leaving Bc4 hanging) is similarly tight â€” threat, refutation, better square, transferable question. Ply 56 is the best middlegame turn: Re4 hits the d4 rook and the e6 bishop, and "can I find a move that hits two of my opponent's pieces at once?" is a real, level-appropriate skill named from a real board fact.[0m[0m
[0m[0m
[1mRefutations are usually concrete rather than abstract.[22m On mistakes and blunders the coach almost always names the opponent's punishing move (ply 20 fxg5, ply 28 Rxg5, ply 34 Nxc4, ply 42 Rxc4, ply 52 Rh3+, ply 1000 Kxe5). That is the difference between "this was bad" and teaching, and it's the architecture working â€” the composer supplies the fact, the model voices it.[0m[0m
[0m[0m
[1mLatency is acceptable in steady state.[22m p90 5.6s means a played game feels responsive once warm.[0m[0m
[0m[0m
[38;5;252m[1m## WEAKNESSES / PROBLEMS[0m[0m
[0m[0m
[1mIt invents corrections where the engine says there is none.[22m Six turns have 0cp drop and still get told a different move was "better": ply 0 ("Nc3 achieves even better development" â€” the engine says the two are equal, and the claim that Nc3 is "a more active square" than Nf3 is not chess, it's filler), ply 2, ply 10, ply 54 ("Rge1+ slightly refines rook placement" â€” vacuous), ply 1001, ply 1002. This is corrosive: the student is being corrected for playing a best move. At ply 4, 48, 64 the coach correctly just says "great move," so the harness knows the difference; the prompt is pushing a comparison that shouldn't exist.[0m[0m
[0m[0m
[1mBoard-fact errors that the fidelity metric does not catch.[22m The 0%-unsupplied-square stat is true and still hides real falsehoods, because the model recombines [3msupplied[23m facts wrongly:[0m[0m
- Ply 30 says "your opponent immediately captures your bishop on d4 with exd4" â€” then ply 32 the [3mstudent[23m plays exd4 and is told they "captured their pawn on d4." Both cannot be true; wrong side, wrong piece type.[0m[0m
- Ply 36: "bxc4 wins material by capturing the undefended bishop on b4." bxc4 captures on c4 â€” it's the recapture of the knight from ply 34's Nxc4. The b4 bishop exists (it's taken at ply 50), so the square passes fidelity while the sentence is flatly false.[0m[0m
- Ply 40: "your opponent threatens to attack your king on f2" â€” the king just moved to f3.[0m[0m
- Ply 20 claims a3 "directly addresses the threat" of fxg5. It does not; it's a counterattack elsewhere. The student is being told a non-defence defends.[0m[0m
[0m[0m
Six deterministic violations in 44 turns (~14%), including two [3munsound[23m recommended moves, is disqualifying for a teaching tool independent of anything stylistic. A student cannot detect these; that's the whole reason they're using a coach.[0m[0m
[0m[0m
[1mNo memory, so the actual lesson of the game is never taught.[22m The student declined O-O at ply 6 and then spent the entire game hand-walking the king: Ke2 (14), Kd1 (20), Ke2 (28/34), Kf3 (40). Four separate turns (16, 26, 34, 40) diagnose "your king is exposed, find a safer square" as if it were fresh news. Not once does the coach say "this is the third time we've paid for not castling on move 4." A teacher's leverage is the arc; this coach is 44 unrelated position analysts.[0m[0m
[0m[0m
[1mRepetition is worse than the 19%/45% numbers suggest.[22m Plies 74 and 78 are word-for-word identical. Plies 12, 18 and 24 share a whole stock sentence. Every single one of 44 turns ends with "Next time you see X, ask yourselfâ€¦" â€” the shape itself is now noise, and by ply 40 a student skips it. The three attractor lessons are easy to see by eye: "undefended piece â†’ attack it" (36, 38, 44, 46, 48), "a capture â†’ how does the recapture go" (12, 18, 22, 24, 32, 50), "threatened piece â†’ move it somewhere safe and useful" (8, 34, 40, 62, 70, 74, 78).[0m[0m
[0m[0m
[1mHarness internals leak as if they were chess.[22m "The evaluation spread shows it was a key decision" (12, 18, 24), "the evaluation difference between your move and the third-best option was huge" (50), "the evaluation drops significantly" (40), "the evaluation difference shows a clear path to better play" (44). This is the tool talking about itself. It teaches nothing and reads as machine.[0m[0m
[0m[0m
[1mHollow and contradictory praise.[22m Ply 62 opens "Great move, Rxh7" and then immediately says the best move was Rgg1 (17cp). Ply 76 calls a 28cp king-shuffle "sound." Ply 68's "Great job taking the undefended rook" is praise for taking a free rook â€” in a game where the student has dropped a bishop, a knight and multiple pawns, the praise budget is misallocated to the trivially forced.[0m[0m
[0m[0m
[1mIt misses checkmate.[22m Ply 1003, Ra8#: "it gives check â€¦ Does this force my opponent to respond, giving me time to act?" The game is over. Failing to recognise mate is the kind of error that ends a user's trust in one turn.[0m[0m
[0m[0m
[1mCold start.[22m 40.7s on ply 0, then 21s on plies 2 and 4. The first three moves of every session are the ones that decide whether the user keeps playing, and they are the slowest by 4-8x.[0m[0m
[0m[0m
[38;5;252m[1m## PHASE FIT[0m[0m
[0m[0m
Coaching is close to phase-blind; one middlegame-flavoured heuristic set is applied everywhere.[0m[0m
[0m[0m
[1mOpening (10 plies, thinnest coverage).[22m The vocabulary is right â€” development, centre, castling â€” and ply 6 is genuinely good. But it is one-move-at-a-time rule recitation: no opening named, no plan beyond "put pieces toward the centre," and this is where the fake 0cp corrections cluster (plies 0, 2, 10). What an opening coach owes the student is a [3mscheme[23m â€” three or four moves of intent â€” not a per-ply verdict.[0m[0m
[0m[0m
[1mMiddlegame (16 plies).[22m Correct emphasis (threats, hanging pieces, material) and also where nearly all the factual damage is (30, 32, 36, 40). It reports refutations but never teaches the [3mprocedure[23m that would have prevented them â€” a candidate-move / "what does his last move threaten" routine. Ply 52's "what is my opponent targeting right now?" is the one turn that gets at it, and it's in the endgame. Ply 42 shows the principle end bolted on backwards: "your a2 pawn is isolated â€¦ next time you see an isolated pawn, ask yourself how can I use this to gain space and control the center." Your own isolated pawn is a liability; the actual problem was Rxc4 winning material.[0m[0m
[0m[0m
[1mEndgame (18 plies, best-covered, worst-fitted).[22m The coach imports middlegame reflexes wholesale. Ply 58: Kf2 was "a good attempt to secure your king" â€” in an endgame the king is a [3mfighting piece[23m, and "secure" is the wrong principle to reinforce. Plies 64, 70, 74, 78 are all "your piece is threatened, move it somewhere useful," which is not endgame technique. Ply 1002 says Kf3 gives "slightly better control over the d-file" â€” kings do not control files; that sentence is noise wearing technical clothes. Only plies 1000-1003 touch real endgame content (king support for a passed pawn, the open file), and 1000 is the single best turn in that phase. Also worth noting the ply IDs jump to 1000-1003, so the endgame sample is partly spliced from elsewhere rather than one continuous game.[0m[0m
[0m[0m
[1mShould it behave differently by phase? Yes, and this is the cheapest structural win.[22m Opening: name the scheme and the completion checklist (development, centre, king), suppress corrections below ~30cp. Middlegame: lead with the threat-checking procedure, and treat material as the consequence, not the lesson. Endgame: switch the principle vocabulary entirely â€” king activity over king safety, passed pawns, rook behind the pawn, cutting off, and [3malways[23m check for mate before anything else.[0m[0m
[0m[0m
Under-covered: the opening (10 plies, and no strategic content), and quiet/positional positions generally â€” essentially every turn in this transcript is driven by material or an immediate threat, so the coach is untested on positions where nothing is hanging.[0m[0m
[0m[0m
[38;5;252m[1m## VERDICT[0m[0m
[0m[0m
Not yet. The scaffold reliably produces two ends of a bridge, and maybe a quarter of the turns (6, 8, 56, 1000) are the coaching the standard describes â€” but ~14% of turns contain a move-level or board-level falsehood a student cannot detect, the endgame is taught with middlegame principles, mate goes unrecognised, and 44 turns of the same closing formula collapse into three lessons that would have been given regardless of the position.[0m[0m
[0m[0m
The single highest-leverage change is [1mcross-turn memory: a running student model that carries the recurring failure forward[22m (here: "never castled, king walked into fire for 30 plies"). It fixes the biggest teaching gap and the two loudest symptoms at once â€” it forces variety in the closing lesson because the coach must say something it hasn't said, and it converts 44 disconnected analyses into one lesson. Second, gate the "better move" comparison on a real eval delta so 0cp turns become clean praise instead of invented corrections; that's a small prompt/harness change and it removes six false turns immediately.
