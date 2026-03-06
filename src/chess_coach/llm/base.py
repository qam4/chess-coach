"""Abstract LLM provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Base class for LLM providers. Implement this to add a new backend."""

    def __init__(self, model: str, base_url: str = "", timeout: float = 300.0, **kwargs: object):
        self.model = model
        self.base_url = base_url
        self.timeout = timeout

    @abstractmethod
    def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7) -> str:
        """Generate a text response from the LLM.

        Args:
            prompt: The full prompt text.
            max_tokens: Maximum tokens in the response.
            temperature: Sampling temperature (0.0 = deterministic).

        Returns:
            The generated text.
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is reachable and the model is loaded."""
        ...

    def smoke_test(self) -> tuple[bool, str]:
        """Quick generation test to verify the model can actually respond.

        Returns:
            (success, message) — message is the response text or error detail.
        """
        try:
            reply = self.generate("Say hi", max_tokens=16, temperature=0.0)
            if reply.strip():
                return True, reply.strip()[:80]
            return False, "Empty response"
        except Exception as exc:
            return False, str(exc)[:120]
