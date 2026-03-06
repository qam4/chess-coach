"""Ollama LLM provider — local inference via Ollama's REST API."""

from __future__ import annotations

import logging
import time

import httpx

from chess_coach.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    """Connects to a local Ollama instance.

    Ollama serves models at http://localhost:11434 by default.
    Install: https://ollama.com/download
    Pull a model: ollama pull qwen3:8b
    """

    def __init__(
        self,
        model: str = "qwen3:8b",
        base_url: str = "http://localhost:11434",
        timeout: float = 300.0,
        **kwargs: object,
    ):
        super().__init__(model=model, base_url=base_url, timeout=timeout, **kwargs)
        self._client = httpx.Client(base_url=base_url, timeout=self.timeout)

    def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7) -> str:
        logger.debug(
            "Ollama generate: model=%s prompt_len=%d max_tokens=%d timeout=%.0fs",
            self.model,
            len(prompt),
            max_tokens,
            self.timeout,
        )
        t0 = time.perf_counter()
        chunks: list[str] = []
        token_count = 0
        with self._client.stream(
            "POST",
            "/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": True,
                "think": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": temperature,
                },
            },
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                import json as _json

                data = _json.loads(line)
                token = data.get("response", "")
                if token:
                    chunks.append(token)
                    token_count += 1
                    if token_count <= 3 or token_count % 50 == 0:
                        logger.debug(
                            "Ollama token #%d (%.1fs): %r",
                            token_count,
                            time.perf_counter() - t0,
                            token[:40],
                        )
                if data.get("done"):
                    eval_dur = data.get("eval_duration", "n/a")
                    logger.debug(
                        "Ollama stream done: %d tokens, %d chars, eval_duration=%s, total=%.1fs",
                        token_count,
                        sum(len(c) for c in chunks),
                        eval_dur,
                        time.perf_counter() - t0,
                    )
                    break
        result = "".join(chunks)
        logger.debug(
            "Ollama generate finished: %d chars in %.1fs", len(result), time.perf_counter() - t0
        )
        return result

    def is_available(self) -> bool:
        try:
            resp = self._client.get("/api/tags")
            if resp.status_code != 200:
                return False
            models = [m["name"] for m in resp.json().get("models", [])]
            # Check if our model (or a variant like "qwen3:8b") is loaded
            return any(self.model in m for m in models)
        except (httpx.HTTPError, KeyError):
            return False
