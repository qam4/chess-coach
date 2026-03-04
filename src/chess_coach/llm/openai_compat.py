"""OpenAI-compatible API provider.

Works with any server that implements the /v1/chat/completions endpoint:
- llama.cpp server (--host 0.0.0.0 --port 8080)
- vLLM (python -m vllm.entrypoints.openai.api_server)
- LM Studio
- text-generation-webui with openai extension
"""

from __future__ import annotations

import httpx

from chess_coach.llm.base import LLMProvider


class OpenAICompatProvider(LLMProvider):
    """OpenAI-compatible chat completions API."""

    def __init__(self, model: str = "local-model",
                 base_url: str = "http://localhost:8080", **kwargs: object):
        super().__init__(model=model, base_url=base_url, **kwargs)
        self._client = httpx.Client(base_url=base_url, timeout=120.0)

    def generate(self, prompt: str, max_tokens: int = 512,
                 temperature: float = 0.7) -> str:
        resp = self._client.post(
            "/v1/chat/completions",
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def is_available(self) -> bool:
        try:
            resp = self._client.get("/v1/models")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False
