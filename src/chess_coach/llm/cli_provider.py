"""Generic CLI LLM provider — drive any "text in, text out" command.

Lets a command-line tool stand in as an `LLMProvider`. The motivating
case is using a headless agent CLI (e.g. Kiro CLI's `--no-interactive`
mode) as the Layer-2 *judge* endpoint when there's no hosted frontier
API to point at. But it is deliberately tool-agnostic: anything that
reads a prompt and prints a completion works — `kiro-cli`, `q chat`,
simonw's `llm`, `ollama run`, a shell script, etc.

Prompt delivery:
- If any token in ``command`` contains the literal ``{prompt}``, the
  prompt is substituted there (positional-arg style).
- Otherwise the prompt is piped to the process on **stdin** (the safe
  default; e.g. Kiro CLI accepts piped stdin in non-interactive mode).

The completion is the process's stdout. The judge's verdict parser
already tolerates banners / markdown / surrounding prose, so a chatty
CLI is fine as long as it prints the model's answer to stdout.
"""

from __future__ import annotations

import logging
import shutil
import subprocess

from chess_coach.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_PROMPT_PLACEHOLDER = "{prompt}"


class CliProvider(LLMProvider):
    """Run a configurable subprocess as an LLM backend."""

    def __init__(
        self,
        model: str = "cli",
        command: list[str] | None = None,
        base_url: str = "",
        timeout: float = 300.0,
        probe_timeout: float = 5.0,
        **kwargs: object,
    ):
        super().__init__(model=model, base_url=base_url, timeout=timeout, probe_timeout=probe_timeout, **kwargs)
        if not command:
            raise ValueError("CliProvider requires a non-empty 'command' (list of argv tokens)")
        self.command = list(command)

    def _argv(self, prompt: str) -> tuple[list[str], str | None]:
        """Return (argv, stdin_text). If the command template carries a
        {prompt} placeholder, substitute it and use no stdin; otherwise
        the prompt is sent on stdin."""
        if any(_PROMPT_PLACEHOLDER in tok for tok in self.command):
            argv = [tok.replace(_PROMPT_PLACEHOLDER, prompt) for tok in self.command]
            return argv, None
        return list(self.command), prompt

    def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7) -> str:
        # NOTE: max_tokens / temperature can't be mapped to an arbitrary CLI,
        # so they're ignored here. A judge wants temperature 0 — bake that
        # into the configured command if the tool supports it.
        argv, stdin_text = self._argv(prompt)
        logger.debug("CliProvider exec: %s (stdin=%s)", argv[0], stdin_text is not None)
        proc = subprocess.run(
            argv,
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:300]
            raise RuntimeError(f"CLI judge command failed (exit {proc.returncode}): {detail}")
        return proc.stdout

    def is_available(self) -> bool:
        """Cheap, no-exec check: is the executable resolvable on PATH?"""
        return shutil.which(self.command[0]) is not None

    def check_status(self) -> tuple[bool, bool]:
        found = self.is_available()
        return found, found
