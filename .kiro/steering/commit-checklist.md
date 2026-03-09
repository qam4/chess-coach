---
inclusion: auto
description: Chess-coach-specific build commands and rules
---

# Build & Test Commands

1. Test: `pytest`
2. Type check: `mypy src/`
3. Format: `ruff format src/ tests/`
4. Lint: `ruff check src/ tests/ --fix`

# Code Quality Tools

- Formatter: `ruff format`
- Linter: `ruff check --fix`
- Type checker: `mypy` (strict mode)
- Test runner: `pytest`

# Project Rules

- All LLM models must be open source (Apache 2.0 preferred), no proprietary APIs
- All inference runs locally — no data leaves the user's machine
- Weight files and large binaries go in GitHub Releases, not git
