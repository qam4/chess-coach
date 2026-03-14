"""Orchestrator: ties engine analysis to LLM coaching."""

from __future__ import annotations

import logging
import time
import typing
from dataclasses import dataclass, field

import chess

from chess_coach.analyzer import analyze_position, format_analysis_for_llm
from chess_coach.engine import AnalysisResult, CoachingEngine, EngineProtocol, UciEngine
from chess_coach.llm.base import LLMProvider
from chess_coach.openings import lookup_fen
from chess_coach.prompts import (
    build_coaching_prompt,
    build_engine_move_explanation_prompt,
    build_move_evaluation_prompt,
    build_rich_coaching_prompt,
    build_rich_move_evaluation_prompt,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Debug trace — shared between web UI and CLI
# ---------------------------------------------------------------------------


@dataclass
class TraceStep:
    """One step in the pipeline trace."""

    step: str
    message: str
    tool: str = ""  # "engine" | "llm" | ""
    elapsed_s: float = 0.0
    detail: dict[str, typing.Any] = field(default_factory=dict)


DebugCallback = typing.Callable[[TraceStep], None]
"""Signature for the on_debug callback."""


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
    llm_prompt: str = ""
    opening_name: str | None = None


@dataclass
class MoveEvaluation:
    """Evaluation of a user's move."""

    classification: str  # "good", "inaccuracy", "blunder"
    eval_before_cp: int
    eval_after_cp: int
    eval_drop_cp: int
    feedback: str  # LLM-generated feedback
    hint_uci: str | None = None
    """Best next move for the user (UCI notation), extracted from engine PV."""
    _result_after: typing.Any = field(default=None, repr=False)
    """Engine AnalysisResult for the position after the user's move (internal)."""


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
    debug: dict[str, typing.Any] | None = None


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
        play_elo: int = 0,
    ):
        self.engine = engine
        self.llm = llm
        self.depth = depth
        self.top_moves = top_moves
        self.level = level
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.play_elo = play_elo
        self._coaching_available = isinstance(engine, CoachingEngine) and engine.coaching_available

    def _set_play_skill(self) -> None:
        """Set engine to reduced strength for play moves."""
        if self.play_elo > 0 and hasattr(self.engine, "set_option"):
            self.engine.set_option("UCI_LimitStrength", True)
            self.engine.set_option("UCI_Elo", self.play_elo)

    def _set_full_strength(self) -> None:
        """Restore engine to full strength for analysis."""
        if self.play_elo > 0 and hasattr(self.engine, "set_option"):
            self.engine.set_option("UCI_LimitStrength", False)

    @property
    def debug_config(self) -> dict[str, typing.Any]:
        """Return config summary for debug traces."""
        if isinstance(self.engine, CoachingEngine):
            engine_path = getattr(self.engine, "_inner", None)
            engine_path = getattr(engine_path, "_path", "?") if engine_path else "?"
            engine_args = (
                getattr(self.engine._inner, "_args", []) if hasattr(self.engine, "_inner") else []
            )
            protocol = "coaching" if self._coaching_available else "uci"
        else:
            engine_path = getattr(self.engine, "_path", "?")
            engine_args = getattr(self.engine, "_args", [])
            protocol = "uci" if isinstance(self.engine, UciEngine) else "xboard"
        return {
            "engine": {
                "path": engine_path,
                "args": engine_args,
                "protocol": protocol,
                "depth": self.depth,
            },
            "llm": {
                "provider": type(self.llm).__name__,
                "model": getattr(self.llm, "model", "?"),
                "base_url": getattr(self.llm, "base_url", "?"),
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "timeout": getattr(self.llm, "timeout", "?"),
            },
            "coaching": {
                "level": self.level,
                "top_moves": self.top_moves,
                "coaching_available": self._coaching_available,
            },
        }

    def explain(
        self,
        fen: str,
        depth: int | None = None,
        level: str | None = None,
        on_progress: typing.Callable[[str], None] | None = None,
        on_debug: DebugCallback | None = None,
    ) -> CoachingResponse:
        """Analyze a position and generate a coaching explanation."""
        use_depth = depth if depth is not None else self.depth
        use_level = level if level is not None else self.level

        def _progress(msg: str) -> None:
            if on_progress:
                on_progress(msg)

        def _trace(step: str, message: str, elapsed: float = 0.0, **detail: typing.Any) -> None:
            if on_debug:
                on_debug(TraceStep(step=step, message=message, elapsed_s=elapsed, detail=detail))

        _trace("config", "Pipeline config", tool="system", **self.debug_config)

        # ----- Opening identification -----
        opening = lookup_fen(fen)
        if opening:
            _trace(
                "opening",
                f"Opening: {opening.eco} {opening.name}",
                eco=opening.eco,
                name=opening.name,
                pgn=opening.pgn,
            )

        # ----- Coaching protocol path (rich structured data) -----
        if self._coaching_available:
            assert isinstance(self.engine, CoachingEngine)
            _trace(
                "engine_start",
                "Coaching protocol: requesting position report",
                tool="engine",
                protocol="coaching",
                engine_command=f"coach eval fen {fen} multipv {self.top_moves}",
                input_fen=fen,
            )
            _progress("Engine analyzing (coaching protocol)...")
            t0 = time.perf_counter()
            report = self.engine.get_position_report(fen, multipv=self.top_moves)
            t1 = time.perf_counter()
            logger.info("Coaching position report took %.1fs", t1 - t0)

            best = (
                report.top_lines[0].moves[0]
                if report.top_lines and report.top_lines[0].moves
                else "?"
            )
            score = f"{report.eval_cp / 100:+.2f}"
            _trace(
                "engine_done",
                f"Position report ready — eval: {score}",
                tool="engine",
                elapsed=t1 - t0,
                eval_cp=report.eval_cp,
                position_report=report.to_dict(),
            )
            _progress(f"Engine done ({t1 - t0:.1f}s). LLM thinking...")

            opening_label = f"{opening.eco} {opening.name}" if opening else None
            prompt = build_rich_coaching_prompt(report, level=use_level, opening_name=opening_label)
            logger.debug("Rich coaching prompt length: %d chars", len(prompt))

            _trace(
                "llm_start",
                f"LLM generating ({len(prompt)} chars prompt)",
                tool="llm",
                model=getattr(self.llm, "model", "?"),
                base_url=getattr(self.llm, "base_url", "?"),
                llm_prompt=prompt,
            )
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
            _trace(
                "llm_done",
                f"LLM done ({t3 - t2:.1f}s)",
                tool="llm",
                elapsed=t3 - t2,
                llm_response=coaching_text,
            )
            _progress(
                f"LLM done ({t3 - t2:.1f}s, {len(coaching_text)} chars). Total: {t3 - t0:.1f}s"
            )

            return CoachingResponse(
                fen=fen,
                analysis_text=prompt,
                coaching_text=coaching_text,
                best_move=best,
                score=score,
                engine_elapsed_s=t1 - t0,
                llm_elapsed_s=t3 - t2,
                llm_prompt=prompt,
                opening_name=opening.name if opening else None,
            )

        # ----- UCI fallback path (existing flow) -----
        _trace(
            "engine_start",
            f"Engine analyzing (depth {use_depth})",
            tool="engine",
            input_fen=fen,
            depth=use_depth,
            top_n=self.top_moves,
        )
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
        lines_raw = [
            {"depth": ln.depth, "score_cp": ln.score_cp, "pv": ln.pv[:6]} for ln in result.lines
        ]
        _trace(
            "engine_done",
            f"Engine done — best: {best} ({score})",
            tool="engine",
            elapsed=t1 - t0,
            best_move=best,
            score=score,
            lines=lines_raw,
        )
        _progress(f"Engine done ({t1 - t0:.1f}s) — best: {best} ({score}). LLM thinking...")

        analysis_text = format_analysis_for_llm(result, level=use_level)
        opening_label = f"{opening.eco} {opening.name}" if opening else None
        prompt = build_coaching_prompt(analysis_text, level=use_level, opening_name=opening_label)
        logger.debug("Coaching prompt length: %d chars", len(prompt))

        _trace(
            "llm_start",
            f"LLM generating ({len(prompt)} chars prompt)",
            tool="llm",
            model=getattr(self.llm, "model", "?"),
            base_url=getattr(self.llm, "base_url", "?"),
            analysis_text=analysis_text,
            llm_prompt=prompt,
        )
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
        _trace(
            "llm_done",
            f"LLM done ({t3 - t2:.1f}s)",
            tool="llm",
            elapsed=t3 - t2,
            llm_response=coaching_text,
        )
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
            llm_prompt=prompt,
            opening_name=opening.name if opening else None,
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
        - good: eval drop <= 50 cp  (less than half a pawn — not worth critiquing)
        - inaccuracy: eval drop 51-100 cp
        - blunder: eval drop > 100 cp
        """
        if eval_drop_cp <= 50:
            return "good"
        elif eval_drop_cp <= 100:
            return "inaccuracy"
        else:
            return "blunder"

    def evaluate_move(
        self,
        fen_before: str,
        user_move: str,
        on_debug: DebugCallback | None = None,
    ) -> MoveEvaluation:
        """Classify a user move as good, inaccuracy, or blunder."""

        def _trace(step: str, message: str, elapsed: float = 0.0, **detail: typing.Any) -> None:
            if on_debug:
                on_debug(TraceStep(step=step, message=message, elapsed_s=elapsed, detail=detail))

        _trace("config", "Pipeline config", tool="system", **self.debug_config)

        # Ensure full strength for analysis (play strength may be active)
        self._set_full_strength()

        # ----- Coaching protocol path (single round-trip) -----
        if self._coaching_available:
            assert isinstance(self.engine, CoachingEngine)
            _trace(
                "eval_engine_coaching",
                "Coaching protocol: requesting comparison report",
                tool="engine",
                input_fen=fen_before,
                user_move=user_move,
            )
            t0 = time.perf_counter()
            report = self.engine.get_comparison_report(fen_before, user_move)
            t1 = time.perf_counter()
            logger.info("evaluate_move: coaching comparison report took %.1fs", t1 - t0)
            _trace(
                "eval_engine_coaching_done",
                f"Comparison report ready — {report.classification} "
                f"(drop {report.eval_drop_cp}cp, {report.nag})",
                tool="engine",
                elapsed=t1 - t0,
                classification=report.classification,
                eval_drop_cp=report.eval_drop_cp,
                nag=report.nag,
            )

            # Skip LLM for good moves — no need to explain what's not wrong.
            # If the user's move leads to a known opening position, it's a
            # book move — use a very high threshold (only critique real blunders).
            # Otherwise use the normal 50cp threshold.
            board_tmp = chess.Board(fen_before)
            board_tmp.push(chess.Move.from_uci(user_move))
            is_book_move = lookup_fen(board_tmp.fen()) is not None
            skip_threshold = 150 if is_book_move else 50
            if report.eval_drop_cp <= skip_threshold:
                _trace(
                    "eval_skip_llm",
                    f"Good move (drop {report.eval_drop_cp}cp) — skipping LLM",
                    tool="llm",
                )
                return MoveEvaluation(
                    classification="good",
                    eval_before_cp=report.best_eval_cp,
                    eval_after_cp=report.user_eval_cp,
                    eval_drop_cp=report.eval_drop_cp,
                    feedback="",
                )

            prompt = build_rich_move_evaluation_prompt(report, level=self.level)
            _trace(
                "eval_llm_start",
                f"LLM evaluating move ({len(prompt)} chars prompt)",
                tool="llm",
                model=getattr(self.llm, "model", "?"),
                base_url=getattr(self.llm, "base_url", "?"),
                llm_prompt=prompt,
            )
            t2 = time.perf_counter()
            feedback = self.llm.generate(
                prompt,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            t3 = time.perf_counter()
            logger.info("evaluate_move: LLM feedback took %.1fs", t3 - t2)
            logger.info("evaluate_move: total %.1fs", t3 - t0)
            _trace(
                "eval_llm_done",
                f"Move feedback ready: {report.classification}",
                tool="llm",
                elapsed=t3 - t2,
                llm_response=feedback,
            )

            return MoveEvaluation(
                classification=report.classification,
                eval_before_cp=report.best_eval_cp,
                eval_after_cp=report.user_eval_cp,
                eval_drop_cp=report.eval_drop_cp,
                feedback=feedback,
            )

        # ----- UCI fallback path (existing two-analysis flow) -----

        # 1. Analyze position before user's move
        _trace(
            "eval_engine_before",
            "Analyzing position before move",
            tool="engine",
            input_fen=fen_before,
            depth=self.depth,
            commands=["force", f"setboard {fen_before}", "analyze"],
        )
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
        best_before = result_before.best_move or "?"
        lines_before = [
            {"depth": ln.depth, "score_cp": ln.score_cp, "pv": ln.pv[:6]}
            for ln in result_before.lines
        ]
        _trace(
            "eval_engine_before_done",
            f"Position analyzed — best: {best_before}, eval: {eval_before}cp",
            tool="engine",
            elapsed=t1 - t0,
            best_move=best_before,
            eval_cp=eval_before,
            lines=lines_before,
        )

        # 2. Push user's move and analyze new position
        board = chess.Board(fen_before)
        move = chess.Move.from_uci(user_move)
        board.push(move)
        fen_after = board.fen()

        _trace(
            "eval_engine_after",
            "Analyzing position after move",
            tool="engine",
            input_fen=fen_after,
            user_move=user_move,
            commands=["force", f"setboard {fen_after}", "analyze"],
        )
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
        _trace(
            "eval_engine_after_done",
            f"Move analyzed — eval: {eval_before}→{eval_after}cp, "
            f"drop: {eval_drop}cp, {classification}",
            tool="engine",
            elapsed=t3 - t2,
            eval_before_cp=eval_before,
            eval_after_cp=eval_after,
            raw_eval_after_cp=raw_eval_after,
            eval_drop_cp=eval_drop,
            classification=classification,
        )

        # Skip LLM for good moves — no need to explain what's not wrong.
        # If the user's move leads to a known opening, it's a book move.
        is_book_move = lookup_fen(fen_after) is not None
        skip_threshold = 150 if is_book_move else 50
        if eval_drop <= skip_threshold:
            _trace(
                "eval_skip_llm",
                f"Good move (drop {eval_drop}cp) — skipping LLM feedback",
                tool="llm",
            )
            return MoveEvaluation(
                classification="good",
                eval_before_cp=eval_before,
                eval_after_cp=eval_after,
                eval_drop_cp=eval_drop,
                feedback="",
                _result_after=result_after,
            )

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
        _trace(
            "eval_llm_start",
            f"LLM evaluating move ({len(prompt)} chars prompt)",
            tool="llm",
            model=getattr(self.llm, "model", "?"),
            base_url=getattr(self.llm, "base_url", "?"),
            endpoint="/api/generate",
            llm_prompt=prompt,
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
        _trace(
            "eval_llm_done",
            f"Move feedback ready: {classification}",
            tool="llm",
            elapsed=t5 - t4,
            llm_response=feedback,
        )

        return MoveEvaluation(
            classification=classification,
            eval_before_cp=eval_before,
            eval_after_cp=eval_after,
            eval_drop_cp=eval_drop,
            feedback=feedback,
            _result_after=result_after,
        )

    def explain_engine_move(
        self,
        fen_before: str,
        engine_move: str,
        on_debug: DebugCallback | None = None,
        precomputed_analysis: AnalysisResult | None = None,
    ) -> str:
        """Generate coaching text explaining why the engine chose this move.

        If *precomputed_analysis* is provided (e.g. reused from evaluate_move),
        the engine analysis step is skipped, saving ~90s per call.
        """

        def _trace(step: str, message: str, elapsed: float = 0.0, **detail: typing.Any) -> None:
            if on_debug:
                on_debug(TraceStep(step=step, message=message, elapsed_s=elapsed, detail=detail))

        if precomputed_analysis is not None:
            result = precomputed_analysis
            _trace(
                "explain_engine_reuse",
                "Reusing pre-computed analysis (skipping engine call)",
                tool="engine",
                input_fen=fen_before,
                engine_move=engine_move,
            )
        else:
            _trace(
                "explain_engine_start",
                "Analyzing position for explanation",
                tool="engine",
                input_fen=fen_before,
                engine_move=engine_move,
                depth=self.depth,
                commands=["force", f"setboard {fen_before}", "analyze"],
            )
            t0 = time.perf_counter()
            result = analyze_position(
                self.engine,
                fen_before,
                depth=self.depth,
                top_n=1,
            )
            t1 = time.perf_counter()
            lines_raw = [
                {"depth": ln.depth, "score_cp": ln.score_cp, "pv": ln.pv[:6]} for ln in result.lines
            ]
            _trace(
                "explain_engine_done",
                f"Analysis ready ({t1 - t0:.1f}s)",
                tool="engine",
                elapsed=t1 - t0,
                lines=lines_raw,
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
        _trace(
            "explain_llm_start",
            f"LLM explaining move ({len(prompt)} chars prompt)",
            tool="llm",
            model=getattr(self.llm, "model", "?"),
            base_url=getattr(self.llm, "base_url", "?"),
            endpoint="/api/generate",
            llm_prompt=prompt,
        )
        t2 = time.perf_counter()
        coaching_text = self.llm.generate(
            prompt,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        t3 = time.perf_counter()
        _trace(
            "explain_llm_done",
            f"Explanation ready ({t3 - t2:.1f}s)",
            tool="llm",
            elapsed=t3 - t2,
            llm_response=coaching_text,
        )
        return coaching_text

    def play_move(self, fen: str, user_move: str) -> PlayMoveResponse:
        """Process a user move and get the engine's response with coaching.

        When the coaching protocol is available, uses:
        1. get_comparison_report() for user move evaluation (single round-trip)
        2. engine.play() for the engine's response move
        3. get_position_report() for engine move explanation → rich prompt → LLM

        Otherwise falls back to the existing optimised UCI pipeline:
        1. evaluate_move → 2 engine analyses + 1 LLM call
        2. engine.play   → 1 engine call (fast — just picks a move)
        3. explain_engine_move → reuses analysis from step 1, 1 LLM call only
        4. Eval from step 1's after-move analysis (negated) — no extra engine call
        """
        t_start = time.perf_counter()

        # ----- Coaching protocol path -----
        if self._coaching_available:
            assert isinstance(self.engine, CoachingEngine)

            # 1. Evaluate user's move via comparison report
            comparison = self.engine.get_comparison_report(fen, user_move)
            t_compare = time.perf_counter()

            # Build user feedback from comparison report
            user_prompt = build_rich_move_evaluation_prompt(comparison, level=self.level)
            user_feedback = self.llm.generate(
                user_prompt,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            t_user_llm = time.perf_counter()

            # 2. Push user's move to get new FEN
            board = chess.Board(fen)
            move = chess.Move.from_uci(user_move)
            board.push(move)
            fen_after_user = board.fen()

            # 3. Engine plays its response (at reduced skill if configured)
            self._set_play_skill()
            engine_move_uci = self.engine.play(
                fen_after_user,
                depth=self.depth,
            )
            self._set_full_strength()
            t_engine_play = time.perf_counter()

            # Convert engine move to SAN
            engine_move_obj = chess.Move.from_uci(engine_move_uci)
            engine_move_san = board.san(engine_move_obj)

            # 4. Push engine move and get position report for explanation
            board.push(engine_move_obj)
            fen_after_engine = board.fen()

            pos_report = self.engine.get_position_report(fen_after_engine, multipv=self.top_moves)
            t_pos_report = time.perf_counter()

            opening = lookup_fen(fen_after_engine)
            opening_label = f"{opening.eco} {opening.name}" if opening else None
            coaching_prompt = build_rich_coaching_prompt(
                pos_report,
                level=self.level,
                opening_name=opening_label,
            )
            coaching_text = self.llm.generate(
                coaching_prompt,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            t_explain = time.perf_counter()

            eval_cp = pos_report.eval_cp
            eval_score = f"{eval_cp / 100:+.2f}"

            debug = {
                "fen_input": fen,
                "user_move": user_move,
                "fen_after_user": fen_after_user,
                "engine_move_uci": engine_move_uci,
                "fen_after_engine": fen_after_engine,
                "eval_before_cp": comparison.best_eval_cp,
                "eval_after_cp": comparison.user_eval_cp,
                "eval_drop_cp": comparison.eval_drop_cp,
                "final_eval_cp": eval_cp,
                "coaching_protocol": True,
                "timings": {
                    "comparison_report_s": round(t_compare - t_start, 2),
                    "user_feedback_llm_s": round(t_user_llm - t_compare, 2),
                    "engine_play_s": round(t_engine_play - t_user_llm, 2),
                    "position_report_s": round(t_pos_report - t_engine_play, 2),
                    "explain_move_s": round(t_explain - t_pos_report, 2),
                    "total_s": round(t_explain - t_start, 2),
                },
            }

            return PlayMoveResponse(
                engine_move=engine_move_san,
                engine_move_uci=engine_move_uci,
                coaching_text=coaching_text,
                user_feedback=user_feedback,
                user_classification=comparison.classification,
                eval_cp=eval_cp,
                eval_score=eval_score,
                debug=debug,
            )

        # ----- UCI fallback path (existing flow) -----
        # 1. Evaluate user's move (produces analysis of position after user's move)
        evaluation = self.evaluate_move(fen, user_move)
        t_eval = time.perf_counter()

        # 2. Push user's move to get new FEN
        board = chess.Board(fen)
        move = chess.Move.from_uci(user_move)
        board.push(move)
        fen_after_user = board.fen()

        # 3. Engine plays its response (at reduced skill if configured)
        self._set_play_skill()
        engine_move_uci = self.engine.play(
            fen_after_user,
            depth=self.depth,
        )
        self._set_full_strength()
        t_engine_play = time.perf_counter()

        # Convert engine move to SAN
        engine_move_obj = chess.Move.from_uci(engine_move_uci)
        engine_move_san = board.san(engine_move_obj)

        # 4. Explain the engine's move — reuse the after-move analysis
        #    from evaluate_move instead of re-analyzing the same position
        coaching_text = self.explain_engine_move(
            fen_after_user,
            engine_move_san,
            precomputed_analysis=evaluation._result_after,
        )
        t_explain = time.perf_counter()

        # 5. Derive eval from the after-move analysis we already have.
        #    evaluate_move's result_after is from the opponent's perspective,
        #    so eval_after_cp is already negated. Use it directly as the
        #    position eval from the user's perspective.
        board.push(engine_move_obj)
        eval_cp = evaluation.eval_after_cp
        eval_score = f"{eval_cp / 100:+.2f}"

        debug = {
            "fen_input": fen,
            "user_move": user_move,
            "fen_after_user": fen_after_user,
            "engine_move_uci": engine_move_uci,
            "fen_after_engine": board.fen(),
            "eval_before_cp": evaluation.eval_before_cp,
            "eval_after_cp": evaluation.eval_after_cp,
            "eval_drop_cp": evaluation.eval_drop_cp,
            "final_eval_cp": eval_cp,
            "timings": {
                "evaluate_move_s": round(t_eval - t_start, 2),
                "engine_play_s": round(t_engine_play - t_eval, 2),
                "explain_move_s": round(t_explain - t_engine_play, 2),
                "total_s": round(t_explain - t_start, 2),
            },
        }

        return PlayMoveResponse(
            engine_move=engine_move_san,
            engine_move_uci=engine_move_uci,
            coaching_text=coaching_text,
            user_feedback=evaluation.feedback,
            user_classification=evaluation.classification,
            eval_cp=eval_cp,
            eval_score=eval_score,
            debug=debug,
        )
