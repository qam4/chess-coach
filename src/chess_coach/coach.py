"""Orchestrator: ties engine analysis to LLM coaching."""

from __future__ import annotations

import logging
import time
import typing
from collections import Counter
from dataclasses import dataclass, field

import chess

from chess_coach.analyzer import analyze_position, format_analysis_for_llm
from chess_coach.coaching_phrases import DUBIOUS_MAX_DROP_CP, OPENING_LENIENCY_CP, SOUND_MAX_DROP_CP
from chess_coach.coaching_templates import generate_move_coaching, generate_position_coaching
from chess_coach.engine import AnalysisResult, CoachingEngine, EngineProtocol, UciEngine
from chess_coach.llm.base import LLMProvider
from chess_coach.models import ComparisonReport, PositionReport
from chess_coach.openings import lookup_fen
from chess_coach.piece_history import PieceHistory
from chess_coach.prompts import (
    LESSON_RETIRE_AFTER,
    build_coaching_prompt,
    build_engine_move_explanation_prompt,
    build_move_evaluation_prompt,
    build_rich_coaching_prompt,
    build_rich_move_evaluation_prompt,
    build_socratic_prompt,
    compose_safe_move_feedback,
    composed_achievement,
    composed_lesson,
    move_feedback_max_tokens,
    refuted_square,
)
from chess_coach.verify import Violation, generate_verified

logger = logging.getLogger(__name__)


