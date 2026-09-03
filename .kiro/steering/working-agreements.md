# Working agreements

How the product owner has asked to be worked with. Distinct from `docs/coach-report-card.md`,
which records what we decided about the *coach*; this records how to conduct the work. It
exists because these instructions were given repeatedly in one session and forgotten
repeatedly inside it — the ledger held the decisions, nothing held the method.

## Reporting

**Answer the question that was asked, then stop.** "Did the fix work?" wants yes or no first.
Analysis follows only if it changes what to do next.

**Plain English.** No jargon, no restating the method before the result. If a sentence would
make the owner ask "what does that mean", cut it.

**Caveats: at most one, and only if it changes the decision.** Stacking three qualifiers on a
result is a way of avoiding a conclusion. "You are killing me with those caveats" was said
after the third.

**Do not narrate your own errors as if they were findings.** A miscounted FEN in a test is not
a project insight. Fix it and move on. Mistakes belong in a report only when they changed a
conclusion the owner is relying on.

**Never report a number without saying how it was measured**, and separate what a judge
asserted from what was verified against the board.

## Measurement

**Do not accept or reject a change on the judge's 0-10 score.** It returned 5.5 / 5.0 / 2.0 on
byte-identical input, and four of seven category scores differ on a re-run of the same
transcript. "Worse on five of seven dimensions" is what noise looks like, not evidence.
Use the deterministic counters (`scripts/eval_hard_metrics.py`) and the validated pairwise
harness (`scripts/eval_transcript_pairwise.py`, 94% self-agreement). Keep the judge's *prose*:
it has found the best defects.

**Measure coverage BEFORE building, not after.** Two changes shipped at coverage too low to
register (piece history 2/18 turns, centre control 0/36). If a change cannot affect at least
half the coached turns, say so before spending the afternoon.

**Never conclude from one game.** The report card defaults to seed 7; pass `-Seed` and use
several. Every number in the ledger up to v43 rests on one game, which the owner raised as a
concern before it was acted on.

**Verify a position before writing it into a test.** Four test FENs in one session named a
piece that was not there or a move that was illegal.

## Choosing what to do

**Read `BACKLOG.md` before proposing work, not just after.** Sixteen rounds of numbered lists
accumulated there, and the same items recur — cross-turn memory six times, the two text parsers
five, "the composer needs the student's failure cause" twice before it was built. The failure
mode is not discovery, it is follow-through: run a review, write down the same conclusion, do
something adjacent, repeat.

**Order the backlog by impact, never by cost.** Cost decides how to do an item, not whether it
comes first. Under cheapest-first, a session opened on a cosmetic fix while two confirmed
falsehoods stayed in the coach's mouth.

**Finish the thing before starting the next thing.** "Agreeing to do something and finding a
way not to do it" was the owner's description of the failure. A judge suggestion is not a
reason to abandon an agreed plan mid-way.

**No process artifacts unless asked.** A spec, a summary document, another markdown file — if
its value cannot be stated in one line, it is not worth the owner's attention. A test that
fails when behaviour changes beats a document describing the behaviour.

## Division of labour with Blunder

The engine answers *what is true about this position* — evaluation, material, what is hanging,
which move is better. chess-coach answers *what is worth teaching and how*. Rules-level
geometry via python-chess (who attacks what, is this legal, is this piece pinned) is ours to
compute; anything needing piece values or an assessment of worth is the engine's.

**Do not work around a Blunder shortcoming.** Drop untrustworthy engine data, record it in
`engine_trust`, and fix it in Blunder. A board-derived material counter was written here once
and removed for this reason.
