"""Prompt templates for chess coaching."""

from __future__ import annotations

SYSTEM_PROMPT = """\
You are an experienced chess coach. You explain positions clearly and help \
players understand strategic and tactical ideas. You focus on plans, piece \
activity, pawn structure, and concrete threats rather than just listing moves.

Adapt your language to the student's level:
- Beginner: simple terms, focus on basic tactics and piece safety
- Intermediate: discuss plans, pawn structure, piece coordination
- Advanced: nuanced positional ideas, prophylaxis, long-term strategy
"""

ANALYSIS_PROMPT_TEMPLATE = """\
{system}

Student level: {level}

Here is the current position and engine analysis:

{analysis}

Based on this analysis, please explain:
1. What is happening in this position? (key features, who stands better and why)
2. What is the best plan for the side to move?
3. Briefly explain the top move — why is it good?

Keep your response concise (under 200 words). Use plain language, not engine \
notation. Refer to pieces by name and squares when helpful.\
"""


def build_coaching_prompt(analysis_text: str, level: str = "intermediate") -> str:
    """Build the full prompt for the LLM."""
    return ANALYSIS_PROMPT_TEMPLATE.format(
        system=SYSTEM_PROMPT,
        level=level,
        analysis=analysis_text,
    )
