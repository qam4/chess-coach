"""Ollama LLM provider — local inference via Ollama's REST API."""

from __future__ import annotations

import httpx

from chess_coach.llm.base import LLMProvider


class OllamaProvider(LLMProvider):
    """Connects to a local Ollama instance.

    Ollama serves models at http://localhost:11434 by default.
    Install: https://ollama.com/download
    Pull a model: ollama pull qwen3:8b
    """

    def __init__(
        self, model: str = "qwen3:8b", base_url: str = "http://localhost:11434", **kwargs: object
    ):
        super().__init__(model=model, base_url=base_url, **kwargs)
        self._client = httpx.Client(base_url=base_url, timeout=120.0)

    def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7) -> str:
        resp = self._client.post(
            "/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": temperature,
                },
            },
        )
        resp.raise_for_status()
        return str(resp.json()["response"])

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
