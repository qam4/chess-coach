---
inclusion: manual
description: How to monitor GitHub Actions CI after pushing
---

# CI Monitoring

After `git push`, check CI status with `gh`:

```bash
# Quick status of latest run
gh run list --limit 3

# Watch a specific run (get run ID from above)
gh run view <run-id>

# View failed job logs
gh run view <run-id> --log-failed
```

## After pushing

1. Run `gh run list --limit 3` to find the triggered workflow run
2. If status is `completed` + `success`: done
3. If status is `in_progress`: tell the user CI is running and they can check back
4. If status is `completed` + `failure`: run `gh run view <id> --log-failed` and report the errors

## CI workflow

The CI runs on every push to `main` and on PRs. It tests:
- pytest (all tests)
- mypy src/ (strict type checking)
- ruff check (linting)
- ruff format --check (formatting)

Matrix: Python 3.11 + 3.12 on ubuntu-latest.