def _move_ends_game(fen: str, uci: str) -> bool:
    """True if playing ``uci`` in ``fen`` ends the game (mate, stalemate, or a draw).

    Total: any unparseable position or move answers False, so a bad input can only
    fall back to the ordinary skip rules rather than raise inside coaching.
    """
    try:
        board = chess.Board(fen)
        move = chess.Move.from_uci(uci)
    except ValueError:
        return False
    if move not in board.legal_moves:
        return False
    board.push(move)
    return board.is_game_over(claim_draw=True)


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
    _comparison: typing.Any = field(default=None, repr=False)
    """The ``ComparisonReport`` this evaluation was built from (internal).

    Exposed so the eval harness can report the engine's best move, phase and
    eval-drop WITHOUT re-running the comparison or rebuilding the coaching path.
    It reconstructed that path instead, and drifted from it three times: it
    mirrored guidance selection by hand, it missed output verification entirely,
    and it missed the rule that keeps the coach silent on good moves — which
    produced a repetition defect that no student could ever see.
    """
    _position_report: typing.Any = field(default=None, repr=False)
    """The ``PositionReport`` used for guidance/menu, when one was fetched (internal)."""


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
        coaching_depth: int | None = None,
        top_moves: int = 3,
        level: str = "intermediate",
        max_tokens: int = 512,
        temperature: float = 0.7,
        play_elo: int = 0,
        book_path: str = "",
        template_only: bool = False,
        guidance: bool = False,
        guidance_max: int = 3,
        constrain_moves: bool = True,
        verify_output: bool = True,
        verify_retries: int = 1,
    ):
        self.engine = engine
        self.llm = llm
        self.depth = depth  # play depth (engine as opponent)
        self.coaching_depth = coaching_depth or depth  # analysis depth (engine as coach)
        self.top_moves = top_moves
        self.level = level
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.play_elo = play_elo
        self.book_path = book_path
        self.template_only = template_only
        self.guidance = guidance
        self.guidance_max = guidance_max
        self.constrain_moves = constrain_moves
        # Check the finished text against the board before the student sees it,
        # rather than only counting violations on an eval scoreboard. See
        # verify.GATING_VIOLATION_KINDS for what blocks a send and why.
        self.verify_output = verify_output
        self.verify_retries = max(0, verify_retries)
        self._coaching_available = isinstance(engine, CoachingEngine) and engine.coaching_available
        self._last_position_report: PositionReport | None = None  # for breakdown diffs
        # Per-game memory of what has already been taught, keyed by composed lesson.
        # Without it the coach treats every turn as its first: in v33 it closed on
        # "going after a piece that has too few defenders" five times in one game
        # (plies 20, 30, 38, 44, 46), each instance individually true, because the
        # engine kept recommending the same move and the composer kept describing it
        # identically. A frontier reviewer called that "one lesson, five times, with no
        # escalation and no memory". Reset by :meth:`new_game`.
        self._lessons_taught: Counter[str] = Counter()
        # The game record, kept so a turn can say how a piece came to be where it is.
        # Diagnosis was stuck at 5 for four runs because this did not exist: the coach
        # saw one position and could only ever report the consequence.
        self._piece_history = PieceHistory()

        # Pedagogy guidance resource (loaded once, guarded) when the knob is on.
        # The profiler recommends turning this on per model; default off = no
        # change to behaviour. If the resource can't load, disable gracefully.
        self._resource = None
        if guidance:
            try:
                from chess_coach.pedagogy.guard import guard_entries
                from chess_coach.pedagogy.resource import (
                    KnowledgeResource,
                    default_resource_path,
                    load_resource,
                )

                res = load_resource(default_resource_path())
                admitted, _ = guard_entries(res.entries, engine=None)
                self._resource = KnowledgeResource(
                    entries=tuple(admitted),
                    feature_vocab=res.feature_vocab,
                    eco_vocab=res.eco_vocab,
                    levels=res.levels,
                )
            except Exception as e:
                logger.warning("guidance enabled but knowledge resource unavailable: %s — guidance disabled", e)
                self.guidance = False

        # Load opening book via UCI option if path is configured
        if book_path and hasattr(engine, "set_option"):
            engine.set_option("BookFile", book_path)
            engine.set_option("Book", True)

    def new_game(self) -> None:
        """Forget everything that is per-game, so a fresh game starts clean.

        Two pieces of state: the lesson history behind the teach / escalate / retire
        ladder, and the previous position report used for breakdown diffs. Without
        this, a long-lived ``Coach`` (the web server holds one for its whole life)
        would carry lessons from a finished game into the next one and go quiet on a
        student who has never been told them.

        ``_last_position_report`` was already per-game state with no reset, which is a
        latent defect on the same footing — the first move of game two would be
        diffed against the last position of game one.
        """
        self._lessons_taught.clear()
        self._last_position_report = None
        self._piece_history.clear()

    def _select_guidance(self, pos_report: PositionReport, level: str) -> list | None:  # type: ignore[type-arg]
        """Select pedagogy guidance for a position when the guidance knob is on.

        Returns ``None`` when guidance is disabled or the resource is
        unavailable, so the prompt builders fall back to their no-guidance
        behaviour (no change vs. guidance off).
        """
        if not self.guidance or self._resource is None:
            return None
        try:
            from chess_coach.pedagogy.instantiate import feature_facts
            from chess_coach.pedagogy.selector import guidance_for_position
            from chess_coach.pedagogy.theme_map import theme_features

            # Bias guidance toward the theme of the move the coach will lead
            # with (the engine's best line), so the taught principle matches
            # the recommended move. Soft bias — never restricts the selection.
            preferred: frozenset[str] = frozenset()
            if pos_report.top_lines and pos_report.top_lines[0].theme:
                preferred = theme_features(pos_report.top_lines[0].theme)

            # Also prefer entries we can INSTANTIATE with a verified board fact.
            # Measured: without this, only 10 of 30 selected entries could carry
            # a "HERE: ..." fact — entries tied on relevance and the tie-break
            # (type, then id) was blind to whether a fact existed, so "center
            # control" beat "answer the threat first" in a position with a live
            # threat. Passed as its own rank term, NOT folded into `preferred`:
            # the PV theme "piece development" maps to the broad `phase:opening`
            # feature, which handed the same bonus to every abstract opening
            # entry and cancelled the fact bias out.
            facts = frozenset(feature_facts(pos_report))

            return guidance_for_position(
                self._resource,
                pos_report,
                level,
                self.guidance_max,
                preferred_features=preferred,
                fact_features=facts,
            )
        except Exception as e:
            logger.warning("guidance selection failed: %s — proceeding without guidance", e)
            return None

    def _set_play_skill(self) -> None:
        """Set engine to reduced strength for play moves."""
        if hasattr(self.engine, "set_option"):
            # Enable opening book for variety in play mode
            self.engine.set_option("Book", True)
            if self.play_elo > 0:
                self.engine.set_option("UCI_LimitStrength", True)
                self.engine.set_option("UCI_Elo", self.play_elo)

    def _set_full_strength(self) -> None:
        """Restore engine to full strength for analysis."""
        if hasattr(self.engine, "set_option"):
            # Disable opening book for analysis (always search)
            self.engine.set_option("Book", False)
            if self.play_elo > 0:
                self.engine.set_option("UCI_LimitStrength", False)

    @property
    def debug_config(self) -> dict[str, typing.Any]:
        """Return config summary for debug traces."""
        if isinstance(self.engine, CoachingEngine):
            engine_path = getattr(self.engine, "_inner", None)
            engine_path = getattr(engine_path, "_path", "?") if engine_path else "?"
            engine_args = getattr(self.engine._inner, "_args", []) if hasattr(self.engine, "_inner") else []
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
        socratic: bool = False,
        on_progress: typing.Callable[[str], None] | None = None,
        on_debug: DebugCallback | None = None,
    ) -> CoachingResponse:
        """Analyze a position and generate a coaching explanation.

        When ``socratic`` is True, the coach asks guiding questions (grounded
        in the engine features, without revealing the best move or evaluation)
        instead of explaining the position.
        """
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

            best = report.top_lines[0].moves[0] if report.top_lines and report.top_lines[0].moves else "?"
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
            if socratic:
                prompt = build_socratic_prompt(report, level=use_level, opening_name=opening_label)
            else:
                guidance = self._select_guidance(report, use_level)
                prompt = build_rich_coaching_prompt(
                    report,
                    level=use_level,
                    opening_name=opening_label,
                    guidance=guidance,
                    constrain_moves=self.constrain_moves,
                )
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
            if self.template_only and not socratic:
                # Profiler-recommended for models that hallucinate: skip the LLM
                # and use the deterministic template coaching instead.
                coaching_text = generate_position_coaching(report, level=use_level)
            else:
                _progress(f"LLM generating (prompt {len(prompt)} chars)...")
                try:
                    coaching_text = self.llm.generate(
                        prompt,
                        max_tokens=self.max_tokens,
                        temperature=self.temperature,
                    )
                    if not coaching_text.strip():
                        raise ValueError("Empty LLM response")
                except Exception as e:
                    logger.warning("LLM failed for position coaching: %s — falling back to templates", e)
                    if socratic:
                        coaching_text = (
                            "Before you choose a move, ask yourself: Are any of my "
                            "pieces undefended? What is my opponent threatening right "
                            "now? Which of my pieces is doing the least, and could it "
                            "do more? Take a look and see what stands out."
                        )
                    else:
                        coaching_text = generate_position_coaching(report, level=use_level)
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
        lines_raw = [{"depth": ln.depth, "score_cp": ln.score_cp, "pv": ln.pv[:6]} for ln in result.lines]
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
        try:
            coaching_text = self.llm.generate(
                prompt,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            if not coaching_text.strip():
                raise ValueError("Empty LLM response")
        except Exception as e:
            logger.warning("LLM failed for position coaching (UCI path): %s — falling back to templates", e)
            # UCI path doesn't have a PositionReport, so use the analysis_text as-is
            coaching_text = analysis_text
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

        Thresholds (from side-to-move perspective) share the single-source
        centipawn boundaries in ``coaching_phrases`` with the move-menu
        soundness tags, so the numbers are defined in exactly one place:
        - good: drop <= ``SOUND_MAX_DROP_CP`` (not worth critiquing)
        - inaccuracy: drop up to ``DUBIOUS_MAX_DROP_CP``
        - blunder: past that

        The values are deliberately not repeated here. They were, and the docstring went
        stale the moment the engine's output scale changed — a comment is the one place a
        threshold can be wrong with no test to catch it.
        """
        if eval_drop_cp <= SOUND_MAX_DROP_CP:
            return "good"
        elif eval_drop_cp <= DUBIOUS_MAX_DROP_CP:
            return "inaccuracy"
        else:
            return "blunder"

    def _ends_game(self, fen: str, uci: str) -> bool:
        """Does playing ``uci`` in ``fen`` end the game? Total: never raises."""
        return _move_ends_game(fen, uci)

    def _verified_move_feedback(
        self,
        prompt: str,
        report: ComparisonReport,
        max_tokens: int,
        trace: typing.Callable[..., None],
        lesson_times_taught: int = 0,
    ) -> str:
        """Generate move feedback and refuse to return a false claim about the board.

        The deterministic checker already existed but only ever fed an eval
        scoreboard, so a response contradicting the board still reached the
        student. An external audit of coaching quality made truth a GATE rather
        than a weighted quality — a false claim is worse than silence, because a
        1200 cannot detect it and will act on it for months.

        On a gating violation: regenerate once (the same prompt — the model is
        sampled, so a retry is a genuinely different draw), then fall back to the
        composed template, which is built from engine facts and cannot invent a
        piece. The fallback is degraded, not wrong, which is the right way round.

        Only :data:`verify.GATING_VIOLATION_KINDS` blocks; adherence kinds with
        known false positives stay reported and un-gated.
        """

        def _generate() -> str:
            return self.llm.generate(prompt, max_tokens=max_tokens, temperature=self.temperature)

        if not self.verify_output:
            feedback = _generate()
            if not feedback.strip():
                raise ValueError("Empty LLM response")
            return feedback

        def _on_violation(attempt: int, attempts: int, bad: list[Violation]) -> None:
            detail = "; ".join(f"{v.kind}: {v.text} — {v.detail}" for v in bad)
            logger.warning(
                "evaluate_move: response contradicts the board (attempt %d/%d): %s", attempt, attempts, detail
            )
            trace(
                "eval_verify_failed",
                f"Response contradicts the board (attempt {attempt}/{attempts}): {detail}",
                tool="llm",
                violations=[{"kind": v.kind, "text": v.text, "detail": v.detail} for v in bad],
            )

        def _on_fallback(bad: list[Violation]) -> None:
            why = "; ".join(f"{v.kind}: {v.detail}" for v in bad)
            logger.warning("evaluate_move: sending composed text instead (%s)", why)
            trace(
                "eval_verify_fallback",
                f"Falling back to composed text — every attempt contradicted the board ({why})",
                tool="engine",
                violations=[{"kind": v.kind, "text": v.text, "detail": v.detail} for v in bad],
            )

        return generate_verified(
            _generate,
            report.fen,
            # Composed from the board, keeping the teaching shape — not the general
            # template, which showed pawn-unit costs and dumped raw tactic data. Passed
            # the lesson count so the safety net honours the same ladder as the prompt:
            # at v34 ply 46 the gate fired and this text shipped the fifth telling of a
            # lesson the prompt builder had already retired.
            lambda: (
                compose_safe_move_feedback(report, lesson_times_taught)
                or generate_move_coaching(report, level=self.level)
            ),
            retries=self.verify_retries,
            # The move actually played, so a mate described without notation is still
            # caught — the beginner level asks the coach to avoid notation.
            played_uci=report.user_move,
            on_violation=_on_violation,
            on_fallback=_on_fallback,
        )

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

        # Record the move in the game history FIRST, before any of the early returns
        # below. v39 is why this sits here and not next to the composition: it was
        # placed after the "stay quiet on an unremarkable move" returns, so only 16 of
        # the game's 40 student moves were ever seen. The knight that died on g5 had
        # walked there on a quiet move, so the record held no arrival for it — and the
        # composer read that absence as "has not moved this game" and said so. A piece
        # the coach declines to comment on is still a piece whose story it needs later.
        self._piece_history.observe(fen_before, user_move)

        # Note: coaching commands always run at full strength in Blunder
        # (UCI_LimitStrength is ignored for coach commands), so no need
        # to toggle strength here.

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
            report = self.engine.get_comparison_report(fen_before, user_move, depth=self.coaching_depth)
            t1 = time.perf_counter()
            logger.info("evaluate_move: coaching comparison report took %.1fs", t1 - t0)
            _trace(
                "eval_engine_coaching_done",
                f"Comparison report ready — {report.classification} (drop {report.eval_drop_cp}cp, {report.nag})",
                tool="engine",
                elapsed=t1 - t0,
                classification=report.classification,
                eval_drop_cp=report.eval_drop_cp,
                nag=report.nag,
            )

            # Skip LLM for good moves — no need to explain what's not wrong.
            # In the opening (first ~6 moves), engine eval at shallow depth
            # is unreliable — only critique moves with a large eval drop.
            move_number = int(fen_before.split()[-1]) if fen_before.split() else 1
            # A move that ends the game always gets a word. The skip rules look only
            # at the eval drop, and checkmate has a drop of zero — so the student
            # delivered mate and the coach said NOTHING. Found when the report card
            # finally started calling this method: the curated Ra8# position went
            # silent. It also reframes the mate-labelling defect a reviewer called its
            # decisive item; that only ever appeared because the harness forced
            # commentary on a good move. In production the coach was not wrong about
            # mate, it was absent.
            ends_game = _move_ends_game(fen_before, user_move)
            if ends_game:
                _trace(
                    "eval_terminal",
                    "Move ends the game — coaching it regardless of eval drop",
                    tool="engine",
                )
            # 75 was 150 before the engine started normalizing its output (see
            # OPENING_LENIENCY_CP): an algebraic halving, verified against the row-53
            # book positions, which now score 55 where they scored 110.
            if not ends_game and move_number <= 6 and report.eval_drop_cp <= OPENING_LENIENCY_CP:
                _trace(
                    "eval_skip_llm",
                    f"Opening move (move {move_number}, drop {report.eval_drop_cp}cp) — skipping LLM",
                    tool="llm",
                )
                return MoveEvaluation(
                    classification="good",
                    eval_before_cp=report.best_eval_cp,
                    eval_after_cp=report.user_eval_cp,
                    eval_drop_cp=report.eval_drop_cp,
                    feedback="",
                    _comparison=report,
                )
            if not ends_game and report.eval_drop_cp <= SOUND_MAX_DROP_CP:
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
                    _comparison=report,
                )

            guidance = None
            guidance_facts: dict[str, str] | None = None
            pos_report = None
            if self.guidance and self._resource is not None:
                from chess_coach.pedagogy.instantiate import feature_facts

                try:
                    pos_report = self.engine.get_position_report(fen_before, multipv=self.top_moves)
                    guidance = self._select_guidance(pos_report, self.level)
                    # Instantiate each selected theme with the board fact that
                    # fired it, so the guidance is specific rather than abstract.
                    guidance_facts = feature_facts(pos_report)
                except Exception as e:
                    logger.warning("evaluate_move: guidance position report failed: %s", e)

            # A SECOND report, for the position the student's move produces. This is the
            # position the coaching is about, and asking the engine about it is the v40
            # fix. v40 used the before-move report for "what is undefended" and the model
            # wrote "your move leaves your pawn on c4 vulnerable" about a pawn that had
            # just moved off c4 — on 4 of 13 turns the fact was stale, and the fidelity
            # gate fired. Filtering the old list with geometry of our own was the
            # alternative; asking the right question is cleaner and keeps the judgment of
            # what counts as hanging where it belongs.
            after_report: PositionReport | None = None
            try:
                board_after = chess.Board(fen_before)
                move_played = chess.Move.from_uci(user_move)
                if move_played in board_after.legal_moves:
                    board_after.push(move_played)
                    after_report = self.engine.get_position_report(board_after.fen(), multipv=1)
            except Exception as e:
                logger.warning("evaluate_move: post-move position report failed: %s", e)
            # How often this turn's lesson has already closed a turn in this game.
            # Read before generating, recorded after — a turn the coach stays silent on
            # teaches nothing and must not count against the ladder.
            lesson_key, _lesson = composed_lesson(report)
            times_taught = self._lessons_taught[lesson_key] if lesson_key else 0
            # The body sentence gets its own count, keyed on the rendered clause rather
            # than the lesson category. v34 showed why both are needed: the takeaway
            # ladder worked and "attacking their undefended bishop on b4" still appeared
            # on five turns, because that sentence comes from the achievement clause.
            clause_key, _clause = composed_achievement(report)
            times_shown = self._lessons_taught[clause_key] if clause_key else 0
            for key, count, what in (
                (lesson_key, times_taught, "Lesson"),
                (clause_key, times_shown, "Achievement clause"),
            ):
                if count:
                    _trace(
                        "eval_lesson_repeat",
                        f"{what} {key!r} already used {count}x this game — "
                        + ("naming the recurrence" if count < LESSON_RETIRE_AFTER else "retiring it"),
                        tool="engine",
                    )
            prompt = build_rich_move_evaluation_prompt(
                report,
                level=self.level,
                guidance=guidance,
                guidance_facts=guidance_facts,
                lesson_times_taught=times_taught,
                achievement_times_shown=times_shown,
                history=self._piece_history,
                # The hanging pieces and threats for the position the move PRODUCES,
                # which is the one the coaching describes.
                position_after=after_report,
            )

            if self.template_only:
                from chess_coach.coaching_templates import generate_move_coaching as _gen_move_coaching_tmpl

                feedback = _gen_move_coaching_tmpl(report, level=self.level)
                _trace(
                    "eval_template",
                    f"Template feedback: {report.classification}",
                    tool="engine",
                )
            else:
                _trace(
                    "eval_llm_start",
                    f"LLM evaluating move ({len(prompt)} chars prompt)",
                    tool="llm",
                    model=getattr(self.llm, "model", "?"),
                    base_url=getattr(self.llm, "base_url", "?"),
                    llm_prompt=prompt,
                )
                t2 = time.perf_counter()
                try:
                    feedback = self._verified_move_feedback(
                        prompt,
                        report,
                        # Per-tier ceiling (lever 4): a serious mistake gets room
                        # to be specific; a sound move is kept short.
                        max_tokens=min(self.max_tokens, move_feedback_max_tokens(report)),
                        trace=_trace,
                        lesson_times_taught=times_taught,
                    )
                except Exception as e:
                    logger.warning("LLM failed for move evaluation (coaching path): %s — falling back to templates", e)
                    feedback = generate_move_coaching(report, level=self.level)
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

            # Record only when the coach actually said something. Counting a silent turn
            # would retire a lesson the student was never told, which is worse than
            # repeating it.
            #
            # Deliberately approximate in one direction: if generation raised and we fell
            # back to `generate_move_coaching`, the student got text that carries no
            # takeaway, yet this still counts. That over-counts on a rare path and can
            # retire a lesson one turn early. Erring toward less repetition is the safe
            # side of this trade, and the alternative — threading "did the delivered text
            # actually close on the lesson" back out of three fallback layers — buys
            # precision that the ladder (teach, name, stop) is too coarse to use.
            if feedback.strip():
                if lesson_key:
                    self._lessons_taught[lesson_key] += 1
                if clause_key:
                    self._lessons_taught[clause_key] += 1
                # Remember WHICH PIECE this turn was about, so a later turn can say the
                # student has been here before. Recorded against the position the move
                # was played in, and only on a turn that actually spoke.
                refuted = refuted_square(report)
                if refuted is not None:
                    self._piece_history.record_warning(fen_before, refuted, motif=lesson_key or "")

            return MoveEvaluation(
                classification=report.classification,
                eval_before_cp=report.best_eval_cp,
                eval_after_cp=report.user_eval_cp,
                eval_drop_cp=report.eval_drop_cp,
                feedback=feedback,
                _comparison=report,
                _position_report=pos_report,
            )

        # ----- UCI fallback path (existing two-analysis flow) -----

        # 1. Analyze position before user's move
        _trace(
            "eval_engine_before",
            "Analyzing position before move",
            tool="engine",
            input_fen=fen_before,
            depth=self.coaching_depth,
            commands=["force", f"setboard {fen_before}", "analyze"],
        )
        t0 = time.perf_counter()
        result_before = analyze_position(
            self.engine,
            fen_before,
            depth=self.coaching_depth,
            top_n=1,
        )
        t1 = time.perf_counter()
        logger.info("evaluate_move: engine analysis (before) took %.1fs", t1 - t0)
        eval_before = result_before.top_line.score_cp if result_before.top_line else 0
        best_before = result_before.best_move or "?"
        lines_before = [{"depth": ln.depth, "score_cp": ln.score_cp, "pv": ln.pv[:6]} for ln in result_before.lines]
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
            depth=self.coaching_depth,
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
            f"Move analyzed — eval: {eval_before}→{eval_after}cp, drop: {eval_drop}cp, {classification}",
            tool="engine",
            elapsed=t3 - t2,
            eval_before_cp=eval_before,
            eval_after_cp=eval_after,
            raw_eval_after_cp=raw_eval_after,
            eval_drop_cp=eval_drop,
            classification=classification,
        )

        # Skip LLM for good moves — no need to explain what's not wrong.
        # In the opening, engine eval at shallow depth is unreliable.
        # Same terminal-move exception as the coaching path above, applied here too so
        # the two paths cannot disagree about whether a won game gets a word.
        move_number = int(fen_before.split()[-1]) if fen_before.split() else 1
        ends_game = _move_ends_game(fen_before, user_move)
        if not ends_game and move_number <= 6 and eval_drop <= OPENING_LENIENCY_CP:
            _trace(
                "eval_skip_llm",
                f"Opening move (move {move_number}, drop {eval_drop}cp) — skipping LLM feedback",
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
        if not ends_game and eval_drop <= SOUND_MAX_DROP_CP:
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

        if self.template_only:
            feedback = ""
            _trace("eval_template", f"Template-only mode — skipping LLM ({classification})")
        else:
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
            try:
                feedback = self.llm.generate(
                    prompt,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                )
                if not feedback.strip():
                    raise ValueError("Empty LLM response")
            except Exception as e:
                logger.warning("LLM failed for move evaluation (UCI path): %s — falling back to empty", e)
                feedback = ""
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
                depth=self.coaching_depth,
                top_n=1,
            )
            t1 = time.perf_counter()
            lines_raw = [{"depth": ln.depth, "score_cp": ln.score_cp, "pv": ln.pv[:6]} for ln in result.lines]
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

        if self.template_only:
            return ""

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
            comparison = self.engine.get_comparison_report(fen, user_move, depth=self.coaching_depth)
            t_compare = time.perf_counter()

            # Build user feedback from comparison report
            if self.template_only:
                from chess_coach.coaching_templates import generate_move_coaching as _gen_move_coaching

                user_feedback = _gen_move_coaching(comparison, level=self.level)
            else:
                user_prompt = build_rich_move_evaluation_prompt(comparison, level=self.level)
                try:
                    user_feedback = self.llm.generate(
                        user_prompt,
                        max_tokens=self.max_tokens,
                        temperature=self.temperature,
                    )
                    if not user_feedback.strip():
                        raise ValueError("Empty LLM response")
                except Exception as e:
                    logger.warning("LLM failed for user feedback in play_move: %s — falling back to templates", e)
                    user_feedback = generate_move_coaching(comparison, level=self.level)
            t_user_llm = time.perf_counter()

            # 2. Push user's move to get new FEN
            board = chess.Board(fen)
            move = chess.Move.from_uci(user_move)
            board.push(move)
            fen_after_user = board.fen()

            # 2b. Get position report after user's move (NEW — for breakdown diff)
            user_pos_report = self.engine.get_position_report(
                fen_after_user, multipv=self.top_moves, depth=self.coaching_depth
            )
            t_user_eval = time.perf_counter()

            # Generate move impact text (what did the user's move change?)
            move_impact: str | None = None
            priority_advice: str | None = None
            user_move_insight = None
            if self._last_position_report is not None:
                from chess_coach.coaching_templates import (
                    generate_move_impact_text,
                    generate_priority_coaching,
                )
                from chess_coach.insights import extract_move_insight

                # Convert user move to SAN for display
                user_san = chess.Board(fen).san(chess.Move.from_uci(user_move))
                move_impact = generate_move_impact_text(
                    self._last_position_report, user_pos_report, user_move_san=user_san
                )
                priority_advice = generate_priority_coaching(user_pos_report, level=self.level)
                user_move_insight = extract_move_insight(
                    self._last_position_report,
                    user_pos_report,
                    user_move,
                    user_san,
                )

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

            pos_report = self.engine.get_position_report(
                fen_after_engine, multipv=self.top_moves, depth=self.coaching_depth
            )
            t_pos_report = time.perf_counter()

            opening = lookup_fen(fen_after_engine)
            opening_label = f"{opening.eco} {opening.name}" if opening else None
            coaching_prompt = build_rich_coaching_prompt(
                pos_report,
                level=self.level,
                opening_name=opening_label,
            )
            if self.template_only:
                from chess_coach.coaching_templates import generate_position_coaching as _gen_pos_coaching

                coaching_text = _gen_pos_coaching(pos_report, level=self.level, opening=opening)
            else:
                try:
                    coaching_text = self.llm.generate(
                        coaching_prompt,
                        max_tokens=self.max_tokens,
                        temperature=self.temperature,
                    )
                    if not coaching_text.strip():
                        raise ValueError("Empty LLM response")
                except Exception as e:
                    logger.warning("LLM failed for position coaching in play_move: %s — falling back to templates", e)
                    coaching_text = generate_position_coaching(pos_report, level=self.level, opening=opening)
            t_explain = time.perf_counter()

            # Save position report for next turn's breakdown diff
            self._last_position_report = pos_report

            eval_cp = pos_report.eval_cp
            eval_score = f"{eval_cp / 100:+.2f}"

            # Prepend move insight and priority advice to coaching text
            coaching_parts: list[str] = []
            if user_move_insight is not None:
                from chess_coach.insights import render_insight_text

                insight_text = render_insight_text(user_move_insight)
                if insight_text:
                    coaching_parts.append(insight_text)
            elif move_impact:
                coaching_parts.append(move_impact)
            if priority_advice:
                coaching_parts.append(priority_advice)
            if coaching_text:
                coaching_parts.append(coaching_text)
            coaching_text = "\n\n".join(coaching_parts) if coaching_parts else coaching_text

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
                "move_impact": move_impact,
                "priority_advice": priority_advice,
                "insight": user_move_insight.to_dict() if user_move_insight else None,
                "coaching_protocol": True,
                "timings": {
                    "comparison_report_s": round(t_compare - t_start, 2),
                    "user_feedback_llm_s": round(t_user_llm - t_compare, 2),
                    "user_eval_s": round(t_user_eval - t_user_llm, 2),
                    "engine_play_s": round(t_engine_play - t_user_eval, 2),
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
