"""Tests for chess_coach.web.server — FastAPI endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from chess_coach.coach import Coach, CoachingResponse
from chess_coach.engine import EngineProtocol
from chess_coach.llm.base import LLMProvider
from chess_coach.web.server import create_app

STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def _mock_coach(
    engine_ready: bool = True,
    llm_available: bool = True,
) -> Coach:
    """Create a Coach with mocked engine and LLM."""
    engine = MagicMock(spec=EngineProtocol)
    engine.is_ready.return_value = engine_ready

    llm = MagicMock(spec=LLMProvider)
    llm.is_available.return_value = llm_available

    coach = Coach(engine=engine, llm=llm)

    # Mock explain to avoid real engine/LLM calls
    coach.explain = MagicMock(
        return_value=CoachingResponse(
            fen=STARTING_FEN,
            analysis_text="Material: equal",
            coaching_text="Develop your pieces and control the center.",
            best_move="e2e4",
            score="+0.35",
        )
    )

    # Mock check to use the mocked statuses
    coach.check = MagicMock(
        return_value={
            "engine": engine_ready,
            "llm": llm_available,
        }
    )

    return coach


@pytest.fixture()
def app():
    """Create a FastAPI app with a mocked Coach."""
    return create_app(_mock_coach())


@pytest_asyncio.fixture()
async def client(app):
    """Async HTTP client for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestHealthEndpoint:
    """GET /api/health returns engine and LLM status."""

    @pytest.mark.asyncio
    async def test_health_ok(self, client: AsyncClient) -> None:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["engine"] is True
        assert data["llm"] is True

    @pytest.mark.asyncio
    async def test_health_degraded(self) -> None:
        coach = _mock_coach(engine_ready=False, llm_available=True)
        app = create_app(coach)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["engine"] is False


class TestAnalyzeEndpoint:
    """POST /api/analyze returns coaching response."""

    @pytest.mark.asyncio
    async def test_analyze_success(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/analyze",
            json={
                "fen": STARTING_FEN,
                "depth": 12,
                "level": "beginner",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["coaching_text"] == "Develop your pieces and control the center."
        assert data["best_move"] == "e2e4"
        assert data["score"] == "+0.35"
        assert data["fen"] == STARTING_FEN

    @pytest.mark.asyncio
    async def test_analyze_default_params(self, client: AsyncClient) -> None:
        resp = await client.post("/api/analyze", json={"fen": STARTING_FEN})
        assert resp.status_code == 200
        data = resp.json()
        assert "coaching_text" in data

    @pytest.mark.asyncio
    async def test_analyze_missing_fen(self, client: AsyncClient) -> None:
        resp = await client.post("/api/analyze", json={})
        assert resp.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_analyze_calls_coach_explain(self, app) -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            await ac.post(
                "/api/analyze",
                json={
                    "fen": STARTING_FEN,
                    "depth": 20,
                    "level": "advanced",
                },
            )
        app.state.coach.explain.assert_called_once_with(
            STARTING_FEN,
            depth=20,
            level="advanced",
        )


class TestIndexEndpoint:
    """GET / serves the index.html page."""

    @pytest.mark.asyncio
    async def test_index_returns_html(self, client: AsyncClient) -> None:
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Chess Coach" in resp.text


class TestStaticFiles:
    """Static files are served correctly."""

    @pytest.mark.asyncio
    async def test_css_served(self, client: AsyncClient) -> None:
        resp = await client.get("/static/style.css")
        assert resp.status_code == 200
        assert "text/css" in resp.headers["content-type"]

    @pytest.mark.asyncio
    async def test_js_served(self, client: AsyncClient) -> None:
        resp = await client.get("/static/app.js")
        assert resp.status_code == 200
        assert "javascript" in resp.headers["content-type"]

    @pytest.mark.asyncio
    async def test_vendor_js_served(self, client: AsyncClient) -> None:
        resp = await client.get("/static/vendor/chess.js")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_missing_file_404(self, client: AsyncClient) -> None:
        resp = await client.get("/static/nonexistent.xyz")
        assert resp.status_code == 404
