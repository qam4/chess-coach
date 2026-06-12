"""LLM provider abstraction layer."""

from chess_coach.llm.base import LLMProvider
from chess_coach.llm.null import NullProvider
from chess_coach.llm.ollama import OllamaProvider
from chess_coach.llm.openai_compat import OpenAICompatProvider
from chess_coach.llm.outcome import DispatchOutcome, classify_exception, classify_status, describe


def create_provider(
    provider: str,
    model: str = "none",
    base_url: str = "http://localhost:11434",
    timeout: float = 300.0,
    probe_timeout: float = 5.0,
    **kwargs: object,
) -> LLMProvider:
    """Factory: create an LLM provider by name."""
    providers: dict[str, type[LLMProvider]] = {
        "ollama": OllamaProvider,
        "openai_compat": OpenAICompatProvider,
        "none": NullProvider,
    }
    cls = providers.get(provider)
    if cls is None:
        raise ValueError(f"Unknown LLM provider: {provider!r}. Choose from: {list(providers)}")
    if cls is NullProvider:
        return NullProvider()
    return cls(model=model, base_url=base_url, timeout=timeout, probe_timeout=probe_timeout, **kwargs)


__all__ = [
    "DispatchOutcome",
    "LLMProvider",
    "NullProvider",
    "OllamaProvider",
    "OpenAICompatProvider",
    "classify_exception",
    "classify_status",
    "create_provider",
    "describe",
]
