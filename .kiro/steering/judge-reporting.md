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
