"""Orchestrator: ties engine analysis to LLM coaching."""

from __future__ import annotations

import logging
import time
import typing
from dataclasses import dataclass

import chess

from chess_coach.analyzer import analyze_position, format_analysis_for_llm
from chess_coach.engine import EngineProtocol
from chess_coach.llm.base import LLMProvider
from chess_coach.prompts import (
    build_coaching_prompt,
    build_engine_move_explanation_prompt,
    build_move_evaluation_prompt,
)

logger = logging.getLogger(__name__)


@dataclass
class CoachingResponse:
    """A coaching response for a position."""

    fen: str
    analysis_text: str
    coaching_text: str
    best_move: str
    score: str
    engine_elapsed_s: float = 0.0
    llm_elapsed_s: float = 0.0


@dataclass
class MoveEvaluation:
    """Evaluation of a user's move."""

    classification: str  # "good", "inaccuracy", "blunder"
    eval_before_cp: int
    eval_after_cp: int
    eval_drop_cp: int
    feedback: str  # LLM-generated feedback


@dataclass
class PlayMoveResponse:
    """Response from a play_move call."""

    engine_move: str  # SAN notation
    engine_move_uci: str  # UCI/coordinate notation
    coaching_text: str  # Why the engine played this move
    user_feedback: str  # Evaluation of the user's move
    user_classification: str  # good / inaccuracy / blunder
    eval_cp: int  # Eval after engine's move
    eval_score: str  # Human-readable score string


