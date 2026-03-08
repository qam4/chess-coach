#!/usr/bin/env python3
"""Sidecar monitor for long-running tasks.

Usage:
    python scripts/monitor.py <output_dir> <hang_timeout_min> <command...>

Example:
    python scripts/monitor.py output/eval 3 python scripts/run_eval.py

Writes:
    <output_dir>/status.json  — structured status (machine-readable)
    <output_dir>/output.log   — stdout+stderr from the command
"""

import json
import os
import subprocess
import sys
import time


def write_status(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def main():
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <output_dir> <hang_timeout_min> <command...>")
        sys.exit(1)

    out_dir = sys.argv[1]
    hang_timeout = int(sys.argv[2]) * 60  # convert to seconds
    cmd = sys.argv[3:]

    os.makedirs(out_dir, exist_ok=True)
    status_path = os.path.join(out_dir, "status.json")
    output_path = os.path.join(out_dir, "output.log")

    status = {
        "started_at": time.time(),
        "command": " ".join(cmd),
        "status": "RUNNING",
        "pid": None,
        "exit_code": None,
        "finished_at": None,
        "warning": None,
    }

    with open(output_path, "w") as log_file:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=os.environ.copy(),
            )
            status["pid"] = proc.pid
            write_status(status_path, status)

            # Monitor loop
            while proc.poll() is None:
                time.sleep(10)
                # Check for hang: output.log not modified recently
                try:
                    mtime = os.path.getmtime(output_path)
                    stale = time.time() - mtime
                    if stale > hang_timeout:
                        status["status"] = "HANG_DETECTED"
                        status["stale_seconds"] = stale
                        proc.kill()
                        proc.wait()
                        status["exit_code"] = -9
                        status["finished_at"] = time.time()
                        write_status(status_path, status)
                        sys.exit(1)
                except OSError:
                    pass

            # Process finished naturally
            status["exit_code"] = proc.returncode
            status["status"] = "COMPLETED" if proc.returncode == 0 else "FAILED"
            status["finished_at"] = time.time()

            # Check for known errors in output
            try:
                with open(output_path) as f:
                    content = f.read()
                if any(kw in content for kw in ("Traceback", "RuntimeError", "MemoryError")):
                    status["warning"] = "CRITICAL_ERROR_DETECTED"
            except OSError:
                pass

            write_status(status_path, status)

        except Exception as e:
            status["status"] = "LAUNCH_FAILED"
            status["warning"] = str(e)
            status["finished_at"] = time.time()
            write_status(status_path, status)
            sys.exit(1)


if __name__ == "__main__":
    main()
