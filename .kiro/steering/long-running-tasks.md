---
inclusion: always
---

# Long-Running Task Execution Strategy

When executing Python scripts or commands that take more than ~10 seconds (training,
evaluation, inference, benchmarks), follow the **sidecar wrapper** pattern instead of
polling with sleep loops.

## The Pattern

### 1. Use the Python monitor wrapper (`scripts/monitor.py`)

The monitor script:
- Launches the command as a subprocess
- Captures stdout/stderr to `<output_dir>/output.log`
- Writes structured JSON status to `<output_dir>/status.json`
- Detects hangs (output log not modified for N minutes) and kills the process
- Detects critical errors (Traceback, RuntimeError, MemoryError) in output
- Records exit code and timing

Usage:
```
python scripts/monitor.py <output_dir> <hang_timeout_minutes> <command...>
```

### 2. Launch with controlBashProcess (fire and forget)

```
controlBashProcess(action="start", command="RETRO_AI_ROM_DIR=... PYTHONPATH=... python scripts/monitor.py output/eval 3 python scripts/run_eval.py")
```

### 3. Check status by reading files (not polling)

When you need to check progress:
- `readFile("output/eval/status.json")` — structured JSON status
- `readFile("output/eval/output.log")` — full output (use start_line for tail)

Status JSON fields:
- `status`: RUNNING, COMPLETED, FAILED, HANG_DETECTED, LAUNCH_FAILED
- `exit_code`: process exit code (null while running, -9 on hang kill)
- `warning`: CRITICAL_ERROR_DETECTED if Traceback/RuntimeError found
- `started_at` / `finished_at`: timestamps

### 4. Tell the user what's running

After launching, tell the user:
- What command is running
- Where the logs are
- Expected duration
- Ask them to let you know when it's done, OR check back after the expected time

## Hang Timeout Guidelines

| Task Type | Expected Duration | Hang Timeout |
|-----------|------------------|--------------|
| Eval (1 episode) | ~60s | 3 min |
| Eval (10 episodes) | ~10 min | 5 min |
| Training (100k steps) | ~50 min | 5 min |
| Benchmark | ~30s | 2 min |
| Quick smoke test | ~5s | 1 min |

## Anti-Patterns (DO NOT)

- Do NOT use `sleep` in a loop to poll process output
- Do NOT send commands to a shell that has a running foreground process
- Do NOT use `executeBash` with very long timeouts (>120s) for training/eval
- Do NOT assume a process completed just because the terminal buffer stopped updating
- Do NOT run full episodes when a quick smoke test would validate the same thing

## Preferred Workflow

1. **Quick smoke test first** — run 50-100 steps to verify the code works (catches import errors, config bugs, shape mismatches)
2. **Full run via sidecar** — if smoke test passes, launch the real run with monitoring
3. **Read results from files** — check status.log and output files, don't poll
