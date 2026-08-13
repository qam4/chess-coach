[38;5;141m> [0mI deliberately did not read this repo's [38;5;10mdocs/pedagogy.md[0m before answering, so what follows is uncontaminated by your existing framing. Happy to reconcile the two afterwards.[0m[0m
[0m[0m
A note on the scenario used in the anchors, so both graders calibrate on the same case:[0m[0m
[0m[0m
[38;5;244mâ”‚ **Scenario S.** Student is White, move 14. f2 is attacked twice (queen on b6 down the b6â€“f2 diagonal, knight on g4) and defended twice (king on g1, rook on f1). The student plays 14.Rfd1 â€” a natural "rooks to the centre" move â€” removing a defender. ...Nxf2 now wins material. Engine: +0.2 â†’ âˆ’1.6.[0m[0m
[0m[0m
â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
[0m[0m
[0m[0m
[38;5;252m[1m## 1. Categories[0m[0m
[0m[0m
[1m1. Fidelity[22m â€” Every factual claim about the position (what is attacked, what is hanging, what the threat wins, what the line is) is true.[0m[0m
Why here: an 80-word one-shot with no follow-up is unfalsifiable by the student. A confidently wrong claim doesn't just fail to teach, it installs a false pattern that a 1200 will apply for months. Specific and memorable is exactly what makes a hallucination expensive.[0m[0m
[0m[0m
[1m2. Diagnosis[22m â€” Does it talk about the thing that actually decided this move, and does it name the [3mcause[23m of the error rather than only its existence?[0m[0m
Why here: at 1200 the causes are a short list (didn't look at the opponent's reply, didn't count attackers and defenders, moved a defender, grabbed material, played a plan while a tactic was live). One move gives you one slot; spending it on the third-most-important feature is a wasted slot even if everything said is true.[0m[0m
[0m[0m
[1m3. Transfer Handle[22m â€” Does the feedback attach a [3mrecognizable condition[23m to a [3mconcrete action[23m, so the lesson can fire again in a position that doesn't look like this one?[0m[0m
Why here: this is the whole diagnosis of your student. They already know "count the defenders" as a sentence. What they lack is the index â€” the "when." Feedback shaped as [3mcue â†’ check[23m is the only form that touches this; feedback shaped as [3mthis position â†’ that move[23m cannot.[0m[0m
[0m[0m
[1m4. Executability[22m â€” Could this specific student carry out the advice unaided, in-game, within their calculation ability and time?[0m[0m
Why here: the engine's best move often rests on a tactic or an evaluation beyond a 1200. Advice they cannot execute reads as coaching but functions as noise, and repeated exposure teaches them that coaching is something you nod at rather than do.[0m[0m
[0m[0m
[1m5. Load Discipline[22m â€” One takeaway, expressed in what's visible on the board, without variation trees the student must hold in their head.[0m[0m
Why here: the student is mid-game, already at working-memory capacity. Every extra idea competes with the one that matters, and any line beyond a move or two must be visualized blind â€” which is precisely a skill they don't have.[0m[0m
[0m[0m
[1m6. Attention-First Order[22m â€” Does it point the student's eyes at the cue [3mbefore[23m delivering the conclusion (and then still deliver it)?[0m[0m
Why here: it's the only way to get any generative work out of a medium with no dialogue. "Look at f2 â€” count attackers and defenders" gives them a two-second chance to see it themselves; the answer arrives in the next clause regardless, so nothing is lost if they don't.[0m[0m
[0m[0m
[1m7. Stance[22m â€” Feedback is about the move and the process, never about the student as a person; honest about the size of the error without amplifying it or softening it into a lie.[0m[0m
Why here: two-fold. Person-level feedback measurably degrades subsequent performance, and this student has 25 more moves to play â€” a demoralized student wastes every remaining message. Equally, false praise on a blunder destroys the signal value of praise everywhere else.[0m[0m
[0m[0m
[1m8. Stream Behaviour[22m [3m(scored per game, not per move)[23m â€” Across a whole game: does the feedback build a thread, revisit the student's actual recurring weakness with increasing specificity, stay quiet when there's nothing worth saying, and avoid repeating itself verbatim?[0m[0m
Why here: the unit of instruction is the game, not the move. Forty independently-decent comments on forty different themes teach nothing, and a coach that comments on every move at full length stops being read by move 15.[0m[0m
[0m[0m
â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
[0m[0m
[0m[0m
[38;5;252m[1m## 2. Anchors[0m[0m
[0m[0m
[1mFidelity[22m[0m[0m
- 4 â€” Contains one plausible-sounding falsehood: "...Nxf2 wins your queen" (it wins a pawn and the exchange), or invents a threat that isn't there, or names a move that isn't legal.[0m[0m
- 6 â€” All material claims true; one loose imprecision that doesn't mislead ("your opponent's knight jumps into g4" when it had been there three moves).[0m[0m
- 8 â€” Every claim checks out against engine output: the squares, the counts, the piece names, the size of the loss, the recommended move.[0m[0m
[0m[0m
[1mDiagnosis[22m[0m[0m
- 4 â€” Discusses a real but secondary feature (the d-file, pawn structure, development count) while the game is being decided on f2. Also 4: "this was a mistake, best was 14.Bd4" with no account of what went wrong.[0m[0m
- 6 â€” Correctly identifies that f2 is the issue and that the rook move caused it, but stops at the board level: describes the error without naming the thinking failure behind it.[0m[0m
- 8 â€” Names the specific process failure â€” the rook was doing a job and was moved anyway â€” and that failure is genuinely the one this move exhibits.[0m[0m
[0m[0m
[1mTransfer Handle[22m[0m[0m
- 4 â€” Nothing reusable: entirely about this position and this move. Or a slogan with no condition attached ("always be careful of tactics").[0m[0m
- 6 â€” Invokes a correct general principle but unconditionalized: "remember to count attackers and defenders." True, already known, no trigger for when to do it.[0m[0m
- 8 â€” Cue and action both present and both concrete: "Before you move any piece, check what it was guarding. Squares next to your king with two enemy pieces aiming at them are where this bites."[0m[0m
[0m[0m
[1mExecutability[22m[0m[0m
- 4 â€” Requires strength the student lacks: assessing the resulting endgame, prophylaxis against a plan not yet begun, "improve your worst-placed piece," or a refutation that only works because of a 5-move tactic.[0m[0m
- 6 â€” Doable but expensive: a check the student can perform but not sustain every move ("count attackers and defenders on every square near your king").[0m[0m
- 8 â€” A single check a 1200 can complete in a few seconds, unprompted, from what's on the board.[0m[0m
[0m[0m
[1mLoad Discipline[22m[0m[0m
- 4 â€” Two or more ideas of comparable weight, or a branching variation, or a line requiring blind visualization past move two. Or well over ~120 words.[0m[0m
- 6 â€” One main idea plus one aside, or one three-move line, or ~100 words. Survivable, diluted.[0m[0m
- 8 â€” Exactly one takeaway, â‰ˆ80 words, at most a couple of move references, everything it points at is visible on the current board.[0m[0m
[0m[0m
[1mAttention-First Order[22m[0m[0m
- 4 â€” Bare verdict with no cue ("14.Rfd1 loses a pawn; 14.Bd4 was correct"). Also 4: a pure question with no answer supplied â€” in a medium with no follow-up, that's a coin flip on comprehension.[0m[0m
- 6 â€” Verdict first, then the explanation. Complete and informative, but the student is told rather than given a look.[0m[0m
- 8 â€” Directs attention to the cue in the opening clause, then answers within the same message: "Look at f2 before anything else. Two attackers, and you just moved one of its two defenders."[0m[0m
[0m[0m
[1mStance[22m[0m[0m
- 4 â€” Person-level attribution ("careless again," "you keep making this mistake"), or catastrophizing ("this loses the game"), or false comfort ("nice developing move!" on Scenario S).[0m[0m
- 6 â€” Mild self-level framing or a compliment sandwich: accurate content wrapped in "Good instinct! ... but ... you're improving." Harmless, costs 15 of 80 words.[0m[0m
- 8 â€” Move and process only, no evaluation of the person, the cost stated plainly and once ("this drops a pawn and the exchange"), no padding in either direction.[0m[0m
[0m[0m
[1mStream Behaviour[22m [3m(per game)[23m[0m[0m
- 4 â€” Near-verbatim repetition of the same advice, or a brand-new unrelated theme every move with no thread, or full-length commentary on all forty moves.[0m[0m
- 6 â€” A recognizable thread plus several unrelated one-offs; quiet moves still get a comment but a short one.[0m[0m
- 8 â€” At most two or three themes per game; the student's dominant weakness is revisited two or three times at increasing specificity; unremarkable moves get a clause or nothing; no message duplicates an earlier one.[0m[0m
[0m[0m
â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
[0m[0m
[0m[0m
[38;5;252m[1m## 3. Weighting[0m[0m
[0m[0m
Two hard gates. Both cap the score for the whole message regardless of everything else, because both do net damage â€” the message would have been better unsent.[0m[0m
[0m[0m
- **Fidelity â‰¤ 4** â†’ total capped at 2/10. A false specific claim is worse than silence.[0m[0m
- **Stance â‰¤ 4 in the person-attribution or false-praise varieties** â†’ total capped at 3/10. It corrupts the remaining 25 messages of the game.[0m[0m
[0m[0m
One soft gate:[0m[0m
[0m[0m
- **Diagnosis â‰¤ 3** (talked about the wrong thing) â†’ total capped at 4/10. Elegant teaching of an irrelevance trains the student to attend to the wrong feature of a position, which is the opposite of the goal.[0m[0m
[0m[0m
Otherwise, for the survivors:[0m[0m
[0m[0m
| Category | Weight |[0m[0m
|---|---|[0m[0m
| Diagnosis | 25 |[0m[0m
| Transfer Handle | 25 |[0m[0m
| Executability | 15 |[0m[0m
| Load Discipline | 10 |[0m[0m
| Stance | 10 |[0m[0m
| Stream Behaviour | 10 |[0m[0m
| Attention-First Order | 5 |[0m[0m
| Fidelity | gate only |[0m[0m
[0m[0m
Diagnosis and Transfer Handle carry half the weight between them deliberately: they are the two that address why a 1200 who knows the principles still can't use them. Everything else is hygiene â€” necessary, cheap to get right, and not where the teaching lives. Attention-First Order is weighted low despite good experimental support, because its effect size in a one-shot medium is genuinely modest.[0m[0m
[0m[0m
Fidelity as gate-only rather than weighted is a considered choice: there is no credit for being true, only a penalty for being false. Score it programmatically against engine output; the rest needs a judge.[0m[0m
[0m[0m
â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
[0m[0m
[0m[0m
[38;5;252m[1m## 4. Sourcing[0m[0m
[0m[0m
| Category | Basis |[0m[0m
|---|---|[0m[0m
| Fidelity | [1mMine[22m, with thin external support. The general finding that inaccurate or misdirected feedback can reduce performance comes from Kluger & DeNisi's 1996 feedback meta-analysis, but the specific argument â€” that a false claim is worse than silence because it installs a retrievable wrong pattern â€” is my extension. |[0m[0m
| Diagnosis | [1mSourced.[22m Dan Heisman's [3mNovice Nook[23m / [3mA Guide to Chess Improvement[23m is built on the claim that at this level the error is in the thinking process, not the move; his "Hope Chess" (moving without checking the opponent's forcing replies) is exactly a cause-level diagnosis. Jonathan Rowson's [3mThe Seven Deadly Chess Sins[23m supplies a vocabulary of causes rather than mistakes. Hattie & Timperley's 2007 feedback review independently finds process-level feedback outperforms task-level ("right/wrong") feedback for transfer. |[0m[0m
| Transfer Handle | [1mSourced,[22m and the best-supported item here. Whitehead's "inert ideas" (*The Aims of Education*, 1929) names the failure mode; [3mHow People Learn[23m (Bransford, Brown & Cocking) makes "conditionalized knowledge" â€” knowledge indexed to the conditions of its use â€” a defining property of expertise. Chess-specific: de la Maza's [3mRapid Chess Improvement[23m CCT scan (checks, captures, threats) is a pure trigger procedure rather than a principle, and Heisman's checklists are the same move. The cueâ†’check [3msentence format[23m is my own operationalization. |[0m[0m
| Executability | [1mMixed.[22m Vygotsky's zone of proximal development is the standard warrant and is genuinely apt, though it's invoked loosely everywhere; Silman (*How to Reassess Your Chess*) insists on level-appropriate plans over engine-correct ones. Applying it as a per-move scoring axis is mine. |[0m[0m
| Load Discipline | [1mSourced.[22m Sweller's cognitive load theory, specifically extraneous load and the split-attention effect, plus the chunking work of de Groot (*Thought and Choice in Chess*) and Chase & Simon establishing that a 1200 has neither the chunks nor the visualization to carry a variation. The ~80-word/one-idea operationalization is mine. |[0m[0m
| Attention-First Order | [1mSourced for the mechanism, mine for the application.[22m Generation and testing effects (Roediger & Karpicke, 2006) and Bjork's desirable difficulties support cue-before-answer. The specific conclusion â€” that a one-shot medium should pose [3mand[23m answer, never pose alone â€” is my judgement about your constraints. |[0m[0m
| Stance | [1mSourced,[22m strongly. Kluger & DeNisi (1996): feedback drawing attention to the self degrades performance. Hattie & Timperley (2007): self-level feedback is the least effective of their four levels. Mueller & Dweck (1998): person-directed praise undermines persistence after setbacks. The "honest about size, no amplification" half is mine. |[0m[0m
| Stream Behaviour | [1mMixed.[22m Revisiting the same weakness at intervals rests on the spacing effect (Ebbinghaus; Cepeda et al.'s 2006 meta-analysis). Escalating specificity, the two-to-three-theme cap, and the value of near-silence are my judgement. |[0m[0m
[0m[0m
â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
[0m[0m
[0m[0m
[38;5;252m[1m## 5. What doesn't matter â€” or hurts[0m[0m
[0m[0m
[1mEngine evaluations in centipawns or pawn units.[22m "âˆ’1.6" is not information to a 1200; it's a number they'll learn to fear. It also trains outcome-orientation over process, which is the exact opposite of the fix.[0m[0m
[0m[0m
[1mThe engine's best move, when it's unreachable.[22m "14.Nxe6!! and the point is that after ...fxe6 15.Qh5+..." is not teaching, it's a demonstration. The instructive target is the best move the student could have found [3mby a repeatable method[23m â€” often the second or third engine choice, and sometimes the same move they played, reached for the right reason.[0m[0m
[0m[0m
[1mVariations and lines.[22m Beyond about two plies you are asking for blind visualization they do not have. Split attention, no transfer, and it looks like the most authoritative part of the message.[0m[0m
[0m[0m
[1mOpening names, book moves, and novelty callouts.[22m Games at 1200 are decided by undefended pieces and unchecked replies, not by move 8 of a mainline. This is close to unanimous across the instructional literature, Heisman and Silman included.[0m[0m
[0m[0m
[1mComprehensiveness.[22m Listing all three things wrong with the move guarantees that none of them lands. Coverage is not a virtue here; it's the primary failure mode of automated coaching.[0m[0m
[0m[0m
[1mAdvanced positional vocabulary.[22m Prophylaxis, minority attacks, "improve your worst-placed piece," long-term bishop-pair compensation. All correct, all above the ceiling, and irrelevant to a student who will lose to a fork on move 22 whatever the pawn structure is.[0m[0m
[0m[0m
[1mPraise sandwiches, encouragement decoration, persona and humour.[22m At 80 words a compliment costs a fifth of the message, and the specific thing it buys â€” self-level positive feedback â€” is the variety the evidence says doesn't work. Warmth in tone, yes; warmth as content, no.[0m[0m
[0m[0m
[1mHedging.[22m "This might not be best, but..." You have engine ground truth. Hedging spends words and forfeits the authority that makes the instruction stick.[0m[0m
[0m[0m
[1mCommenting on every move.[22m The scarcest resource in this medium is the student's attention across a whole game, not words within a message. A coach that says something substantial forty times has said nothing forty times. Restraint on quiet moves is a feature, and worth scoring for (it sits inside Diagnosis and Stream Behaviour) â€” but it will not emerge unless you stop rewarding coverage.[0m[0m
[0m[0m
[1mAnything about the game's result.[22m "You're winning â€” convert carefully" adds pressure, shifts attention to outcome, and is not teachable content.
