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

**The Python we write does not use regexes, phrase lists or keyword matches to parse LLM
output**, unless the owner consents. That covers the gate, the counters, tests, scripts and
scratch scripts. Anchor code checks on text we composed or on the board.
- Covered: `verify.py` treating the word "capturing" as a capture claim to decide whether a reply
  is false.
- Not covered: the agent or the judge reading that reply, using python-chess when unsure whether
  Qc2 captures anything.

There are no exceptions an agent grants itself; if one looks justified, ask. Parsing a JSON reply
we asked a model for is not parsing prose. The owner's ruling, 2026-10-14. Three rules saying the same for
measures were already loaded when it was broken: a checker matching "is still available" was
added to `verify.py`, defended in its own comment because "the word is ours", and scratch scripts
did the same with no defence at all. `tests/test_model_text_matchers.py` freezes every
string-matching construct in code that handles model text (207 at freeze) and fails on any new
one or any changed pattern. **When it fails, stop and ask; never regenerate its list to pass.**
A commit that changes `tests/model_text_matchers.txt` says so in its first line. The 207 predate
the ruling and are recorded, not endorsed: do not extend them, and replacing them is the owner's
decision. Scratch scripts under `.kiro/tmp/` are not tracked, so the test cannot see them; the
rule still applies there.

**One measured exception: the live gate.** The word lists in `verify.py`'s gate stay, because no
exact check of free-form text is possible during a live game. They are best effort and are not
extended. The frontier judge's claim reading (`eval_coach_rejudge.py --claims`) measures them on
every sweep: false-accept (false replies passed) and false-reject (true replies blocked). First
measured 2026-10-15 on 82 v62 replies: false-accept 6-7 of 15-16, false-reject 1 of 66-67.
Considered not harmful, because a blocked reply is replaced by composed text that is true. The
owner's ruling, 2026-10-15.

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

## At each milestone: say where the bottleneck is

Asked for directly: after each milestone, state plainly whether the limit is now the ENGINE or
the COACH, and show the reasoning. Not a hedge — a verdict.

The test is mechanical. For each defect worth fixing, ask: **is the information the coach needs
present in the engine's output?**

- Present and unused -> coach. Fixable here, now.
- Absent or wrong -> engine. Prompt work cannot lift it, and per the division of labour we do
  not work around it.

Worked example, the phase/endgame defect (2026-09-14): phase we compute ourselves, passed pawns
the engine supplies, king activity we already have a detector for, opposition and
rook-behind-the-passer are rules geometry. All present, none used. Coach.

Counter-example on the same day: best-move agreement 4 of 18 and a 50-60cp residual under every
conversion. No prompt fixes that. Engine.

**Name the instrument's blind spot when you give the verdict.** The judge can read writing,
structure and lesson variety; it cannot check whether a move was really bad. So it will keep
reporting coach problems even when an engine problem is larger, because the engine's errors are
invisible to it. A verdict that does not mention this is overstating its own evidence — nine
unanimous reviews saying "coach" is partly an artefact of what the reviewer can see.

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
