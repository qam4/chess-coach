"""Abstract LLM provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Base class for LLM providers. Implement this to add a new backend."""

    def __init__(self, model: str, base_url: str = "", **kwargs: object):
        self.model = model
        self.base_url = base_url

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