class Coach:
    """Main coaching class: position -> analysis -> LLM -> explanation."""

    def __init__(
        self,
        engine: EngineProtocol,
        llm: LLMProvider,
        depth: int = 18,
        top_moves: int = 3,
        level: str = "intermediate",
        max_tokens: int = 512,
        temperature: float = 0.7,
    ):
        self.engine = engine
        self.llm = llm
        self.depth = depth
        self.top_moves = top_moves
        self.level = level
        self.max_tokens = max_tokens
        self.temperature = temperature

    def explain(
        self,
        fen: str,
        depth: int | None = None,
        level: str | None = None,
        on_progress: typing.Callable[[str], None] | None = None,
    ) -> CoachingResponse:
        """Analyze a position and generate a coaching explanation."""
        use_depth = depth if depth is not None else self.depth
        use_level = level if level is not None else self.level

        def _progress(msg: str) -> None:
            if on_progress:
                on_progress(msg)

        _progress(f"Engine analyzing (depth {use_depth})...")
        t0 = time.perf_counter()
        result = analyze_position(
            self.engine,
            fen,
            depth=use_depth,
            top_n=self.top_moves,
        )
        t1 = time.perf_counter()
        logger.info("Engine analysis took %.1fs", t1 - t0)

        best = result.best_move or "?"
        score = result.top_line.score_str if result.top_line else "?"
        _progress(f"Engine done ({t1 - t0:.1f}s) — best: {best} ({score}). LLM thinking...")

        analysis_text = format_analysis_for_llm(result, level=use_level)
        prompt = build_coaching_prompt(analysis_text, level=use_level)
        logger.debug("Coaching prompt length: %d chars", len(prompt))

        t2 = time.perf_counter()
        _progress(f"LLM generating (prompt {len(prompt)} chars)...")
        coaching_text = self.llm.generate(
            prompt,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        t3 = time.perf_counter()
        logger.info("LLM generation took %.1fs", t3 - t2)
        logger.info("Total explain took %.1fs", t3 - t0)
        _progress(f"LLM done ({t3 - t2:.1f}s, {len(coaching_text)} chars). Total: {t3 - t0:.1f}s")
        score = result.top_line.score_str if result.top_line else "?"

        return CoachingResponse(
            fen=fen,
            analysis_text=analysis_text,
            coaching_text=coaching_text,
            best_move=result.best_move,
            score=score,
            engine_elapsed_s=t1 - t0,
            llm_elapsed_s=t3 - t2,
        )

    def check(self) -> dict[str, bool]:
        """Verify engine and LLM connectivity."""
        return {
            "engine": self.engine.is_ready(),
            "llm": self.llm.is_available(),
        }

    @staticmethod
    def classify_move(eval_drop_cp: int) -> str:
        """Classify a move based on centipawn eval drop.

        Thresholds (from side-to-move perspective):
        - good: eval drop <= 30 cp
        - inaccuracy: eval drop 31-100 cp
        - blunder: eval drop > 100 cp
        """
        if eval_drop_cp <= 30:
            return "good"
        elif eval_drop_cp <= 100:
            return "inaccuracy"
        else:
            return "blunder"

    def evaluate_move(
        self,
        fen_before: str,
        user_move: str,
    ) -> MoveEvaluation:
        """Classify a user move as good, inaccuracy, or blunder."""
        # 1. Analyze position before user's move
        t0 = time.perf_counter()
        result_before = analyze_position(
            self.engine,
            fen_before,
            depth=self.depth,
            top_n=1,
        )
        t1 = time.perf_counter()
        logger.info("evaluate_move: engine analysis (before) took %.1fs", t1 - t0)
        eval_before = result_before.top_line.score_cp if result_before.top_line else 0

        # 2. Push user's move and analyze new position
        board = chess.Board(fen_before)
        move = chess.Move.from_uci(user_move)
        board.push(move)
        fen_after = board.fen()

        t2 = time.perf_counter()
        result_after = analyze_position(
            self.engine,
            fen_after,
            depth=self.depth,
            top_n=1,
        )
        t3 = time.perf_counter()
        logger.info("evaluate_move: engine analysis (after) took %.1fs", t3 - t2)
        # eval_after is from the opponent's perspective, so negate it
        raw_eval_after = result_after.top_line.score_cp if result_after.top_line else 0
        eval_after = -raw_eval_after

        # 3. Compute eval drop from user's perspective
        eval_drop = max(0, eval_before - eval_after)

        # 4. Classify
        classification = self.classify_move(eval_drop)

        # 5. Format analysis and call LLM for feedback
        analysis_text = format_analysis_for_llm(
            result_before,
            level=self.level,
        )
        prompt = build_move_evaluation_prompt(
            fen_before=fen_before,
            fen_after=fen_after,
            user_move=user_move,
            eval_before=eval_before,
            eval_after=eval_after,
            eval_drop=eval_drop,
            classification=classification,
            analysis_text=analysis_text,
            level=self.level,
        )
        t4 = time.perf_counter()
        feedback = self.llm.generate(
            prompt,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        t5 = time.perf_counter()
        logger.info("evaluate_move: LLM feedback took %.1fs", t5 - t4)
        logger.info("evaluate_move: total %.1fs", t5 - t0)

        return MoveEvaluation(
            classification=classification,
            eval_before_cp=eval_before,
            eval_after_cp=eval_after,
            eval_drop_cp=eval_drop,
            feedback=feedback,
        )

    def explain_engine_move(
        self,
        fen_before: str,
        engine_move: str,
    ) -> str:
        """Generate coaching text explaining why the engine chose this move."""
        result = analyze_position(
            self.engine,
            fen_before,
            depth=self.depth,
            top_n=1,
        )
        analysis_text = format_analysis_for_llm(
            result,
            level=self.level,
        )
        prompt = build_engine_move_explanation_prompt(
            fen_before=fen_before,
            engine_move=engine_move,
            analysis_text=analysis_text,
            level=self.level,
        )
        return self.llm.generate(
            prompt,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )

    def play_move(self, fen: str, user_move: str) -> PlayMoveResponse:
        """Process a user move and get the engine's response with coaching.

        1. Evaluate the user's move
        2. Push the user's move to get the new position
        3. Have the engine play its response
        4. Explain the engine's move
        5. Analyze the final position for eval
        6. Return PlayMoveResponse
        """
        # 1. Evaluate user's move
        evaluation = self.evaluate_move(fen, user_move)

        # 2. Push user's move to get new FEN
        board = chess.Board(fen)
        move = chess.Move.from_uci(user_move)
        board.push(move)
        fen_after_user = board.fen()

        # 3. Engine plays its response
        engine_move_uci = self.engine.play(
            fen_after_user,
            depth=self.depth,
        )

        # Convert engine move to SAN
        engine_move_obj = chess.Move.from_uci(engine_move_uci)
        engine_move_san = board.san(engine_move_obj)

        # 4. Explain the engine's move
        coaching_text = self.explain_engine_move(
            fen_after_user,
            engine_move_san,
        )

        # 5. Push engine's move and analyze final position
        board.push(engine_move_obj)
        fen_after_engine = board.fen()

        result_final = analyze_position(
            self.engine,
            fen_after_engine,
            depth=self.depth,
            top_n=1,
        )
        eval_cp = result_final.top_line.score_cp if result_final.top_line else 0
        eval_score = result_final.top_line.score_str if result_final.top_line else "+0.00"

        return PlayMoveResponse(
            engine_move=engine_move_san,
            engine_move_uci=engine_move_uci,
            coaching_text=coaching_text,
            user_feedback=evaluation.feedback,
            user_classification=evaluation.classification,
            eval_cp=eval_cp,
            eval_score=eval_score,
        )
