"""Prompt templates for chess coaching."""

from __future__ import annotations

from chess_coach.models import (
    ComparisonReport,
    PositionReport,
)

SYSTEM_PROMPT = """\
You are an experienced chess coach. You explain positions clearly and help \
players understand strategic and tactical ideas. You focus on plans, piece \
activity, pawn structure, and concrete threats rather than just listing moves.

Adapt your language to the student's level:
- Beginner: simple terms, focus on basic tactics and piece safety
- Intermediate: discuss plans, pawn structure, piece coordination
- Advanced: nuanced positional ideas, prophylaxis, long-term strategy

IMPORTANT: Only use information provided in the engine analysis below. \
If the engine analysis is empty, incomplete, or missing lines, say so honestly \
(e.g. "The engine did not return analysis for this position."). \
Do NOT invent or fabricate analysis, move evaluations, or tactical ideas \
that are not supported by the data provided. Never describe a piece as being \
on a square unless the FEN confirms it. Never claim a move attacks, defends, \
or controls something unless you can verify it from the position.
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


MOVE_EVALUATION_PROMPT = """\
{system}

Student level: {level}

The student played a move in this position. Evaluate it briefly.

Position before the move (FEN): {fen_before}
Student's move: {user_move}
Position after the move (FEN): {fen_after}

Engine evaluation before the move: {eval_before} centipawns
Engine evaluation after the move: {eval_after} centipawns
Evaluation drop: {eval_drop} centipawns
Classification: {classification}

{analysis}

Based on this analysis, give brief feedback on the student's move. \
If the move was good, say so. If it was an inaccuracy or blunder, \
explain what was missed and suggest a better alternative. \
Keep your response concise (under 100 words).\
"""

ENGINE_MOVE_EXPLANATION_PROMPT = """\
{system}

Student level: {level}

The engine played a move. Explain the idea behind it.

Position before the move (FEN): {fen_before}
Engine's move: {engine_move}

{analysis}

Briefly explain why this move is good and what the engine's plan is. \
Keep your response concise (under 100 words).\
"""


def build_move_evaluation_prompt(
    fen_before: str,
    fen_after: str,
    user_move: str,
    eval_before: int,
    eval_after: int,
    eval_drop: int,
    classification: str,
    analysis_text: str,
    level: str = "intermediate",
) -> str:
    """Build the prompt for evaluating a user's move."""
    return MOVE_EVALUATION_PROMPT.format(
        system=SYSTEM_PROMPT,
        level=level,
        fen_before=fen_before,
        fen_after=fen_after,
        user_move=user_move,
        eval_before=eval_before,
        eval_after=eval_after,
        eval_drop=eval_drop,
        classification=classification,
        analysis=analysis_text,
    )


def build_engine_move_explanation_prompt(
    fen_before: str,
    engine_move: str,
    analysis_text: str,
    level: str = "intermediate",
) -> str:
    """Build the prompt for explaining an engine move."""
    return ENGINE_MOVE_EXPLANATION_PROMPT.format(
        system=SYSTEM_PROMPT,
        level=level,
        fen_before=fen_before,
        engine_move=engine_move,
        analysis=analysis_text,
    )


# ---------------------------------------------------------------------------
# Rich prompt templates for coaching protocol data
# ---------------------------------------------------------------------------

RICH_COACHING_PROMPT = """\
{system}

Student level: {level}

You are given a structured engine analysis of a chess position. Your job is \
to explain this analysis in plain language. Do NOT add your own analysis or \
invent ideas not present in the data below. Only explain what the engine found.

Position (FEN): {fen}
Overall evaluation: {eval_cp} centipawns

{sections}

{critical_section}\
Based on the data above, explain the position to the student. Cover the most \
important features first. Keep your response concise (under 200 words).\
"""

RICH_MOVE_EVALUATION_PROMPT = """\
{system}

Student level: {level}

You are given a structured comparison of the student's move against the \
engine's best move. Your job is to explain what the student missed. Do NOT \
re-analyze the position or add ideas not present in the data below.

Position (FEN): {fen}

Student's move: {user_move}
Student's move evaluation: {user_eval_cp} centipawns
Best move: {best_move}
Best move evaluation: {best_eval_cp} centipawns
Evaluation drop: {eval_drop_cp} centipawns
Classification: {classification}
Annotation: {nag}

What the best move achieves: {best_move_idea}

{sections}

{critical_section}\
Based on the data above, explain what the student missed and why the best \
move is stronger. Keep your response concise (under 100 words).\
"""


