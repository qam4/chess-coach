# Auditing the standard, not the coach (2026-08-13)

For fifteen changes the report-card score sat between 3.5 and 4.5 while real
defects were found and fixed. v26 scored 4.5 — the same as lever 2, a change we
**reverted** for having no measurable effect. The score has never told us whether
our work helped.

Two questions from the product owner reframed the problem:

1. Do we ask the judge *why* the score is low, and what would raise it?
2. Is the north star well enough defined to score against at all?

The answer to (1) is half-yes: the review task already asks for the single
highest-leverage change (that is where "cross-turn memory" came from) but never
asks why the number is not higher, and **defines only the endpoints of the scale**
— 0 is useless, 10 is the envisioned teacher, nothing in between. So the judge
re-invents the middle of the scale on every run. We diagnosed that exact failure
once before, in the guidance A/Bs: *"a judge re-anchoring 'what does 0.4 mean?'
every time is the dominant noise source"*, which is why change-detection moved to
pairwise. We fixed it there and never fixed it here.

The answer to (2) is the important one. The standard is a **composite** — the
teaching bridge, level fit, soundness, warmth, concision — measured by **one
number**. A gain in one part is averaged into a gestalt and disappears. Our own
data shows it: lesson concentration fell 82% -> 45% across the series, a large
real change, with no score movement; and in v25 the judge called a ~14%
factual-defect rate *"the single most disqualifying fact in the report"* and then
scored 4.3, in the same band as runs with fewer defects. Its words and its number
did not agree.

## Why we did not write the rubric ourselves

VISION forbids it, and the reasoning applies to the agent as much as the owner:

> The person who defines the product is the **student**, not a chess expert — and
> that is exactly *why* the product exists. If we knew what a great teacher would
> say, we wouldn't need the coach. So the standard for "good coaching" cannot be
> sourced from the product owner's chess judgment. It must come from outside.

A rubric decomposed from VISION.md would be circular: a high score would mean "we
built what we said we would build", not "this teaches well".

## Method

Two calls to `claude-opus-5`, deliberately **blind** to the project: no VISION, no
bridge framing, no transcript, no mention of what the coach currently does. Only
the medium was supplied — one shot per move, ~80 words, mid-game, no dialogue, a
~1200 student who knows the principles but freezes applying them, an engine
supplying ground truth.

Blindness applies to **this question only**. Deciding the yardstick is the one
place our context contaminates the answer, because agreement is the path of least
resistance. Everywhere else the judge should get *more* context than it does now —
see the action items.

Two different framings were used so that agreement means knowledge rather than
improvisation:

- **A** asked directly for scorable categories, anchors, weighting and sourcing.
- **B** asked what you would *look at* to tell a helpful product from a useless one
  and from an actively harmful one — same question by a different route.

Prompts and full answers: `docs/audit/blind-prompt-{a,b}.txt`,
`docs/audit/blind-derivation-{a,b}.md`.

## Result: the categories are stable

Both framings independently produced the same core, in the same rank order:

| Framing A | Framing B | Rank |
|---|---|---|
| Diagnosis — name the *thinking* failure, not the board fact | P1 — is the main clause about the position, or the student's decision? | #1 in both |
| Transfer Handle — a recognizable *cue* attached to a concrete check | (inside P1: "a process the student can actually execute") | joint #1 in A |
| Stream Behaviour — a thread across the game, revisited with increasing specificity | P4 — thematic accumulation, with callbacks | #2 in B |
| Load Discipline — one takeaway, nothing to hold in the head | P6 — assertions per paragraph | throughput in both |
| Stance — about the move, never the person | P2-harmful — unfalsifiable claims about the student | same sources in both |
| Fidelity — every claim true | P1-harmful / P2 | gate in both |
| Executability — could *this* student do it unaided | §4 — the best move when it is unreachable | present in both |

It also separated sourced claims from opinion without being asked twice: Diagnosis
and Transfer Handle are attributed to Heisman (*Novice Nook*, "Hope Chess"),
Rowson (*The Seven Deadly Chess Sins*), Whitehead's "inert ideas" and *How People
Learn* on conditionalized knowledge; Stance to Kluger & DeNisi (1996), Hattie &
Timperley (2007) and Mueller & Dweck (1998) — cited independently in **both**
framings; and Fidelity it labels its own extension with thin external support.

## Finding 1 — we do something the audit classes as harmful

