"""Tests for Play vs Engine API endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from chess_coach.coach import Coach, PlayMoveResponse
from chess_coach.engine import (
    AnalysisLine,
    AnalysisResult,
    EngineProtocol,
)
from chess_coach.llm.base import LLMProvider
from chess_coach.web.server import create_app

STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

# FEN after 1. e4 e5
AFTER_E4_E5 = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"

# Scholar's mate checkmate position (white wins)
CHECKMATE_FEN = "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"


def _make_line(score_cp: int = 35) -> AnalysisLine:
    return AnalysisLine(
        depth=12,
        score_cp=score_cp,
        nodes=50000,
        time_ms=500,
        pv=["e2e4", "e7e5"],
    )


def _mock_coach() -> Coach:
    """Create a Coach with mocked engine and LLM for play endpoint tests."""
    engine = MagicMock(spec=EngineProtocol)
    engine.is_ready.return_value = True
    # engine.play returns a legal move in coordinate notation
    engine.play.return_value = "g1f3"
    # engine.analyze returns a basic result
    engine.analyze.return_value = AnalysisResult(
        fen=STARTING_FEN,
        lines=[_make_line(35)],
        best_move="e2e4",
    )

    llm = MagicMock(spec=LLMProvider)
    llm.is_available.return_value = True
    llm.generate.return_value = "Good move."

    coach = Coach(engine=engine, llm=llm, depth=12)

    # Mock play_move to return a realistic response
    coach.play_move = MagicMock(
        return_value=PlayMoveResponse(
            engine_move="Nf3",
            engine_move_uci="g1f3",
            coaching_text="The knight develops to a strong square.",
            user_feedback="Good opening move.",
            user_classification="good",
            eval_cp=35,
            eval_score="+0.35",
        )
    )

    # Mock explain_engine_move
    coach.explain_engine_move = MagicMock(
        return_value="The engine opens with a solid move.",
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
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as ac:
        yield ac


class TestPlayMoveEndpoint:
    """POST /api/play/move tests."""

    @pytest.mark.asyncio
    async def test_valid_move(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/play/move",
            json={
                "fen": STARTING_FEN,
                "user_move": "e2e4",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["engine_move"] == "Nf3"
        assert data["engine_move_uci"] == "g1f3"
        assert data["coaching_text"] is not None
        assert data["user_feedback"] is not None
        assert data["user_classification"] == "good"
        assert data["eval_cp"] == 35
        assert data["eval_score"] == "+0.35"
        assert data["game_over"] is False
        assert data["result"] is None

    @pytest.mark.asyncio
    async def test_invalid_fen(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/play/move",
            json={
                "fen": "not-a-valid-fen",
                "user_move": "e2e4",
            },
        )
        assert resp.status_code == 400
        assert "Invalid FEN" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_illegal_move(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/play/move",
            json={
                "fen": STARTING_FEN,
                "user_move": "e1e5",  # King can't move there
            },
        )
        assert resp.status_code == 400
        assert "Illegal move" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_invalid_move_format(
        self,
        client: AsyncClient,
    ) -> None:
        resp = await client.post(
            "/api/play/move",
            json={
                "fen": STARTING_FEN,
                "user_move": "xyz",
            },
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_missing_fields(self, client: AsyncClient) -> None:
        resp = await client.post("/api/play/move", json={})
        assert resp.status_code == 422


class TestPlayNewEndpoint:
    """POST /api/play/new tests."""

    @pytest.mark.asyncio
    async def test_new_game_as_white(
        self,
        client: AsyncClient,
    ) -> None:
        resp = await client.post(
            "/api/play/new",
            json={"color": "white"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["fen"] == STARTING_FEN
        assert data["engine_move"] is None
        assert data["engine_move_uci"] is None
        assert data["coaching_text"] is None

    @pytest.mark.asyncio
    async def test_new_game_as_black(
        self,
        client: AsyncClient,
    ) -> None:
        resp = await client.post(
            "/api/play/new",
            json={"color": "black"},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Engine should have made a move
        assert data["engine_move"] is not None
        assert data["engine_move_uci"] is not None
        assert data["coaching_text"] is not None
        # FEN should not be starting position (engine moved)
        assert data["fen"] != STARTING_FEN

    @pytest.mark.asyncio
    async def test_invalid_color(
        self,
        client: AsyncClient,
    ) -> None:
        resp = await client.post(
            "/api/play/new",
            json={"color": "red"},
        )
        assert resp.status_code == 400
        assert "color" in resp.json()["detail"]


class TestPlayUndoEndpoint:
    """POST /api/play/undo tests."""

    @pytest.mark.asyncio
    async def test_undo_with_moves(
        self,
        client: AsyncClient,
    ) -> None:
        resp = await client.post(
            "/api/play/undo",
            json={
                "fen": AFTER_E4_E5,
                "moves": ["e2e4", "e7e5", "g1f3", "b8c6"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # Should have replayed only first 2 moves
        assert data["moves"] == ["e2e4", "e7e5"]
        assert "eval_cp" in data
        assert "eval_score" in data
        assert "fen" in data

    @pytest.mark.asyncio
    async def test_undo_no_moves(
        self,
        client: AsyncClient,
    ) -> None:
        resp = await client.post(
            "/api/play/undo",
            json={
                "fen": STARTING_FEN,
                "moves": [],
            },
        )
        assert resp.status_code == 400
        assert "No moves" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_undo_single_move(
        self,
        client: AsyncClient,
    ) -> None:
        resp = await client.post(
            "/api/play/undo",
            json={
                "fen": STARTING_FEN,
                "moves": ["e2e4"],
            },
        )
        assert resp.status_code == 400
        assert "at least two" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_undo_to_starting_position(
        self,
        client: AsyncClient,
    ) -> None:
        """Undo with exactly 2 moves returns starting position."""
        resp = await client.post(
            "/api/play/undo",
            json={
                "fen": AFTER_E4_E5,
                "moves": ["e2e4", "e7e5"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["moves"] == []
        assert data["fen"] == STARTING_FEN


class TestPlayMoveGameOver:
    """Game-over detection in play/move response."""

    @pytest.mark.asyncio
    async def test_game_over_checkmate(self) -> None:
        """Detect checkmate after engine delivers mate."""
        coach = _mock_coach()

        # Fool's mate: 1. f3 e5 2. g4 Qh4#
        # Set up so user plays g4, engine responds with Qh4# (checkmate).
        # user makes a move, then engine checkmates.
        # Fool's mate: 1. f3 e5 2. g4 Qh4#
        # After 1. f3 e5, it's white's turn.
        # White plays g4 (user move), engine plays Qh4# (checkmate)
        fen_after_f3_e5 = "rnbqkbnr/pppp1ppp/8/4p3/8/5P2/PPPPP1PP/RNBQKBNR w KQkq - 0 2"

        coach.play_move = MagicMock(
            return_value=PlayMoveResponse(
                engine_move="Qh4#",
                engine_move_uci="d8h4",
                coaching_text="Checkmate!",
                user_feedback="A terrible blunder.",
                user_classification="blunder",
                eval_cp=-20000,
                eval_score="#-1",
            )
        )

        app = create_app(coach)
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as ac:
            resp = await ac.post(
                "/api/play/move",
                json={
                    "fen": fen_after_f3_e5,
                    "user_move": "g2g4",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["game_over"] is True
        assert data["result"] == "0-1"