# ---------------------------------------------------------------------------
# Rich prompt builder helpers
# ---------------------------------------------------------------------------


def _format_eval_breakdown(report: PositionReport) -> str:
    """Format the eval breakdown section."""
    eb = report.eval_breakdown
    return (
        "--- Material Balance ---\n"
        f"Material: {eb.material} cp\n"
        "\n"
        "--- Piece Activity / Mobility ---\n"
        f"Mobility: {eb.mobility} cp"
    )


def _format_pawn_structure(report: PositionReport) -> str:
    """Format the pawn structure section."""
    lines = ["--- Pawn Structure ---"]
    for side in ("white", "black"):
        pf = report.pawn_structure[side]
        parts: list[str] = []
        if pf.isolated:
            parts.append(f"isolated on {', '.join(pf.isolated)}")
        if pf.doubled:
            parts.append(f"doubled on {', '.join(pf.doubled)}")
        if pf.passed:
            parts.append(f"passed on {', '.join(pf.passed)}")
        if parts:
            lines.append(f"{side.capitalize()}: {'; '.join(parts)}")
        else:
            lines.append(f"{side.capitalize()}: no notable features")
    return "\n".join(lines)


def _format_king_safety(report: PositionReport) -> str:
    """Format the king safety section."""
    lines = ["--- King Safety ---"]
    for side in ("white", "black"):
        ks = report.king_safety[side]
        lines.append(f"{side.capitalize()}: {ks.description} ({ks.score} cp)")
    return "\n".join(lines)


def _format_threats(report: PositionReport) -> str | None:
    """Format the threats section, or return None if no threats."""
    has_threats = any(len(report.threats.get(side, [])) > 0 for side in ("white", "black"))
    if not has_threats:
        return None
    lines = ["--- Threats ---"]
    for side in ("white", "black"):
        for threat in report.threats.get(side, []):
            lines.append(f"{side.capitalize()}: {threat.description}")
    return "\n".join(lines)


def _format_hanging_pieces(report: PositionReport) -> str | None:
    """Format the hanging pieces section, or return None if none."""
    has_hanging = any(len(report.hanging_pieces.get(side, [])) > 0 for side in ("white", "black"))
    if not has_hanging:
        return None
    lines = ["--- Hanging Pieces ---"]
    for side in ("white", "black"):
        for hp in report.hanging_pieces.get(side, []):
            lines.append(f"{side.capitalize()}: {hp.piece} on {hp.square} is hanging")
    return "\n".join(lines)


def _format_tactics(report: PositionReport) -> str | None:
    """Format the tactical motifs section, or return None if empty."""
    if not report.tactics:
        return None
    lines = ["--- Tactical Motifs ---"]
    for tactic in report.tactics:
        pv_note = " (in PV)" if tactic.in_pv else " (on board)"
        lines.append(f"{tactic.type}: {tactic.description}{pv_note}")
    return "\n".join(lines)


def _format_threat_map(report: PositionReport) -> str | None:
    """Format the threat map section, or return None if empty."""
    if not report.threat_map:
        return None
    lines = ["--- Piece Safety (Threat Map) ---"]
    for entry in report.threat_map:
        piece_str = entry.piece if entry.piece else "empty"
        status = "NET ATTACKED" if entry.net_attacked else "safe"
        lines.append(
            f"{entry.square} ({piece_str}): "
            f"W atk={entry.white_attackers} def={entry.white_defenders}, "
            f"B atk={entry.black_attackers} def={entry.black_defenders} "
            f"[{status}]"
        )
    return "\n".join(lines)


def _format_top_lines(report: PositionReport) -> str:
    """Format the top engine lines section."""
    lines = ["--- Top Engine Lines ---"]
    for i, pv in enumerate(report.top_lines, 1):
        moves_str = " ".join(pv.moves)
        lines.append(
            f"Line {i} (depth {pv.depth}, {pv.eval_cp} cp): {moves_str} — theme: {pv.theme}"
        )
    return "\n".join(lines)


