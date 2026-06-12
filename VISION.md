# chess-coach — North Star

## Mission

**chess-coach is a teacher for a player who wants to get better — not a
position analyst that happens to use words.** When the student doesn't
know what to do, it tells them *what to focus on* and *a concrete,
sound way to do it here* — at their level — and over time it tracks
their progress and adapts.

## The moment we serve

The product exists for one lived experience (the owner's own, and the
target user's):

> "I know the opening principles, so I can make a few moves to get
> started. But at some point I don't know what to do. I want a coach
> to say: keep defending the center — and here's a good way to do it."

That moment — *principles in hand, but stuck on how to apply them to
the board in front of me* — is the whole job.

## Why "good coaching" was hard to pin down

The person who defines the product is the **student**, not a chess
expert — and that is exactly *why* the product exists. If we knew what
a great teacher would say, we wouldn't need the coach. So the standard
for "good coaching" cannot be sourced from the product owner's chess
judgment. It must come from outside (see "How we know it's working").

This is not a weakness in the vision. It is the vision: **bring expert
teaching to someone who can't yet recognize it themselves.**

## The teaching unit

Every piece of coaching should be a *bridge* with two ends:

1. **What to focus on** — a named theme/principle (center control,
   development, king safety, piece protection, piece coordination,
   a tactic, an endgame technique). The words the student may already
   know in the abstract.
2. **A concrete, sound way to do it *here*** — the specific move or
   plan in *this* position, at the student's level.

The gap the student feels is the bridge between these two. Coaching is
that bridge. Pure analysis ("Nf3 is best, +0.4") is only the second
end; a lecture on principles is only the first. Neither alone is
teaching.

## How we ground it

The LLM is the teaching *voice*. It can't be trusted to supply the
facts alone (small models hallucinate; even large ones misread
boards). So we ground it with **scaffolds**, and we can add more over
time:

- **The engine** grounds the "concrete way to do it" — is the
  suggested action actually sound? (Today: Blunder's coaching
  protocol.)
- **A pedagogy / curriculum layer** grounds the "what to focus on" —
  the principles, named patterns, standard plans, and how to teach
  them. (Future: a curated knowledge resource, e.g. principles keyed
  to position features and openings keyed to ECO codes.)

The engine answers *what is true about this position*. The pedagogy
layer answers *what is worth teaching and how*. The LLM synthesizes
both into something the student can act on.

## How we know it's working

"Good coaching" is **not** judged by the product owner's read of the
prose — they're the student, not the expert. It is anchored to
external authority, in increasing order of truth:

1. **The engine** — the concrete advice must be sound (objective,
   automatable; this is the eval harness's Layer 1).
2. **Chess authority** — a strong player, established instructional
   canon, or a frontier model as a proxy expert judges whether the
   teaching is correct and well-pitched (the eval harness's Layer 2
   judge; calibrated by someone who actually knows chess — *not* the
   owner).
3. **Student outcomes (true north)** — ultimately, a teacher succeeds
   when the *student improves*: fewer hung pieces after we taught
   piece protection, better moves over time, the stuck feeling fading.
   This is measurable without anyone grading prose, and it is the
   honest definition of the product working.

## The arc this unlocks

Customer experience is the anchor; everything compounds from it:

1. **Bridge** — connect a principle to a concrete, sound action in the
   current position, at the student's stated level. *(Where we are.)*
2. **Progress tracking** — a per-dimension picture of the student's
   understanding (material awareness, king safety, endgames, …) built
   from how their moves line up with engine recommendations in
   positions where each dimension matters.
3. **Level-adaptive teaching** — the coach teaches the right thing at
   the right time for *this* student, targeting their weakest
   dimensions, advancing as they demonstrate understanding.

Step 2 needs step 1 to be trustworthy; step 3 needs step 2's profile.

## What chess-coach is NOT

- **Not a position analyst / engine GUI.** Lichess and Stockfish
  already report evals and best moves. We translate, teach, and bridge.
- **Not a puzzle grinder.** The goal is intuition and fundamentals
  that transfer to real games, not "mate in 3" drills.
- **Not graded by the owner's chess taste.** Quality comes from the
  engine, chess authority, and student outcomes.

## How today's pieces serve the vision

- **LLM-primary coaching** (shipped) — the teaching voice, with
  templates as an offline fallback.
- **The engine + coaching protocol** — the soundness scaffold (end 2
  of the bridge).
- **The eval harness** (`docs/evaluation.md`) — measures whether the
  voice is *truthful* (Layer 1) and *good teaching* (Layer 2 judge),
  with calibration (Layer 3) to keep the judge honest. Note:
  `rubric.v1` is analyst-era (position triage); a teaching-oriented
  `rubric.v2` and the pedagogy layer are the next steps toward this
  vision (tracked in BACKLOG.md).
- **A future pedagogy/curriculum layer** — the missing scaffold for
  end 1 of the bridge (what to teach), and the standard the teaching
  eval grades against.

---

*This is the north star. When a proposal comes up, the test is: does
it move a stuck student closer to knowing what to do and getting
better? If a direction doesn't serve that, it goes to IDEAS.md or
BACKLOG.md, not into the build.*
