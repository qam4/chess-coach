# Reporting judge runs

Applies to every run of a frontier judge / reviewer: the coach report card
(`scripts/eval_coach_review.py`), the architecture review, the pairwise A/Bs, and
any one-off question put to the judge.

## Always report back, in plain English

After a judge run, tell the product owner:

1. **Conclusions** — what the judge actually said, led by the answer, not the
   method. Name the specific plies or numbers it cited.
2. **Action items** — what follows from it, in priority order, with a rough sense
   of cost. Say which ones you propose to do next.
3. **What it means for earlier claims** — if the run contradicts something we
   previously concluded, say so plainly and retract it.

Do not bury this in a summary of what was executed. The conclusions are the
deliverable.

## Build the measure BEFORE you build the change

**Every time a judge recommends something, find the number before writing any code.**
Prose names a defect; it does not tell you which number moves. Find the number,
compute its current value, and write down what would count as success. If no
deterministic measure exists, say so and treat the change as unmeasurable — do not
assume the judge's framing is the measurable one.

A change was once aimed at "long, structurally identical paragraphs". Measured
first, the affected turns turned out to be no longer than average and to share
almost no wording with each other: the repetition was real but sat somewhere the
planned measures could not see. Built first, it would have shipped and then read
flat, and we would have learned nothing about either the change or the defect.

**Anchor the measure on the board, or on something we composed — never on the
model's phrasing.** Squares and move tokens checked against the board survive any
rewording. A list of phrases measures the examples someone happened to quote and
misses the forms nobody quoted; that has failed here more than once, and the
retired phrase list is kept in the code only as a warning against rebuilding it.

**Validate the measure on more than the run that produced the lead.** All stored
runs, every model, every opening, and the retroactive series across versions. A
measure that fires only where you noticed the defect is fitted to that game. A
measure that reads flat across the whole history, or saturates at 0% or 100%, is
not measuring anything. Both have happened, and both were caught by checking the
measure against the recorded arc before trusting it.

**State the coverage before spending the afternoon.** How many coached turns can
this change touch at all? Say the number up front, and say it when it is small.

## Rules that keep the reporting honest

- **Separate what the judge asserted from what we verified.** Its structural
  observations have been reliable; its claims about specific plies have not
  (claude-sonnet-4.6 was wrong on 5 of 5 checked; opus-5 better but not exempt).
  Treat per-ply claims as leads to check against the board, and say which ones you
  checked.
- **Report the score, but do not lead with it.** It sat at 3.5-4.5 across fifteen
  changes, including a lever we reverted as ineffective, so it is a weak
  instrument. The written critique is the useful output.
- **Distinguish "no effect" from "not measured."** If a change is prompt-side only
  and the output has not been re-judged, say so.
- **Log it.** Every finding gets a ledger row in `docs/coach-report-card.md` (judge
  flagged / what we changed / outcome / verdict) and the follow-ups go to
  `BACKLOG.md`. The loop is: judge recommends -> we fix one thing -> we measure ->
  the row records whether it worked, including when it did not.
