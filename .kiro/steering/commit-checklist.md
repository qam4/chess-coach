---
inclusion: auto
description: Chess-coach-specific build commands and rules
---

# Before committing

The same four commands CI runs, so that local green means CI green:

1. `pytest`
2. `mypy src/`
3. `ruff check src/ tests/`
4. `ruff format --check src/ tests/`

Locally we also lint and format `scripts/`, which CI does not. Keep doing it — the eval
harnesses live there and they are how every number in the ledger is produced.

If a change touches the clause pipeline, also run:

- `python scripts/snapshot_clauses.py --check docs/clause-snapshot.tsv`

# After pushing — not optional

**Check CI. "All tests pass locally" is not the same claim as "CI is green", and reporting the
first while implying the second is how CI stayed red for a week of pushes.**

```
gh run list --limit 3
```

- `success` → done.
- `in_progress` → say so, and check back rather than declaring the work finished.
- `failure` → `gh run view <id> --log-failed`, then fix it before moving on.

`.kiro/steering/ci-monitoring.md` has the fuller reference; this is the step that must happen
every time.

## Why this is a rule and not a nicety

The failure that put it here: `tests/test_clause_snapshot.py` discovered its input positions by
globbing `output/coach_review_*/transcript.json`, and `output/` is gitignored. It passed on the
dev machine and failed on every clean checkout, because the two were checking different inputs.
It went red the day it was added and nobody looked for a week.

**A test whose inputs come from gitignored local state protects nothing.** If a check reads
generated artefacts, either commit the inputs or derive them from something that is committed.

Same shape as three other defects found in the same week — the breadth sweep's leak counter,
the report card's fidelity count, and the fidelity checks themselves — all four being two copies
of one check handed different arguments. When you write a second caller of a verification
routine, pass it the same arguments as the first or explain in a comment why not.

# Code Quality Tools

- Formatter: `ruff format`
- Linter: `ruff check --fix`
- Type checker: `mypy` (strict mode)
- Test runner: `pytest`

# Project Rules

- All LLM models must be open source (Apache 2.0 preferred), no proprietary APIs
- All inference runs locally — no data leaves the user's machine
- Weight files and large binaries go in GitHub Releases, not git
