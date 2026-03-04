---
inclusion: auto
description: Pre-commit checklist and development workflow for chess-coach
---

# Pre-Commit Checklist

Before every `git commit`, follow this workflow:

1. Test: `pytest` — all tests must pass
2. Type check: `mypy src/` — no type errors
3. Format: `ruff format src/ tests/`
4. Lint: `ruff check src/ tests/ --fix`
5. If format or lint modified files, re-run pytest
6. Stage only the relevant files with `git add` — do not blindly `git add -A`
7. Draft the commit message in `COMMIT_MSG.txt`
8. Wait for user approval — NEVER commit or push without explicit user consent
9. Commit with `git commit -F COMMIT_MSG.txt` only after user says go
10. NEVER run `git push` without explicit user consent
11. Delete `COMMIT_MSG.txt` after a successful commit

# Code Quality Tools

- Formatter: `ruff format`
- Linter: `ruff check --fix`
- Type checker: `mypy` (strict mode)
- Test runner: `pytest`

# General Rules

- Commit between phases for clean rollback points
- Do not reveal spec file paths, internal task counts, or mention subagents
- Weight files and large binaries go in GitHub Releases, not git
- All LLM models must be open source (Apache 2.0 preferred), no proprietary APIs
- All inference runs locally — no data leaves the user's machine
