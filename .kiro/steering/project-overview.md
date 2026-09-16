---
inclusion: always
description: Project overview, architecture, module layout, and key design decisions
---

<!-- inclusion MUST stay `always` — `auto` defers loading until the request matches this
description, so the module layout was missing from sessions that did not name it.

Rewritten 2026-09-15 from the repo, because the previous version was wrong rather than
merely stale: it listed 8 modules against a 46-file package, described prompts.py as
"prompt templates" when it composes verified clauses, named a model and an endpoint that
had both changed, and omitted verify.py and pedagogy/ entirely. An orientation file that
is wrong is worse than none — it produces confident wrong assumptions. If you change the
package layout, change this. -->

# Chess Coach — Project Overview

A Python CLI and web app that turns chess engine output into coaching a human
can learn from. The engine says what is true about a position; this project
decides what is worth teaching and says it in plain English.

Repository: `qam4/chess-coach`. Engine: **Blunder** (separate repo, same owner).

## Division of labour with the engine

The load-bearing decision, and the one to check before adding a feature:

- **Blunder answers what is TRUE about the position** — evaluation, material,
  what is hanging, which move is better, best-move ideas, themes.
- **chess-coach answers what is worth TEACHING and how** — subject selection,
  lesson choice, phrasing, pedagogy.
- **Rules-level geometry is ours** to compute via `python-chess`: who attacks
  what, is this legal, is this piece pinned. Anything needing piece values or a
  judgement of worth belongs to the engine.

Do not work around an engine shortcoming. Drop the untrustworthy data, record it
in `engine_trust.py`, and fix it in Blunder.

## Commands

```
chess-coach explain <FEN> [--depth N] [--level L] [--template] [--socratic]
chess-coach check                 # engine + LLM connectivity
chess-coach serve [--port N]      # FastAPI play/coach web UI
```

## Pipeline

```
CLI / web  →  Coach (orchestrator)  →  Analyzer + Engine (UCI)
                     ↓
              pedagogy: select guidance entries matching this position
                     ↓
              prompts: COMPOSE the factual clauses, then build the prompt
                     ↓
              LLM provider (writes prose only)
                     ↓
              verify: check every claim against the board
                     ↓
              gating violation? → deterministic template instead
```

`Coach` entry points: `explain`, `evaluate_move`, `explain_engine_move`,
`play_move`, `check`, `new_game`.

Two invariants that most of the design follows from:

1. **The model writes sentences; it does not author facts.** Causal claims,
   piece names and squares are composed from the board in `prompts.py`. "No
   fact, no claim" — where nothing is verifiable, the clause is omitted rather
   than guessed.
2. **Fidelity is a gate, not a score.** There is no credit for being true, only
   a penalty for being false. `verify.generate_verified` re-checks the model's
   output against the board; a violation in `GATING_VIOLATION_KINDS` blocks the
   send and falls back to `coaching_templates`.

## Module layout

46 files under `src/chess_coach/`. The big ones, and why:

```
prompts.py            2719  clause composition + prompt building (the largest, and where
                            most coaching behaviour actually lives)
verify.py             1646  board-based verification of the model's claims
coach.py              1442  orchestrator
engine.py              963  UCI / Xboard protocol, subprocess + reader thread
models.py              939  ComparisonReport, PositionReport, PVLine, ...
coaching_phrases.py    697  deterministic phrase composition
coaching_templates.py  621  full deterministic coaching (the fallback path)
cli.py                 499  click CLI
engine_trust.py        492  what we believe from the engine, what we do not, and what
                            would change our mind
insights.py            351  the "why" behind an engine recommendation
error_diagnosis.py     259  what the student's move failed to do, by diffing attack maps
piece_history.py       218  per-game provenance: where each student piece came from
diagnosis.py           184  what the student failed to CHECK, and what actually mattered
analyzer.py            106  engine + python-chess bridge
openings.py            100  ECO / opening naming

pedagogy/    resource, selector, features, instantiate, inject, guard, theme_map
             — chooses which named principles to offer for THIS position
llm/         ollama, openai_compat, cli_provider, null (+ base protocol)
eval/        coach_review (the report card), judge, scoring, aggregate,
             benchmark, calibrate, profile, objective, move_feedback,
             game_coaching — the measurement harness; every ledger number
             comes from here
web/         server.py — FastAPI + SSE play UI
```

## Configuration

One tracked `config.yaml` (and `config.example.yaml`), three sections:

- `engine` — per-platform `path`, `protocol`, `depth` (currently 8), polyglot
  `book`, `play_elo` / `play_skill` for play mode only. Analysis always runs at
  full strength.
- `llm` — `provider` (`ollama` / `openai_compat`), `model`, `base_url`,
  `max_tokens`, `temperature`, `timeout`.
- `coaching` — `level`, `top_moves`, `guidance` (inject pedagogy entries),
  `guidance_max`, `template_only` (skip the LLM entirely).

Current values matter when reproducing a measurement: `model: qwen3:14b`,
`base_url: http://localhost:11435`, `guidance: on`, `depth: 8`.

## Constraints

- **Open-weight models only** (Apache 2.0 preferred), no proprietary APIs.
- **Inference runs on infrastructure the user controls.** `localhost:11435` is
  an ssh tunnel to an EC2 host running Ollama, not a local process — so "runs
  locally" is about ownership, not about the laptop.
- Python 3.11+, `mypy` strict, `ruff` at line-length 120.
- Weights and large binaries go in GitHub Releases, not git.

## Where the other rules live

Build and verification commands: `commit-checklist.md`. How to report a judge or
report-card run: `judge-reporting.md`. Project-specific working method:
`working-agreements.md`. The decision ledger is `docs/coach-report-card.md` and
open work is `BACKLOG.md` — read the backlog before proposing work.
