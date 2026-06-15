# Authoring guide: `knowledge.yaml`

This is the author-facing reference for the pedagogy layer's curated
knowledge resource (`data/pedagogy/knowledge.yaml`). The resource is the
authority for **what is worth teaching** — the principles, named
patterns, and standard plans the coach and judge are grounded against.

The file is **data, not code**: adding, removing, or editing an entry
requires no code change (Req 1.1). The loader (`load_resource` in
`src/chess_coach/pedagogy/resource.py`) validates every entry fail-fast
and names the offending entry and field on any error.

## File shape

```yaml
version: 1
entries:
  - id: principle.center_control
    type: principle
    theme: center control
    focus: >
      Control the central squares ...
    how_to_apply: >
      Put a pawn or piece that fights for a central square ...
    levels: [beginner, intermediate, advanced]
    features: [phase:opening]
    citation: "Silman, How to Reassess Your Chess, ch. on the center"
```

- Top level is a mapping with `version: 1` and a non-empty `entries`
  list.
- Use YAML folded scalars (`>`) for the multi-line `focus` and
  `how_to_apply` text.

## Entry fields

| Field | Required | Notes |
|---|---|---|
| `id` | yes | Unique within the resource (duplicates are rejected). Convention: `<type>.<short_name>`, e.g. `pattern.back_rank`. |
| `type` | yes | Exactly one of `principle`, `pattern`, `plan`. |
| `theme` | yes | The named theme, e.g. `center control`, `back-rank weakness`. This is the "what to focus on" label. |
| `focus` | yes | Student-facing statement of *what to focus on* (one bridge end). Non-empty. |
| `how_to_apply` | yes | Student-facing statement of *how to apply it here* (the other bridge end). Non-empty. |
| `levels` | yes | Non-empty list; subset of `{beginner, intermediate, advanced}`. The levels the guidance is appropriate for. |
| `features` | for `principle` / `pattern` | Non-empty list of Position_Feature names (see below) that key selection. Not used by plans. |
| `eco_codes` | for `plan` | Non-empty list of ECO codes / opening contexts the plan applies to. Not used by principles/patterns. |
| `citation` | yes | Non-empty, *specific* source + locus (name the book and chapter/section). Ties guidance to instructional canon (Req 1.7). |
| `example` | optional | `{ fen: <FEN>, move: <UCI> }`. When present, the move must be **legal** and **engine-sound** in that position (verified by the annotation guard, Req 6.3/6.4). Only add one you are confident about. |

## Levels

The defined coaching levels (an entry must list one or more):

- `beginner`
- `intermediate`
- `advanced`

## Position_Feature names

`features` must use names from the closed, code-defined
`FEATURE_VOCAB` (finalized in `src/chess_coach/pedagogy/features.py`,
Task 2). Adding a *new* feature is a deliberate code change (a new
checkable extraction); authoring an entry only *uses* existing names.
The available names:

| Feature | Meaning |
|---|---|
| `phase:opening` | The position is in the opening phase. |
| `phase:middlegame` | The position is in the middlegame phase. |
| `phase:endgame` | The position is in the endgame phase. |
| `undefended_piece` | The side to move has an undefended / hanging piece. |
| `hanging_piece_opponent` | The opponent has an undefended / hanging piece. |
| `threat_present` | There is an active threat in the position. |
| `tactic:fork` | A fork motif is present. |
| `tactic:pin` | A pin motif is present. |
| `tactic:back_rank` | A back-rank mating motif is present. |
| `passed_pawn` | The side to move has a passed pawn. |
| `isolated_pawn` | The side to move has an isolated pawn. |
| `exposed_king` | The side to move's king is exposed (threshold-based). |
| `open_file` | There is an open file relevant to the position. |

An entry matches a position only when **every** feature it records is
present in that position (Req 2.1), so prefer the smallest set of
features that genuinely keys the guidance.

## ECO usage

`plan` entries are keyed by `eco_codes` instead of `features`. Use real
ECO codes (or opening names) that identify the opening context, e.g.:

- `C50` — Italian Game (Giuoco Piano / Pianissimo)
- `B20` — Sicilian Defence

The selector includes a plan whenever the position's looked-up ECO
context is among the plan's `eco_codes` (Req 2.2).

## Theme families (authoring taxonomy)

The five foundational opening principles are one slice of a broader,
canon-derived set. Span these families so the resource is not
over-anchored on the opening five — beginners improve most from safety
and tactics, not opening principles. (Copied from the design doc.)

| Theme family | Example entries | Primary source |
|---|---|---|
| Safety / board vision | don't hang pieces, count attackers vs defenders, "is my move safe?" | Heisman |
| Tactics / motifs | fork, pin, skewer, discovered attack, back-rank, double attack | Steps Method, Heisman |
| Opening principles | the five (center, development, king safety, protection, coordination) | classical canon |
| Pawn structure | passed / isolated / doubled pawns, pawn chains, weak squares | Silman, Nimzowitsch |
| Piece activity | outposts, open files, the bad bishop, improving the worst piece | Nimzowitsch, Silman |
| King safety (mid-game) | castle early, don't open lines to your own king, attacking the castled king | classical canon |
| Planning / imbalances | play to your imbalance, prophylaxis | Silman, Nimzowitsch |
| Endgame technique | K+R vs K, opposition, the square of the pawn, king activity | Steps Method, endgame canon |

A theme family is realized as one or more `Guidance_Entry` records at
the appropriate `levels`, keyed to the relevant `Position_Features` (or
`eco_codes` for plans).

## Source literature

Citations should draw on established chess pedagogy rather than invented
guidance (see the design doc's "Source literature" section for the full
bibliography): Heisman (board vision, "is my move safe?"), Chernev
(*Logical Chess: Move by Move*), Silman (*How to Reassess Your Chess*,
*Silman's Complete Endgame Course*), Nimzowitsch (*My System*), Seirawan
(*Winning Chess* series), and the Steps Method (Stappenmethode) for
leveling and sequencing.