Framing B puts this in the harmful tier, not the polish tier, and among the three
properties it *refuses to trade off*:

> Harmful: manufactures fault on genuinely good moves, including the student's
> best of the game — training them to distrust the instincts you most want
> reinforced.

Measured on v26: **21 of 44 turns had an eval drop under 20cp, and 10 of those
still stage a comparison.**

- ply 0, `Nf3` at 0cp: told `Nc3` "achieves even better development"
- ply 54, `Rae1+` at 0cp: told `Rge1+` "slightly refines rook placement"
- ply 1001, `Ra5+` at 6cp: told `Ra4` "slightly improves rook activity" (both rooks
  are already on the a-file)
- plies 12, 18, 24 close on "the best move was also your move, and the evaluation
  spread shows it was a key decision" — harness bookkeeping as pseudo-explanation

The report-card judge raised this twice as its cheap *secondary* pick. An
independent derivation that had never seen our transcript puts it in the harmful
tier. That settles the priority question.

## Finding 2 — the north star's end 1 is defined at a 6/10

This is a finding about VISION, not about the coach.

VISION defines end 1 of the bridge as *"a named theme/principle … the words the
student may already know in the abstract."* Framing A's anchor for that exact thing:

> **6** — Invokes a correct general principle but unconditionalized: "remember to
> count attackers and defenders." True, already known, no trigger for when to do it.
>
> **8** — Cue and action both present and both concrete: "Before you move any
> piece, check what it was guarding. Squares next to your king with two enemy
> pieces aiming at them are where this bites."

The same pattern holds for Diagnosis:

> **6** — stops at the board level: describes the error without naming the thinking
> failure behind it.

Composing verified board facts is exactly what our architecture does, deliberately
and by now rather well. It is also, per this rubric, the 6/10 anchor.

So the plateau has a candidate explanation that is not noise: **we have been
optimising against a definition that caps around 6, and scoring 4.5 on a scale
whose upper half we never aimed at.** Whether to change the definition is a
product decision, not an implementation one.

## Finding 3 — a correction to an earlier claim

I had assumed our closings were bare principles. They are not: **all 44 turns use
the `next time you see X, ask yourself Y` shape**, which is A's cue->check form,
with 30 distinct cues. Transfer Handle is structurally right already.

The weakness is cue *quality*. The most common cues are near-tautological — "next
time you see a capture" (5x), "an undefended piece" (5x), "a threatened piece"
(3x) — against A's 8/10 example, which names where the pattern bites.

## Two independent confirmations of the architecture

Cheap reassurance, worth recording because it was not asked for:

- *"Score [fidelity] programmatically against engine output; the rest needs a
  judge."* That is exactly the `verify.py` / frontier-judge split.
- Both framings say centipawn evaluations and deep variations do not belong in the
  output — both already suppressed.

## What the audit says not to do

Recorded because three of our best wins have been deletions:

- **Eval numbers.** Not information to a 1200; trains outcome-orientation.
- **Deep variations.** Beyond ~2 plies it asks for blind visualization the student
  does not have — and it looks like the most authoritative part of the message.
- **The engine's best move when it is unreachable.** The instructive target is the
  best move the student could have found *by a repeatable method*.
- **Opening names and book moves.** Games at 1200 are decided by undefended pieces,
  not move 8 of a mainline.
- **Comprehensiveness.** *"Listing all three things wrong with the move guarantees
  that none of them lands."*
- **Praise sandwiches.** At 80 words a compliment costs a fifth of the message, and
  buys the variety of feedback the evidence says does not work. Warmth in tone,
  yes; warmth as content, no.
- **Commenting on every move.** *"A coach that says something substantial forty
  times has said nothing forty times."* We coach every move with a drop over 50cp;
  the harness coaches all 44.

## Honest limits of this audit

- It is one frontier model, twice. Stability across two framings makes
  improvisation unlikely; it does not make the model a chess teacher.
- Roughly half the rubric is explicitly the model's own judgement rather than
  sourced, and it says so. The sourced half is the half that ranked highest.
- The citations are named but unverified at the page level — the same weakness as
  the pedagogy knowledge base, where 9 of 22 citations carry "(unverified locus)".
- This is measurement work. It has made the coach no better. The justification is
  that the previous instrument could not tell us whether anything worked, and this
  project has been here once before: "eval sensitivity and validity" was declared
  THE next investment, and switching to pairwise is what finally produced signal.
