"""FastAPI web server for the chess coaching UI."""

from __future__ import annotations

import asyncio
import json
import time
import typing
from pathlib import Path

import chess
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from chess_coach.analyzer import analyze_position
from chess_coach.coach import Coach, CoachingResponse, TraceStep

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
                "debug": {
                    "fen_input": response.fen,
                    "engine_analysis": response.analysis_text,
                    "llm_prompt": response.llm_prompt,
                    "llm_response": response.coaching_text,
                    "timings": {
                        "engine_s": round(response.engine_elapsed_s, 2),
                        "llm_s": round(response.llm_elapsed_s, 2),
                        "total_s": round(response.engine_elapsed_s + response.llm_elapsed_s, 2),
                    },
                },
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
            "debug": response.debug,
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

    # ==================================================================
    # SSE streaming endpoints
    # ==================================================================

    @app.post("/api/analyze/stream")
    async def analyze_stream(req: AnalyzeRequest) -> StreamingResponse:
        coach = app.state.coach

        async def generate() -> typing.AsyncGenerator[str, None]:
            queue: asyncio.Queue[str | None] = asyncio.Queue()
            trace_events: list[dict[str, typing.Any]] = []
            loop = asyncio.get_event_loop()

            def _on_debug(step: TraceStep) -> None:
                event_data = {
                    "step": step.step,
                    "message": step.message,
                    "tool": step.tool,
                    "elapsed_s": round(step.elapsed_s, 2),
                    "detail": step.detail,
                }
                trace_events.append(event_data)
                loop.call_soon_threadsafe(queue.put_nowait, _sse_event("progress", event_data))

            async def _run_explain() -> CoachingResponse | Exception:
                try:
                    return await asyncio.to_thread(
                        coach.explain,
                        req.fen,
                        depth=req.depth,
                        level=req.level,
                        on_debug=_on_debug,
                    )
                except Exception as exc:
                    return exc
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, None)

            task = asyncio.create_task(_run_explain())

            # Yield SSE events as they arrive in real time
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item

            response = await task
            if isinstance(response, Exception):
                yield _sse_event("error", {"message": str(response)})
                return

            yield _sse_event(
                "done",
                {
                    "coaching_text": response.coaching_text,
                    "best_move": response.best_move,
                    "score": response.score,
                    "analysis_text": response.analysis_text or "",
                    "fen": req.fen,
                    "debug": {"trace": trace_events},
                },
            )

        return StreamingResponse(generate(), media_type="text/event-stream")

    @app.post("/api/play/move/stream")
    async def play_move_stream(req: PlayMoveRequest) -> StreamingResponse:
        # Validate upfront
        try:
            board = chess.Board(req.fen)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid FEN: {exc}") from exc

        try:
            move = chess.Move.from_uci(req.user_move)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid move format: {exc}") from exc

        if move not in board.legal_moves:
            raise HTTPException(status_code=400, detail=f"Illegal move: {req.user_move}")

        coach = app.state.coach

        async def generate() -> typing.AsyncGenerator[str, None]:
            queue: asyncio.Queue[str | None] = asyncio.Queue()
            trace_events: list[dict[str, typing.Any]] = []
            loop = asyncio.get_event_loop()

            def _on_debug(step: TraceStep) -> None:
                event_data = {
                    "step": step.step,
                    "message": step.message,
                    "tool": step.tool,
                    "elapsed_s": round(step.elapsed_s, 2),
                    "detail": step.detail,
                }
                trace_events.append(event_data)
                loop.call_soon_threadsafe(queue.put_nowait, _sse_event("progress", event_data))

            def _emit(
                step: str, message: str, tool: str = "", elapsed: float = 0.0, **detail: typing.Any
            ) -> None:
                _on_debug(
                    TraceStep(
                        step=step, message=message, tool=tool, elapsed_s=elapsed, detail=detail
                    )
                )

            async def _run_pipeline() -> dict[str, typing.Any] | Exception:
                try:
                    t0 = time.perf_counter()

                    # Step 1: Evaluate user's move
                    evaluation = await asyncio.to_thread(
                        coach.evaluate_move,
                        req.fen,
                        req.user_move,
                        on_debug=_on_debug,
                    )

                    # Step 2: Engine plays its response
                    board_after = chess.Board(req.fen)
                    board_after.push(chess.Move.from_uci(req.user_move))
                    fen_after_user = board_after.fen()

                    _emit(
                        "engine_play",
                        "Engine choosing its move",
                        tool="engine",
                        input_fen=fen_after_user,
                        depth=coach.depth,
                        commands=["force", f"setboard {fen_after_user}", f"sd {coach.depth}", "go"],
                    )

                    engine_move_uci = await asyncio.to_thread(
                        coach.engine.play,
                        fen_after_user,
                        depth=coach.depth,
                    )
                    t_play = time.perf_counter()

                    engine_move_obj = chess.Move.from_uci(engine_move_uci)
                    engine_move_san = board_after.san(engine_move_obj)
                    _emit(
                        "engine_play_done",
                        f"Engine plays {engine_move_san}",
                        tool="engine",
                        elapsed=t_play - t0,
                        engine_move_uci=engine_move_uci,
                        engine_move_san=engine_move_san,
                    )

                    # Step 3: LLM explains the engine's move — reuse
                    # the after-move analysis from evaluate_move
                    coaching_text = await asyncio.to_thread(
                        coach.explain_engine_move,
                        fen_after_user,
                        engine_move_san,
                        _on_debug,
                        evaluation._result_after,
                    )

                    # Step 4: Derive eval from evaluate_move (no extra
                    # engine call needed)
                    board_after.push(engine_move_obj)
                    eval_cp = evaluation.eval_after_cp
                    eval_score = f"{eval_cp / 100:+.2f}"
                    t_end = time.perf_counter()

                    _emit(
                        "pipeline_done",
                        f"Eval: {eval_score} — total: {t_end - t0:.1f}s",
                        tool="engine",
                        elapsed=t_end - t0,
                        eval_cp=eval_cp,
                        eval_score=eval_score,
                    )

                    # Check game over
                    game_over = board_after.is_game_over()
                    result = board_after.result() if game_over else None

                    return {
                        "engine_move": engine_move_san,
                        "engine_move_uci": engine_move_uci,
                        "coaching_text": coaching_text,
                        "user_feedback": evaluation.feedback,
                        "user_classification": evaluation.classification,
                        "eval_cp": eval_cp,
                        "eval_score": eval_score,
                        "game_over": game_over,
                        "result": result,
                    }
                except Exception as exc:
                    return exc
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, None)

            task = asyncio.create_task(_run_pipeline())

            # Yield SSE events as they arrive in real time
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item

            result_data = await task
            if isinstance(result_data, Exception):
                yield _sse_event("error", {"message": str(result_data)})
                return

            result_data["debug"] = {"trace": trace_events}
            yield _sse_event("done", result_data)

        return StreamingResponse(generate(), media_type="text/event-stream")

    return app


def _sse_event(event: str, data: dict[str, typing.Any]) -> str:
    """Format a Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


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
