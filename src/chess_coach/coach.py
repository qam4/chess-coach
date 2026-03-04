"""Orchestrator: ties engine analysis to LLM coaching."""

from __future__ import annotations

from dataclasses import dataclass

from chess_coach.analyzer import analyze_position, format_analysis_for_llm
from chess_coach.engine import EngineProtocol
from chess_coach.llm.base import LLMProvider
from chess_coach.prompts import build_coaching_prompt


@dataclass
class CoachingResponse:
    """A coaching response for a position."""

    fen: str
    analysis_text: str
    coaching_text: str
    best_move: str
    score: str


class Coach:
    """Main coaching class: position → analysis → LLM → explanation."""

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

    def explain(self, fen: str) -> CoachingResponse:
        """Analyze a position and generate a coaching explanation."""
        # 1. Engine analysis
        result = analyze_position(
            self.engine, fen, depth=self.depth, top_n=self.top_moves,
        )

        # 2. Format for LLM
        analysis_text = format_analysis_for_llm(result, level=self.level)

        # 3. Build prompt and generate
        prompt = build_coaching_prompt(analysis_text, level=self.level)
        coaching_text = self.llm.generate(
            prompt, max_tokens=self.max_tokens, temperature=self.temperature,
        )

        score = result.top_line.score_str if result.top_line else "?"

        return CoachingResponse(
            fen=fen,
            analysis_text=analysis_text,
            coaching_text=coaching_text,
            best_move=result.best_move,
            score=score,
        )
