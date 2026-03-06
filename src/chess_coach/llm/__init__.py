"""LLM provider abstraction layer."""

from chess_coach.llm.base import LLMProvider
from chess_coach.llm.ollama import OllamaProvider
from chess_coach.llm.openai_compat import OpenAICompatProvider


def create_provider(
    provider: str,
    model: str,
    base_url: str = "http://localhost:11434",
    timeout: float = 300.0,
    **kwargs: object,
) -> LLMProvider:
    """Factory: create an LLM provider by name."""
    providers: dict[str, type[LLMProvider]] = {
        "ollama": OllamaProvider,
        "openai_compat": OpenAICompatProvider,
    }
    cls = providers.get(provider)
    if cls is None:
        raise ValueError(f"Unknown LLM provider: {provider!r}. Choose from: {list(providers)}")
    return cls(model=model, base_url=base_url, timeout=timeout, **kwargs)


__all__ = ["LLMProvider", "OllamaProvider", "OpenAICompatProvider", "create_provider"]
