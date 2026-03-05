"""Tests for prompt construction."""

from __future__ import annotations

import pytest

from chess_coach.prompts import SYSTEM_PROMPT, build_coaching_prompt

SAMPLE_ANALYSIS = (
    "Side to move: White\n"
    "Material: White: Q R B N (5 pawns) | Black: Q R B N (5 pawns)\n"
    "Position: Normal\n"
    "Top line: 1. e4 e5 2. Nf3 (+0.35, depth 18)"
)

LEVELS = ["beginner", "intermediate", "advanced"]


class TestBuildCoachingPrompt:
    """Tests for build_coaching_prompt."""

    @pytest.mark.parametrize("level", LEVELS)
    def test_includes_analysis_text(self, level: str) -> None:
        result = build_coaching_prompt(SAMPLE_ANALYSIS, level)
        assert SAMPLE_ANALYSIS in result

    @pytest.mark.parametrize("level", LEVELS)
    def test_includes_level_string(self, level: str) -> None:
        result = build_coaching_prompt(SAMPLE_ANALYSIS, level)
        assert level in result

    @pytest.mark.parametrize("level", LEVELS)
    def test_includes_system_prompt(self, level: str) -> None:
        result = build_coaching_prompt(SAMPLE_ANALYSIS, level)
        assert SYSTEM_PROMPT in result

    @pytest.mark.parametrize("level", LEVELS)
    def test_includes_word_limit_guidance(self, level: str) -> None:
        result = build_coaching_prompt(SAMPLE_ANALYSIS, level)
        assert "200 words" in result

    @pytest.mark.parametrize("level", LEVELS)
    def test_returns_nonempty_string(self, level: str) -> None:
        result = build_coaching_prompt(SAMPLE_ANALYSIS, level)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_default_level_is_intermediate(self) -> None:
        result = build_coaching_prompt(SAMPLE_ANALYSIS)
        assert "intermediate" in result
