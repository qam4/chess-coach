"""Tests for chess_coach.llm — LLM providers with httpx mock transport."""

from __future__ import annotations

import json

import httpx
import pytest

from chess_coach.llm import (
    LLMProvider,
    OllamaProvider,
    OpenAICompatProvider,
    create_provider,
)

# ---------------------------------------------------------------------------
# Helpers: httpx MockTransport factories
# ---------------------------------------------------------------------------


def _json_response(data: dict, status: int = 200) -> httpx.Response:
    """Build an httpx.Response with JSON body."""
    return httpx.Response(status, json=data)


def _make_transport(handler):
    """Wrap a handler function as an httpx.MockTransport."""
    return httpx.MockTransport(handler)


def _inject_transport(provider: LLMProvider, handler) -> None:
    """Replace the provider's httpx client with one using a mock transport."""
    transport = _make_transport(handler)
    provider._client = httpx.Client(transport=transport, base_url=provider.base_url)


# ---------------------------------------------------------------------------
# OllamaProvider tests
# ---------------------------------------------------------------------------


class TestOllamaProviderGenerate:
    def test_generate_returns_response_text(self):
        """generate() should POST to /api/generate and return the response field."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/generate"
            body = json.loads(request.content)
            assert body["model"] == "qwen3:8b"
            assert body["prompt"] == "Explain this position"
            assert body["stream"] is False
            return _json_response({"response": "The position is equal."})

        provider = OllamaProvider(model="qwen3:8b")
        _inject_transport(provider, handler)

        result = provider.generate("Explain this position")
        assert result == "The position is equal."

    def test_generate_passes_options(self):
        """generate() should forward max_tokens and temperature as options."""

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["options"]["num_predict"] == 256
            assert body["options"]["temperature"] == 0.3
            return _json_response({"response": "ok"})

        provider = OllamaProvider()
        _inject_transport(provider, handler)

        provider.generate("test", max_tokens=256, temperature=0.3)

    def test_generate_http_error_raises(self):
        """generate() should raise on non-2xx status."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal Server Error")

        provider = OllamaProvider()
        _inject_transport(provider, handler)

        with pytest.raises(httpx.HTTPStatusError):
            provider.generate("test")


class TestOllamaProviderIsAvailable:
    def test_available_when_model_found(self):
        """is_available() returns True when the model appears in /api/tags."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/tags"
            return _json_response(
                {
                    "models": [
                        {"name": "qwen3:8b"},
                        {"name": "llama3:8b"},
                    ]
                }
            )

        provider = OllamaProvider(model="qwen3:8b")
        _inject_transport(provider, handler)

        assert provider.is_available() is True

    def test_unavailable_when_model_not_found(self):
        """is_available() returns False when the model is not in the list."""

        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"models": [{"name": "llama3:8b"}]})

        provider = OllamaProvider(model="qwen3:8b")
        _inject_transport(provider, handler)

        assert provider.is_available() is False

    def test_unavailable_when_server_down(self):
        """is_available() returns False when the server is unreachable."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        provider = OllamaProvider()
        _inject_transport(provider, handler)

        assert provider.is_available() is False

    def test_unavailable_on_non_200(self):
        """is_available() returns False on non-200 status."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="Service Unavailable")

        provider = OllamaProvider()
        _inject_transport(provider, handler)

        assert provider.is_available() is False


# ---------------------------------------------------------------------------
# OpenAICompatProvider tests
# ---------------------------------------------------------------------------


class TestOpenAICompatProviderGenerate:
    def test_generate_returns_message_content(self):
        """generate() should POST to /v1/chat/completions and return content."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/chat/completions"
            body = json.loads(request.content)
            assert body["model"] == "local-model"
            assert body["messages"][0]["role"] == "user"
            assert body["messages"][0]["content"] == "Explain this"
            return _json_response(
                {"choices": [{"message": {"content": "Here is the explanation."}}]}
            )

        provider = OpenAICompatProvider(model="local-model")
        _inject_transport(provider, handler)

        result = provider.generate("Explain this")
        assert result == "Here is the explanation."

    def test_generate_passes_parameters(self):
        """generate() should forward max_tokens and temperature."""

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["max_tokens"] == 128
            assert body["temperature"] == 0.5
            return _json_response({"choices": [{"message": {"content": "ok"}}]})

        provider = OpenAICompatProvider()
        _inject_transport(provider, handler)

        provider.generate("test", max_tokens=128, temperature=0.5)

    def test_generate_http_error_raises(self):
        """generate() should raise on non-2xx status."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal Server Error")

        provider = OpenAICompatProvider()
        _inject_transport(provider, handler)

        with pytest.raises(httpx.HTTPStatusError):
            provider.generate("test")


class TestOpenAICompatProviderIsAvailable:
    def test_available_on_200(self):
        """is_available() returns True when /v1/models returns 200."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/models"
            return _json_response({"data": [{"id": "local-model"}]})

        provider = OpenAICompatProvider()
        _inject_transport(provider, handler)

        assert provider.is_available() is True

    def test_unavailable_on_non_200(self):
        """is_available() returns False on non-200 status."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="Service Unavailable")

        provider = OpenAICompatProvider()
        _inject_transport(provider, handler)

        assert provider.is_available() is False

    def test_unavailable_when_server_down(self):
        """is_available() returns False when the server is unreachable."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        provider = OpenAICompatProvider()
        _inject_transport(provider, handler)

        assert provider.is_available() is False


# ---------------------------------------------------------------------------
# create_provider factory tests
# ---------------------------------------------------------------------------


class TestCreateProvider:
    def test_create_ollama(self):
        """create_provider('ollama') returns an OllamaProvider."""
        provider = create_provider("ollama", model="qwen3:8b")
        assert isinstance(provider, OllamaProvider)
        assert provider.model == "qwen3:8b"

    def test_create_openai_compat(self):
        """create_provider('openai_compat') returns an OpenAICompatProvider."""
        provider = create_provider(
            "openai_compat",
            model="local-model",
            base_url="http://localhost:8080",
        )
        assert isinstance(provider, OpenAICompatProvider)
        assert provider.model == "local-model"
        assert provider.base_url == "http://localhost:8080"

    def test_unknown_provider_raises(self):
        """create_provider with unknown name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            create_provider("nonexistent", model="test")

    def test_unknown_provider_lists_options(self):
        """ValueError message should list available providers."""
        with pytest.raises(ValueError, match="ollama"):
            create_provider("bad", model="test")
