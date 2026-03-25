"""Null LLM provider — used when LLM is disabled (template-only mode)."""

from __future__ import annotations

from chess_coach.llm.base import LLMProvider


class NullProvider(LLMProvider):
    """No-op LLM provider for template-only coaching (no LLM calls)."""

    def __init__(self, **kwargs: object):
        super().__init__(model="none", base_url="", timeout=0)

    def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7) -> str:
        return ""

    def is_available(self) -> bool:
        return False

    def smoke_test(self) -> tuple[bool, str]:
        return True, "LLM disabled (template-only mode)"
