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
from chess_coach.coach import Coach, CoachingResponse, MoveEvaluation, TraceStep

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
                "opening_name": response.opening_name,
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

    @app.post("/api/analyze/template")
    async def analyze_template(req: AnalyzeRequest) -> dict:  # type: ignore[type-arg]
        """Analyze using template engine — no LLM, instant, no hallucination."""
        from chess_coach.coaching_templates import generate_position_coaching
        from chess_coach.engine import CoachingEngine
        from chess_coach.openings import lookup_fen

        coach = app.state.coach
        engine = coach.engine

        if not (isinstance(engine, CoachingEngine) and engine.coaching_available):
            raise HTTPException(
                status_code=400,
                detail="Template mode requires coaching protocol support",
            )

        try:
            t0 = time.perf_counter()
            report = await asyncio.to_thread(
                engine.get_position_report,
                req.fen,
                multipv=coach.top_moves,
            )
            opening = lookup_fen(req.fen)
            coaching_text = generate_position_coaching(report, level=req.level, opening=opening)
            elapsed = time.perf_counter() - t0

            best_line = report.top_lines[0] if report.top_lines else None
            best_move = best_line.moves[0] if best_line and best_line.moves else "?"
            score = f"{report.eval_cp / 100:+.2f}"

            return {
                "coaching_text": coaching_text,
                "best_move": best_move,
                "score": score,
                "fen": req.fen,
                "opening_name": f"{opening.eco} {opening.name}" if opening else None,
                "mode": "template",
                "debug": {
                    "engine_s": round(elapsed, 2),
                    "llm_s": 0.0,
                    "total_s": round(elapsed, 2),
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

    @app.get("/api/play/strength")
    async def get_strength() -> dict:  # type: ignore[type-arg]
        return {"play_elo": app.state.coach.play_elo}

    @app.post("/api/play/strength")
    async def set_strength(req: dict) -> dict:  # type: ignore[type-arg]
        elo = req.get("play_elo", 0)
        if not isinstance(elo, int) or elo < 0 or elo > 2500:
            raise HTTPException(
                status_code=400,
                detail="play_elo must be 0-2500 (0 = full strength)",
            )
        coach = app.state.coach
        coach.play_elo = elo
        if hasattr(coach.engine, "set_option"):
            if elo > 0:
                coach.engine.set_option("UCI_LimitStrength", True)
                coach.engine.set_option("UCI_Elo", elo)
            else:
                coach.engine.set_option("UCI_LimitStrength", False)
        return {"play_elo": elo}

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

        # Opening identification — check after user move and after engine move,
        # return the most specific (latest) match
        from chess_coach.openings import lookup_fen

        opening_name = None
        # Check position after user's move
        board_after_user = chess.Board(req.fen)
        board_after_user.push(move)
        opening = lookup_fen(board_after_user.fen())
        if opening:
            opening_name = opening.name
        # Check position after engine's move (may be more specific)
        opening2 = lookup_fen(board.fen())
        if opening2:
            opening_name = opening2.name

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
            "opening_name": opening_name,
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
                app.state.coach._set_play_skill()
                engine_move_uci = app.state.coach.engine.play(
                    starting_fen,
                    depth=app.state.coach.depth,
                )
                app.state.coach._set_full_strength()
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

                    # Config summary
                    from chess_coach.engine import CoachingEngine as _CE

                    _is_coaching = isinstance(coach.engine, _CE) and coach.engine.coaching_available
                    _proto = "coaching" if _is_coaching else "uci"
                    _emit(
                        "config",
                        f"mode=llm protocol={_proto} depth={coach.depth} "
                        f"play_elo={coach.play_elo} "
                        f"llm={getattr(coach.llm, 'model', '?')}",
                        tool="system",
                    )

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

                    coach._set_play_skill()
                    engine_move_uci = await asyncio.to_thread(
                        coach.engine.play,
                        fen_after_user,
                        depth=coach.depth,
                    )
                    coach._set_full_strength()
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
                    # the after-move analysis from evaluate_move.
                    # In known openings, skip the LLM and just name the opening.
                    from chess_coach.openings import lookup_fen as _lookup_fen

                    board_after.push(engine_move_obj)
                    opening_before_engine = _lookup_fen(fen_after_user)
                    opening_after_engine = _lookup_fen(board_after.fen())
                    # Use the most specific opening name available
                    opening_match = opening_after_engine or opening_before_engine
                    if opening_match:
                        coaching_text = f"**{opening_match.name}** ({opening_match.eco})"
                        _emit(
                            "explain_skip_opening",
                            f"Opening book — {opening_match.name}",
                            tool="llm",
                        )
                    else:
                        coaching_text = await asyncio.to_thread(
                            coach.explain_engine_move,
                            fen_after_user,
                            engine_move_san,
                            _on_debug,
                            evaluation._result_after,
                        )

                    # Step 4: Derive eval from evaluate_move (no extra
                    # engine call needed)
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

                    # Opening identification
                    from chess_coach.openings import lookup_fen as _lookup_fen

                    opening_name = None
                    _op = _lookup_fen(fen_after_user)
                    if _op:
                        opening_name = _op.name
                    _op2 = _lookup_fen(board_after.fen())
                    if _op2:
                        opening_name = _op2.name

                    # Extract hint: best next move for the user.
                    # Try existing PV first, fall back to a quick engine query.
                    hint_uci = None
                    hint_san = None
                    ra = evaluation._result_after
                    if ra and ra.top_line and len(ra.top_line.pv) >= 2:
                        if ra.top_line.pv[0] == engine_move_uci:
                            hint_uci = ra.top_line.pv[1]
                    if hint_uci is None and not game_over:
                        try:
                            hint_uci = await asyncio.to_thread(
                                coach.engine.play,
                                board_after.fen(),
                                depth=coach.depth,
                            )
                        except Exception:
                            pass
                    if hint_uci:
                        try:
                            hint_move = chess.Move.from_uci(hint_uci)
                            hint_san = board_after.san(hint_move)
                        except (ValueError, AssertionError):
                            hint_san = hint_uci

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
                        "opening_name": opening_name,
                        "hint_uci": hint_uci,
                        "hint_san": hint_san,
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

    @app.post("/api/play/move/template")
    async def play_move_template(req: PlayMoveRequest) -> dict:  # type: ignore[type-arg]
        """Play a move with template-based coaching — no LLM, fast."""
        from chess_coach.coaching_templates import (
            generate_move_coaching,
            generate_position_coaching,
        )
        from chess_coach.engine import CoachingEngine
        from chess_coach.openings import lookup_fen

        coach = app.state.coach
        engine = coach.engine

        # Validate
        try:
            board = chess.Board(req.fen)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid FEN: {exc}") from exc
        try:
            move = chess.Move.from_uci(req.user_move)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid move: {exc}") from exc
        if move not in board.legal_moves:
            raise HTTPException(status_code=400, detail=f"Illegal move: {req.user_move}")

        try:
            t0 = time.perf_counter()
            trace: list[str] = []

            # Config summary
            is_coaching = isinstance(engine, CoachingEngine) and engine.coaching_available
            protocol = "coaching" if is_coaching else "uci"
            trace.append(
                f"config: mode=template protocol={protocol} "
                f"depth={coach.depth} play_elo={coach.play_elo}"
            )

            # 1. Evaluate user's move via comparison report
            user_feedback = ""
            if isinstance(engine, CoachingEngine) and engine.coaching_available:
                trace.append(f">> coach compare fen {req.fen} move {req.user_move}")
                t_eval = time.perf_counter()
                report = await asyncio.to_thread(
                    engine.get_comparison_report, req.fen, req.user_move
                )
                t1 = time.perf_counter()
                import json as _json_cmp

                trace.append(
                    "<< comparison_report:\n" + _json_cmp.dumps(report.to_dict(), indent=2)
                )

                # Classify using our threshold
                board_tmp = chess.Board(req.fen)
                board_tmp.push(move)
                from chess_coach.openings import lookup_fen as _lfen

                is_book = _lfen(board_tmp.fen()) is not None
                skip_threshold = 150 if is_book else 50
                if report.eval_drop_cp <= skip_threshold:
                    classification = "good"
                elif report.eval_drop_cp <= 100:
                    classification = "inaccuracy"
                else:
                    classification = Coach.classify_move(report.eval_drop_cp)
                evaluation = MoveEvaluation(
                    classification=classification,
                    eval_before_cp=report.best_eval_cp,
                    eval_after_cp=report.user_eval_cp,
                    eval_drop_cp=report.eval_drop_cp,
                    feedback="",
                )
                trace.append(
                    f"classification={classification} "
                    f"drop={report.eval_drop_cp}cp "
                    f"(threshold={skip_threshold}cp, "
                    f"book={is_book}) [{t1 - t_eval:.1f}s]"
                )
                if classification != "good":
                    user_feedback = generate_move_coaching(report)
            else:
                trace.append(f"evaluate_move (UCI): fen={req.fen} move={req.user_move}")
                evaluation = await asyncio.to_thread(coach.evaluate_move, req.fen, req.user_move)
                t1 = time.perf_counter()
                trace.append(
                    f"<< classification={evaluation.classification} "
                    f"drop={evaluation.eval_drop_cp}cp "
                    f"[{t1 - t0:.1f}s]"
                )

            # 2. Engine plays its response
            board.push(move)
            fen_after_user = board.fen()

            coach._set_play_skill()
            trace.append(f">> setoption UCI_LimitStrength true / UCI_Elo {coach.play_elo}")
            trace.append(f">> position fen {fen_after_user}\\n>> go depth {coach.depth}")
            t2 = time.perf_counter()
            engine_move_uci = await asyncio.to_thread(
                engine.play, fen_after_user, depth=coach.depth
            )
            t3 = time.perf_counter()
            # Don't call _set_full_strength() here — it sends setoption
            # commands that corrupt the stdout stream for the next coaching
            # command. Blunder ignores UCI_LimitStrength for coach commands
            # anyway, so it's safe to leave it on.

            engine_move_obj = chess.Move.from_uci(engine_move_uci)
            engine_move_san = board.san(engine_move_obj)
            board.push(engine_move_obj)
            trace.append(f"engine played: {engine_move_san} ({engine_move_uci}) [{t3 - t2:.1f}s]")

            # 3. Template coaching for the position after engine's move
            pos_report = None
            opening = lookup_fen(board.fen()) or lookup_fen(fen_after_user)
            opening_label = f"**{opening.name}** ({opening.eco})\n\n" if opening else ""

            if isinstance(engine, CoachingEngine) and engine.coaching_available:
                try:
                    trace.append(f">> coach eval fen {board.fen()} multipv {coach.top_moves}")
                    pos_report = await asyncio.to_thread(
                        engine.get_position_report,
                        board.fen(),
                        multipv=coach.top_moves,
                    )
                    coaching_text = generate_position_coaching(
                        pos_report, level=coach.level, opening=opening
                    )
                    # Full position report in debug trace
                    import json as _json

                    trace.append(
                        "<< position_report:\n" + _json.dumps(pos_report.to_dict(), indent=2)
                    )
                except Exception as exc:
                    trace.append(f"<< coach eval FAILED: {exc}")
                    # Fall back to basic eval from comparison report
                    coaching_text = opening_label
                    if evaluation.eval_after_cp is not None:
                        cp = evaluation.eval_after_cp
                        if abs(cp) < 30:
                            coaching_text += "The position is roughly equal."
                        else:
                            side = "White" if cp > 0 else "Black"
                            coaching_text += f"{side} has an edge ({cp / 100:+.2f} pawns)."
            else:
                coaching_text = opening_label

            # 4. Eval and game state — use pos_report eval (current board)
            if pos_report:
                eval_cp = pos_report.eval_cp
            else:
                eval_cp = evaluation.eval_after_cp
            eval_score = f"{eval_cp / 100:+.2f}"
            game_over = board.is_game_over()
            result = board.result() if game_over else None

            # 5. Extract hint for user's next move
            hint_uci = None
            hint_san = None
            if not game_over:
                # Try the position report PV if we have one
                if pos_report and pos_report.top_lines:
                    top = pos_report.top_lines[0]
                    if top.moves:
                        hint_uci = top.moves[0]
                # Fallback: quick engine query with book enabled
                if hint_uci is None:
                    try:
                        coach._set_play_skill()
                        hint_uci = await asyncio.to_thread(
                            engine.play, board.fen(), depth=coach.depth
                        )
                        coach._set_full_strength()
                    except Exception:
                        pass
                if hint_uci:
                    try:
                        hint_move = chess.Move.from_uci(hint_uci)
                        hint_san = board.san(hint_move)
                        trace.append(f"hint: {hint_san} ({hint_uci})")
                    except (ValueError, AssertionError):
                        hint_san = hint_uci

            # Build alternative moves text from MultiPV
            hint_alternatives = None
            if pos_report:
                from chess_coach.coaching_templates import (
                    _alternative_moves_text,
                )

                hint_alternatives = _alternative_moves_text(pos_report)

            elapsed = time.perf_counter() - t0

            return {
                "engine_move": engine_move_san,
                "engine_move_uci": engine_move_uci,
                "coaching_text": coaching_text,
                "user_feedback": user_feedback or evaluation.feedback,
                "user_classification": evaluation.classification,
                "eval_cp": eval_cp,
                "eval_score": eval_score,
                "game_over": game_over,
                "result": result,
                "opening_name": opening.name if opening else None,
                "hint_uci": hint_uci,
                "hint_san": hint_san,
                "hint_alternatives": hint_alternatives,
                "mode": "template",
                "debug": {
                    "engine_s": round(elapsed, 2),
                    "llm_s": 0.0,
                    "total_s": round(elapsed, 2),
                    "trace": trace,
                },
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

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