def build_rich_coaching_prompt(report: PositionReport, level: str = "intermediate") -> str:
    """Build a rich coaching prompt from a PositionReport.

    Formats each section of the report conditionally — sections with no data
    (empty threats, no hanging pieces, no tactics, empty threat map) are
    omitted to keep the prompt concise.

    When ``critical_moment`` is True, the prompt includes language requesting
    a more detailed explanation from the LLM.

    Args:
        report: The structured position report from the engine.
        level: Student level (``"beginner"``, ``"intermediate"``, or
            ``"advanced"``).

    Returns:
        The complete prompt string ready to send to the LLM.
    """
    sections: list[str] = []

    # Always-present sections
    sections.append(_format_eval_breakdown(report))
    sections.append(_format_pawn_structure(report))
    sections.append(_format_king_safety(report))

    # Conditionally-present sections
    threats_section = _format_threats(report)
    if threats_section is not None:
        sections.append(threats_section)

    hanging_section = _format_hanging_pieces(report)
    if hanging_section is not None:
        sections.append(hanging_section)

    tactics_section = _format_tactics(report)
    if tactics_section is not None:
        sections.append(tactics_section)

    threat_map_section = _format_threat_map(report)
    if threat_map_section is not None:
        sections.append(threat_map_section)

    # Top lines always present
    sections.append(_format_top_lines(report))

    # Critical moment
    if report.critical_moment:
        critical_section = (
            "⚠ CRITICAL MOMENT: This position demands precise play. "
            f"Reason: {report.critical_reason}\n"
            "Please provide a MORE DETAILED explanation of this position, "
            "covering all key features and why accuracy matters here.\n\n"
        )
    else:
        critical_section = ""

    return RICH_COACHING_PROMPT.format(
        system=SYSTEM_PROMPT,
        level=level,
        fen=report.fen,
        eval_cp=report.eval_cp,
        sections="\n\n".join(sections),
        critical_section=critical_section,
    )


def _format_missed_tactics(report: ComparisonReport) -> str | None:
    """Format missed tactics section, or return None if empty."""
    if not report.missed_tactics:
        return None
    lines = ["--- Missed Tactics ---"]
    for tactic in report.missed_tactics:
        pv_note = " (in PV)" if tactic.in_pv else " (on board)"
        lines.append(f"{tactic.type}: {tactic.description}{pv_note}")
    return "\n".join(lines)


def _format_refutation_line(report: ComparisonReport) -> str | None:
    """Format refutation line section, or return None if not present."""
    if report.refutation_line is None:
        return None
    moves_str = " ".join(report.refutation_line)
    return f"--- Refutation Line ---\nOpponent's punishing response: {moves_str}"


def _format_comparison_top_lines(report: ComparisonReport) -> str:
    """Format the top engine lines from a ComparisonReport."""
    lines = ["--- Top Engine Lines ---"]
    for i, pv in enumerate(report.top_lines, 1):
        moves_str = " ".join(pv.moves)
        lines.append(
            f"Line {i} (depth {pv.depth}, {pv.eval_cp} cp): {moves_str} — theme: {pv.theme}"
        )
    return "\n".join(lines)


def build_rich_move_evaluation_prompt(report: ComparisonReport, level: str = "intermediate") -> str:
    """Build a rich move evaluation prompt from a ComparisonReport.

    Formats each section of the comparison report conditionally — missed
    tactics are omitted when empty, and the refutation line is omitted when
    None (non-blunder moves).

    When ``critical_moment`` is True, the prompt includes language requesting
    a more detailed explanation from the LLM.

    Args:
        report: The structured comparison report from the engine.
        level: Student level (``"beginner"``, ``"intermediate"``, or
            ``"advanced"``).

    Returns:
        The complete prompt string ready to send to the LLM.
    """
    sections: list[str] = []

    # Conditionally-present sections
    missed_section = _format_missed_tactics(report)
    if missed_section is not None:
        sections.append(missed_section)

    refutation_section = _format_refutation_line(report)
    if refutation_section is not None:
        sections.append(refutation_section)

    # Top lines for context
    sections.append(_format_comparison_top_lines(report))

    # Critical moment
    if report.critical_moment:
        critical_section = (
            "⚠ CRITICAL MOMENT: This was a critical decision point. "
            f"Reason: {report.critical_reason}\n"
            "Please provide a MORE DETAILED explanation of what was missed "
            "and why this moment was so important.\n\n"
        )
    else:
        critical_section = ""

    return RICH_MOVE_EVALUATION_PROMPT.format(
        system=SYSTEM_PROMPT,
        level=level,
        fen=report.fen,
        user_move=report.user_move,
        user_eval_cp=report.user_eval_cp,
        best_move=report.best_move,
        best_eval_cp=report.best_eval_cp,
        eval_drop_cp=report.eval_drop_cp,
        classification=report.classification,
        nag=report.nag,
        best_move_idea=report.best_move_idea,
        sections="\n\n".join(sections),
        critical_section=critical_section,
    )
