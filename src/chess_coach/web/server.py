"""FastAPI web server for the chess coaching UI."""

from __future__ import annotations

from pathlib import Path

import chess
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from chess_coach.analyzer import analyze_position
from chess_coach.coach import Coach

STATIC_DIR = Path(__file__).parent / "static"


def create_app(coach: Coach) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="Chess Coach")
    app.state.coach = coach

    # Mount static files
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(str(STATIC_DIR / "index.html"))

    @app.post("/api/analyze")
    async def analyze(req: AnalyzeRequest) -> dict:  # type: ignore[type-arg]
        try:
            response = app.state.coach.explain(
                req.fen,
                depth=req.depth,
                level=req.level,
            )
            top_line = None
            if hasattr(response, "analysis_text"):
                top_line = response.analysis_text
            return {
                "coaching_text": response.coaching_text,
                "best_move": response.best_move,
                "score": response.score,
                "analysis_text": top_line or "",
                "fen": response.fen,
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/health")
    async def health() -> dict:  # type: ignore[type-arg]
        status = app.state.coach.check()
        return {
            "status": "ok" if all(status.values()) else "degraded",
            "engine": status.get("engine", False),
            "llm": status.get("llm", False),
        }

    @app.post("/api/play/move")
    async def play_move(req: PlayMoveRequest) -> dict:  # type: ignore[type-arg]
        # Validate FEN
        try:
            board = chess.Board(req.fen)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid FEN: {exc}") from exc

        # Validate move
        try:
            move = chess.Move.from_uci(req.user_move)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid move format: {exc}") from exc

        if move not in board.legal_moves:
            raise HTTPException(status_code=400, detail=f"Illegal move: {req.user_move}")

        try:
            response = app.state.coach.play_move(req.fen, req.user_move)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        # Check for game over after engine's move
        board.push(move)
        engine_move_obj = chess.Move.from_uci(response.engine_move_uci)
        board.push(engine_move_obj)
        game_over = board.is_game_over()
        result = None
        if game_over:
            result = board.result()

        return {
            "engine_move": response.engine_move,
            "engine_move_uci": response.engine_move_uci,
            "coaching_text": response.coaching_text,
            "user_feedback": response.user_feedback,
            "user_classification": response.user_classification,
            "eval_cp": response.eval_cp,
            "eval_score": response.eval_score,
            "game_over": game_over,
            "result": result,
        }

    @app.post("/api/play/new")
    async def play_new(req: PlayNewRequest) -> dict:  # type: ignore[type-arg]
        if req.color not in ("white", "black"):
            raise HTTPException(status_code=400, detail="color must be 'white' or 'black'")

        starting_fen = chess.STARTING_FEN

        if req.color == "black":
            # Engine plays first as white
            try:
                engine_move_uci = app.state.coach.engine.play(
                    starting_fen,
                    depth=app.state.coach.depth,
                )
                board = chess.Board(starting_fen)
                engine_move_obj = chess.Move.from_uci(engine_move_uci)
                engine_move_san = board.san(engine_move_obj)
                board.push(engine_move_obj)

                coaching_text = app.state.coach.explain_engine_move(
                    starting_fen,
                    engine_move_san,
                )

                return {
                    "fen": board.fen(),
                    "engine_move": engine_move_san,
                    "engine_move_uci": engine_move_uci,
                    "coaching_text": coaching_text,
                }
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc

        return {
            "fen": starting_fen,
            "engine_move": None,
            "engine_move_uci": None,
            "coaching_text": None,
        }

    @app.post("/api/play/undo")
    async def play_undo(req: PlayUndoRequest) -> dict:  # type: ignore[type-arg]
        if not req.moves:
            raise HTTPException(status_code=400, detail="No moves to undo")

        if len(req.moves) < 2:
            raise HTTPException(
                status_code=400, detail="Need at least two moves to undo a move pair"
            )

        # Replay all but last two moves from starting position
        truncated_moves = req.moves[:-2]
        board = chess.Board()

        for uci_str in truncated_moves:
            try:
                move = chess.Move.from_uci(uci_str)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"Invalid move: {uci_str}") from exc
            if move not in board.legal_moves:
                raise HTTPException(status_code=400, detail=f"Illegal move in history: {uci_str}")
            board.push(move)

        # Evaluate the resulting position
        try:
            result = analyze_position(
                app.state.coach.engine,
                board.fen(),
                depth=app.state.coach.depth,
                top_n=1,
            )
            eval_cp = result.top_line.score_cp if result.top_line else 0
            eval_score = result.top_line.score_str if result.top_line else "+0.00"
        except Exception:
            eval_cp = 0
            eval_score = "+0.00"

        return {
            "fen": board.fen(),
            "moves": truncated_moves,
            "eval_cp": eval_cp,
            "eval_score": eval_score,
        }

    return app


class AnalyzeRequest(BaseModel):
    """Request body for the analyze endpoint."""

    fen: str
    depth: int = 18
    level: str = "intermediate"


class PlayMoveRequest(BaseModel):
    """Request body for the play/move endpoint."""

    fen: str
    user_move: str


class PlayNewRequest(BaseModel):
    """Request body for the play/new endpoint."""

    color: str  # "white" or "black"


class PlayUndoRequest(BaseModel):
    """Request body for the play/undo endpoint."""

    fen: str
    moves: list[str]
