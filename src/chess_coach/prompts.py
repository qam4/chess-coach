"""Prompt templates for chess coaching."""

from __future__ import annotations

import chess

from chess_coach.coaching_phrases import (
    SOUND_MAX_DROP_CP,
    build_move_menu,
    describe_hanging,
    describe_king_safety,
    describe_move_menu,
    describe_pawn_structure,
    describe_placement,
    describe_tactic,
    describe_threat,
    king_safety_relevant,
    select_tactics,
    suppress_threats_echoing_tactics,
    uci_to_san,
)
from chess_coach.models import (
    ComparisonReport,
    PositionReport,
)
from chess_coach.pedagogy.inject import format_guidance_block
from chess_coach.pedagogy.resource import GuidanceEntry


def _safe_board(fen: str) -> chess.Board | None:
    """Parse a FEN into a board, or None if it is malformed."""
    try:
        return chess.Board(fen)
    except ValueError:
        return None


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


def build_coaching_prompt(
    analysis_text: str,
    level: str = "intermediate",
    opening_name: str | None = None,
) -> str:
    """Build the full prompt for the LLM."""
    if opening_name:
        analysis_text = f"Opening: {opening_name}\n\n{analysis_text}"
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
{perspective}
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
        perspective=_format_perspective(fen_before),
        engine_move=engine_move,
        analysis=analysis_text,
    )


# ---------------------------------------------------------------------------
# V2 system prompt — grounding, pedagogy, and tone for rich coaching
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_V2 = """\
You are a warm, encouraging chess coach who teaches students how to think \
about positions — not a computer that reports data. Your goal is to help \
the student improve by building their understanding and pattern recognition.

GROUNDING RULES (strict):
- Only use information from the engine data sections provided below.
- Never invent analysis, piece placements, or tactical ideas not in the data.
- Never describe a piece as being on a square unless the data confirms it.
- If the engine data is empty or incomplete, say so honestly.

CHESS PRINCIPLES (use these to frame your advice):
- Before you move, ask: "What does my opponent want?" Look for their threats.
- Fight for the center — pieces in the center control more squares.
- Develop pieces before attacking. Knights and bishops off the back rank first.
- Develop with threats when possible — make your opponent react to you.
- Castle early to protect your king and connect your rooks.
- Don't move the same piece twice in the opening without good reason.
- Every piece needs a defender. Before moving, check: is anything hanging?
- Trade pieces when you're ahead in material. Simplify to win.
- In the endgame, activate your king — it becomes a fighting piece.
- Passed pawns must be pushed. They're your ticket to a new queen.

PEDAGOGY:
- Teach the student how to think about the position (e.g., "ask yourself: \
is my king safe?" or "before moving, check if any of your pieces are \
undefended").
- Connect advice to the chess principles above — help the student build \
habits they can apply in every game.
- Acknowledge good aspects of the student's position before pointing out \
problems, when applicable.

TONE:
- Be warm, supportive, and encouraging — like a real coach, not a machine.
- Use positive framing: focus on what the student can do, not just what's wrong.
- Give concrete advice referencing specific squares and pieces rather than \
generic platitudes.
"""

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

RICH_COACHING_PROMPT_V2 = """\
{system}

Student level: {level}

You are given a structured engine analysis of a chess position. Use ONLY the \
data below — do not add your own analysis or invent ideas not present here.

Position (FEN): {fen}
Overall evaluation: {eval_cp} centipawns (from White's perspective: positive \
favors White, negative favors Black)
{perspective}

{sections}

COACHING INSTRUCTIONS:
- Prioritize: Focus on the 1-2 most important features of this position. \
Do not try to cover everything.
- Explain why: For each feature you highlight, explain why it matters — \
what are the consequences? What could happen if the student ignores it?
- Actionable advice: Suggest a concrete plan or idea the student can act on \
(e.g., "consider castling to get your king safe" rather than "king safety is low").
- Teach thinking patterns: Help the student learn how to evaluate positions \
themselves (e.g., "ask yourself: are all my pieces defended?").
- Connect to principles: Tie your advice to general chess principles the \
student can reuse in future games.
- Acknowledge strengths: If the student's position has good aspects, mention \
them before discussing problems.
- Notation: When you name a move, always use standard algebraic notation \
(SAN, e.g. Nf3, O-O, exd5) — never coordinates or "from-to" phrasing.
{move_sourcing}{level_instructions}\
{critical_section}\
Keep your response concise (under 200 words).\
"""

# Gated move-sourcing rule (Req 3.1, 3.2): appended to the coaching
# instructions only when the constraint is on AND the engine returned a
# candidate menu to name from. Keeps the coach's concrete moves engine-sound.
MOVE_SOURCING_RULE = (
    "- Choosing a move: When you recommend a specific move, name ONLY a move "
    'listed as "best" or "sound" in the candidate menu above. You may instead '
    'give a plan without naming a move (e.g. "castle to safety", "improve your '
    'worst-placed piece"). Never name a move that is not in the menu, and never '
    'recommend one tagged "dubious" or "blunder" (mention those only to warn '
    "against them).\n"
)

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

RICH_MOVE_EVALUATION_PROMPT_V2 = """\
{system}

Student level: {level}

You are given a structured comparison of the student's move against the \
engine's best move. Use ONLY the data below — do not re-analyze the position \
or add ideas not present here.

Position (FEN): {fen}
{perspective}

Student's move: {user_move}
Student's move evaluation: {user_eval_cp} centipawns
Best move: {best_move}
Best move evaluation: {best_eval_cp} centipawns
Evaluation drop: {eval_drop_cp} centipawns
Classification: {classification}
Annotation: {nag}

What the best move achieves: {best_move_idea}

{sections}

{move_instructions}\
{level_instructions}\
{critical_section}\
Keep your response concise (under 100 words).\
"""

# Instructions when the student's move was NOT the engine's best — explain the
# gap and why the best move is stronger.
_MOVE_EVAL_INSTRUCTIONS_INFERIOR = """\
COACHING INSTRUCTIONS:
- Constructive framing: Acknowledge what the student may have been trying to \
do before explaining what was missed.
- Explain what the move failed to address: What did the student's move allow \
the opponent to do, or what problem did it leave unsolved?
- Explain why the best move is stronger: What does it achieve or prevent, in \
concrete terms (specific squares, pieces, threats)?
- Stay grounded: Only reference facts present in the data above. Do not \
invent analysis, piece placements, or tactical ideas not in the data.
"""

# Instructions when the student PLAYED the engine's top move — affirm it and
# teach the idea; do NOT invent a "better" alternative (BUG-014).
_MOVE_EVAL_INSTRUCTIONS_BEST = """\
COACHING INSTRUCTIONS:
- The student played the engine's top move — there is no better move here. \
Do NOT suggest a different or "better" move, and do NOT imply the move was \
merely okay or that a superior alternative exists.
- Affirm the move clearly, then teach the idea behind it: what does it \
achieve or prepare (specific squares, pieces, plans)?
- Give the student a transferable principle they can reuse.
- Stay grounded: Only reference facts present in the data above. Do not \
invent analysis, piece placements, or tactical ideas not in the data.
"""

# Instructions when the student played a SOUND move — one that scores well in
# the engine's multi-line PV (small eval drop from best), even if it is not the
# single top move. Affirm it as a strong choice; do NOT second-guess it or push
# a marginally-preferred alternative (BUG-014, broadened beyond the exact best
# move). Distinct from _MOVE_EVAL_INSTRUCTIONS_BEST: we do not claim "no better
# move exists" because the engine's top line scores slightly higher.
_MOVE_EVAL_INSTRUCTIONS_SOUND = """\
COACHING INSTRUCTIONS:
- The student played a strong, sound move — it is among the engine's top \
choices and gives up nothing meaningful. Treat it as a good move: do NOT \
suggest a different or "better" move, and do NOT nitpick or imply the student \
should have played something else.
- Affirm the move clearly, then teach the idea behind it: what does it \
achieve or prepare (specific squares, pieces, plans)?
- Give the student a transferable principle they can reuse.
- Stay grounded: Only reference facts present in the data above. Do not \
invent analysis, piece placements, or tactical ideas not in the data.
"""


# ---------------------------------------------------------------------------
# Rich prompt builder helpers
# ---------------------------------------------------------------------------


def _uci_line_to_san(fen: str, ucis: list[str]) -> str:
    """Convert a UCI move sequence to a space-joined SAN line from ``fen``.

    Walks the position move by move; if any move is illegal/unparseable from
    the running position, that move and the remainder are emitted as raw UCI
    rather than guessing a wrong piece. Returns the original space-joined UCI
    if the base position itself is invalid.
    """
    try:
        board = chess.Board(fen)
    except (ValueError, AssertionError):
        return " ".join(ucis)
    out: list[str] = []
    for i, uci in enumerate(ucis):
        try:
            move = chess.Move.from_uci(uci)
            if move in board.legal_moves:
                out.append(board.san(move))
                board.push(move)
                continue
        except (ValueError, AssertionError):
            pass
        out.extend(ucis[i:])  # couldn't convert — emit this move and rest raw
        break
    return " ".join(out)


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


def _format_placement(fen: str) -> str | None:
    """Format the explicit piece-placement section, or None if FEN is bad.

    Gives the model the board as plain text (it can't reliably read the FEN),
    so it stops inventing pieces / mis-stating what's developed.
    """
    text = describe_placement(_safe_board(fen))
    if not text:
        return None
    return "--- Board (piece placement) ---\n" + text


def _format_pawn_structure(report: PositionReport) -> str:
    """Format the pawn structure section from composed sentences."""
    lines = ["--- Pawn Structure ---"]
    for side in ("white", "black"):
        sentence = describe_pawn_structure(report.pawn_structure[side], side)
        lines.append(sentence if sentence else f"{side.capitalize()} has no notable features.")
    return "\n".join(lines)


def _format_king_safety(report: PositionReport) -> str | None:
    """Format the king safety section from composed sentences, or None.

    Composed entirely from the engine's structured king-safety fields (never
    the prose ``description``). Suppressed wholesale in low-material endgames
    (``king_safety_relevant``), and per side when there is nothing
    coaching-worthy.
    """
    if not king_safety_relevant(report):
        return None
    lines = [
        s for side in ("white", "black") if (s := describe_king_safety(report.king_safety[side], side)) is not None
    ]
    if not lines:
        return None
    return "--- King Safety ---\n" + "\n".join(lines)


def _format_threats(report: PositionReport) -> str | None:
    """Format the threats section from composed sentences, or None if empty.

    Threats that merely restate a shown tactic are suppressed; the rest are
    composed from structured fields (never the prose ``description``).
    """
    board = _safe_board(report.fen)
    tactics = select_tactics(report.tactics)
    lines: list[str] = []
    for side in ("white", "black"):
        for threat in suppress_threats_echoing_tactics(report.threats.get(side, []), tactics):
            lines.append(describe_threat(threat, board))
    if not lines:
        return None
    return "--- Threats ---\n" + "\n".join(lines)


def _format_hanging_pieces(report: PositionReport) -> str | None:
    """Format the hanging pieces section from composed sentences, or None."""
    pieces = [describe_hanging(hp) for side in ("white", "black") for hp in report.hanging_pieces.get(side, [])]
    if not pieces:
        return None
    return "--- Hanging Pieces ---\n" + "\n".join(pieces)


def _format_tactics(report: PositionReport) -> str | None:
    """Format the tactical motifs section from composed sentences, or None.

    De-duplicated by motif identity (``select_tactics``) and composed from
    structured fields; the on-board vs in-PV distinction is carried in the
    composed sentence, never as a raw "(in PV)" token.
    """
    tactics = select_tactics(report.tactics)
    if not tactics:
        return None
    board = _safe_board(report.fen)
    lines = [describe_tactic(t, board) for t in tactics]
    return "--- Tactical Motifs ---\n" + "\n".join(lines)


def _format_threat_map(report: PositionReport) -> str | None:
    """Format the threat map section, or return None if empty.

    Only includes squares with pieces that are attacked by the opponent,
    to keep the prompt concise.  Empty squares and fully-safe pieces are
    omitted.
    """
    if not report.threat_map:
        return None
    lines = ["--- Piece Safety ---"]
    for entry in report.threat_map:
        if entry.piece is None:
            continue
        # Only show pieces that are attacked by the opposing side
        is_white_piece = entry.white_defenders > 0 or (entry.white_attackers == 0 and entry.black_attackers == 0)
        opponent_attackers = entry.black_attackers if is_white_piece else entry.white_attackers
        own_defenders = entry.white_defenders if is_white_piece else entry.black_defenders
        if opponent_attackers == 0:
            continue
        status = "UNDER-DEFENDED" if entry.net_attacked else "defended"
        lines.append(
            f"{entry.piece} on {entry.square}: attacked {opponent_attackers}x, defended {own_defenders}x [{status}]"
        )
    if len(lines) == 1:
        return None
    return "\n".join(lines)


def _build_level_instructions(level: str) -> str:
    """Build level-adaptive coaching instructions.

    Returns a string of additional instructions tailored to the student's
    skill level, to be inserted into the prompt template.

    Args:
        level: Student level (``"beginner"``, ``"intermediate"``, or
            ``"advanced"``).

    Returns:
        A string with level-specific instructions (may be empty for advanced).
    """
    parts: list[str] = []

    # Beginner-specific: simple language, one idea, avoid notation
    if level == "beginner":
        parts.append(
            "- Beginner student: Use simple, everyday language. Focus on ONE "
            "main idea at a time. Avoid chess notation beyond basic piece "
            "names (king, queen, rook, bishop, knight, pawn) and simple "
            "square references."
        )

    # Beginner + intermediate: avoid engine jargon
    if level in ("beginner", "intermediate"):
        parts.append(
            "- Avoid engine jargon: Do not mention centipawns, PV lines, "
            "depth numbers, or other engine-specific terminology. Translate "
            "engine concepts into plain language the student can understand."
        )

    if not parts:
        return ""
    return "\n".join(parts) + "\n"


def _format_perspective(fen: str) -> str:
    """Return a line naming whose turn it is and which side the student plays.

    Parsed from the FEN's active-color field. Without this, the prompt only
    conveys side-to-move implicitly (inside the FEN string) while all engine
    data is in absolute White/Black terms, so the LLM tends to narrate from
    White's side and attribute the opponent's pieces to the student (BUG-011).
    """
    parts = fen.split()
    active = parts[1].lower() if len(parts) > 1 else "w"
    student, opponent = ("Black", "White") if active == "b" else ("White", "Black")
    return (
        f"Side to move: {student}. You are coaching the player with the {student} "
        f'pieces — address them as "you" and refer to {opponent} as their opponent. '
        f"The engine data below labels items by color (White/Black); translate them "
        f"to the student's perspective."
    )


def build_rich_coaching_prompt(
    report: PositionReport,
    level: str = "intermediate",
    opening_name: str | None = None,
    guidance: list[GuidanceEntry] | None = None,
    constrain_moves: bool = True,
) -> str:
    """Build a rich coaching prompt from a PositionReport.

    Uses ``SYSTEM_PROMPT_V2`` with grounding, pedagogy, and tone instructions,
    and ``RICH_COACHING_PROMPT_V2`` with prioritization, causal explanation,
    actionable advice, and level-adaptive instructions.

    Formats each section of the report conditionally — sections with no data
    (empty threats, no hanging pieces, no tactics, empty threat map) are
    omitted to keep the prompt concise.

    When ``critical_moment`` is True, the prompt includes language requesting
    a more detailed explanation from the LLM.

    When ``guidance`` is supplied and non-empty, the selector-chosen guidance
    entries are rendered into a leading "What to focus on" block carrying both
    ends of the teaching bridge — each entry's named theme and its
    how-to-apply statement (Req 3.1, 3.2). The block is inserted *alongside*
    the existing engine-grounding instructions, which are never removed or
    weakened (Req 3.4). Entries whose recorded levels exclude ``level`` are
    dropped (Req 3.3); when ``guidance`` is ``None``/empty, or becomes empty
    after that filter, the prompt is built exactly as today with grounding
    intact and no guidance block (Req 3.6, 3.7).

    Args:
        report: The structured position report from the engine.
        level: Student level (``"beginner"``, ``"intermediate"``, or
            ``"advanced"``).
        opening_name: Optional opening name to include in the prompt.
        guidance: Optional selector-chosen guidance entries to inject as a
            leading focus block.

    Returns:
        The complete prompt string ready to send to the LLM.
    """
    sections: list[str] = []

    # Curated guidance (the "what to focus on" half of the teaching bridge),
    # level-filtered (Req 3.3). Inserted first so the coach leads with the
    # selected themes; the engine-grounding instructions below are untouched
    # (Req 3.4). An empty selection adds nothing (Req 3.6, 3.7).
    guidance_block = format_guidance_block(guidance or [], level=level)
    if guidance_block:
        sections.append(guidance_block)

    # Opening identification (if known)
    if opening_name:
        sections.append(f"--- Opening ---\n{opening_name}")

    # Explicit board placement first — the model cannot reliably read FEN,
    # so give it the pieces as plain text before any analysis.
    placement_section = _format_placement(report.fen)
    if placement_section is not None:
        sections.append(placement_section)

    # Always-present sections
    sections.append(_format_eval_breakdown(report))
    sections.append(_format_pawn_structure(report))

    # Conditionally-present sections
    king_safety_section = _format_king_safety(report)
    if king_safety_section is not None:
        sections.append(king_safety_section)

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

    # Candidate move menu (engine-verified, soundness-tagged). Replaces the
    # raw "Top Engine Lines" — the coach names concrete moves from this menu.
    menu = build_move_menu(report)
    menu_section = describe_move_menu(menu)
    if menu_section is not None:
        sections.append(menu_section)

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

    # Level-adaptive instructions
    level_instructions = _build_level_instructions(level)

    # Move-sourcing rule only when the constraint is on and there is a menu to
    # name from (an empty menu means no sound move to recommend).
    move_sourcing = MOVE_SOURCING_RULE if (constrain_moves and menu) else ""

    return RICH_COACHING_PROMPT_V2.format(
        system=SYSTEM_PROMPT_V2,
        level=level,
        fen=report.fen,
        eval_cp=report.eval_cp,
        perspective=_format_perspective(report.fen),
        sections="\n\n".join(sections),
        level_instructions=level_instructions,
        move_sourcing=move_sourcing,
        critical_section=critical_section,
    )


SOCRATIC_SYSTEM_PROMPT = """\
You are a Socratic chess coach. You do NOT tell the student the answer, the \
best move, or the evaluation. Instead you ask short, guiding questions that \
lead the student to notice the important features of the position themselves \
and reach the idea on their own.

GROUNDING RULES (strict):
- Base every question ONLY on the engine data sections provided below.
- Never invent threats, piece placements, or tactical ideas not in the data.
- Never reveal or name the best move, the winning plan, or the numeric \
evaluation — not even as a hint phrased as a question.
- If the data has no concrete features, ask a general orienting question \
(about development or king safety) rather than inventing specifics.

HOW TO ASK:
- Ask 2-3 short questions, each pointing the student toward one real feature \
in the data (a threat, an undefended piece, king safety, pawn structure).
- Order them from what to notice first toward what to do about it.
- Be warm and encouraging; end with a brief nudge to look for themselves.
"""

SOCRATIC_COACHING_PROMPT_V2 = """\
{system}

Student level: {level}

Below is structured engine analysis of a chess position. Use ONLY this data \
to decide what to ask. Do NOT explain the position, state the evaluation, or \
name the best move — ask guiding questions instead.

Position (FEN): {fen}
{perspective}

{sections}

SOCRATIC INSTRUCTIONS:
- Ask 2-3 short guiding questions that lead the student toward the key \
idea(s) in the data above, without revealing them.
- Each question should point at a real feature (a threat, an undefended \
piece, king safety, a pawn weakness) — never invent one.
- Do not give the answer, the best move, or the evaluation; make the student \
do the noticing.
- End with one short, encouraging nudge to look at the board.
{level_instructions}\
Keep it brief: at most 3 questions, no lecturing.\
"""


def build_socratic_prompt(
    report: PositionReport,
    level: str = "intermediate",
    opening_name: str | None = None,
) -> str:
    """Build a Socratic coaching prompt — guiding questions, not answers.

    Includes the qualitative engine features (threats, hanging pieces, tactics,
    threat map, king safety, pawn structure) so the questions stay grounded,
    but deliberately OMITS the top engine lines, the eval breakdown numbers,
    and the overall evaluation so the LLM cannot hand the student the answer.
    The engine holds the answer key; the coach only asks.

    Args:
        report: The structured position report from the engine.
        level: Student level (``"beginner"``, ``"intermediate"``, or
            ``"advanced"``).
        opening_name: Optional opening name to include.

    Returns:
        The complete Socratic prompt string ready to send to the LLM.
    """
    sections: list[str] = []
    if opening_name:
        sections.append(f"--- Opening ---\n{opening_name}")

    placement_section = _format_placement(report.fen)
    if placement_section is not None:
        sections.append(placement_section)

    # Qualitative, answer-free feature sections only — no top lines, no eval
    # breakdown numbers, no overall evaluation.
    threats = _format_threats(report)
    if threats is not None:
        sections.append(threats)
    hanging = _format_hanging_pieces(report)
    if hanging is not None:
        sections.append(hanging)
    tactics = _format_tactics(report)
    if tactics is not None:
        sections.append(tactics)
    threat_map = _format_threat_map(report)
    if threat_map is not None:
        sections.append(threat_map)
    king_safety_section = _format_king_safety(report)
    if king_safety_section is not None:
        sections.append(king_safety_section)
    sections.append(_format_pawn_structure(report))

    return SOCRATIC_COACHING_PROMPT_V2.format(
        system=SOCRATIC_SYSTEM_PROMPT,
        level=level,
        fen=report.fen,
        perspective=_format_perspective(report.fen),
        sections="\n\n".join(sections),
        level_instructions=_build_level_instructions(level),
    )


def _format_missed_tactics(report: ComparisonReport) -> str | None:
    """Format missed tactics from composed sentences, or None if empty."""
    tactics = select_tactics(report.missed_tactics)
    if not tactics:
        return None
    board = _safe_board(report.fen)
    lines = [describe_tactic(t, board) for t in tactics]
    return "--- Missed Tactics ---\n" + "\n".join(lines)


def _format_refutation_line(report: ComparisonReport) -> str | None:
    """Format refutation line section, or return None if not present."""
    if report.refutation_line is None:
        return None
    # The refutation is the opponent's reply to the student's move, so render it
    # in SAN from the position AFTER that move; fall back to report.fen if the
    # student's move can't be applied.
    base_fen = report.fen
    try:
        board = chess.Board(report.fen)
        board.push_uci(report.user_move)
        base_fen = board.fen()
    except (ValueError, AssertionError):
        base_fen = report.fen
    moves_str = _uci_line_to_san(base_fen, report.refutation_line)
    return f"--- Refutation Line ---\nOpponent's punishing response: {moves_str}"


def _format_comparison_top_lines(report: ComparisonReport) -> str:
    """Format the top engine lines from a ComparisonReport."""
    lines = ["--- Top Engine Lines ---"]
    for i, pv in enumerate(report.top_lines, 1):
        moves_str = _uci_line_to_san(report.fen, pv.moves)
        lines.append(f"Line {i} (depth {pv.depth}, {pv.eval_cp} cp): {moves_str} — theme: {pv.theme}")
    return "\n".join(lines)


def build_rich_move_evaluation_prompt(
    report: ComparisonReport,
    level: str = "intermediate",
    guidance: list[GuidanceEntry] | None = None,
) -> str:
    """Build a rich move evaluation prompt from a ComparisonReport.

    Uses ``SYSTEM_PROMPT_V2`` with grounding, pedagogy, and tone instructions,
    and ``RICH_MOVE_EVALUATION_PROMPT_V2`` with constructive framing, concrete
    explanation of what the move failed to address, and why the best move is
    stronger.

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

    # Curated guidance (the "what to focus on" half of the teaching bridge),
    # level-filtered. Inserted first so the move feedback LEADS with the
    # selected themes; the engine-grounding instructions below are untouched.
    # An empty selection adds nothing, so feedback is unchanged without guidance.
    guidance_block = format_guidance_block(guidance or [], level=level)
    if guidance_block:
        sections.append(guidance_block)

    placement_section = _format_placement(report.fen)
    if placement_section is not None:
        sections.append(placement_section)

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

    # Level-adaptive instructions
    level_instructions = _build_level_instructions(level)

    # Do not second-guess a move that scores well in the engine's multi-line
    # PV, not only the single top move (BUG-014). Three cases:
    #   - exact top move  -> affirm, "there is no better move here".
    #   - sound move (eval drop from best within SOUND_MAX_DROP_CP) -> affirm
    #     as a strong choice; don't push the engine's marginally-preferred line.
    #   - otherwise (dubious/blunder) -> explain the gap and the stronger move.
    if report.user_move == report.best_move:
        move_instructions = _MOVE_EVAL_INSTRUCTIONS_BEST
    elif report.eval_drop_cp <= SOUND_MAX_DROP_CP:
        move_instructions = _MOVE_EVAL_INSTRUCTIONS_SOUND
    else:
        move_instructions = _MOVE_EVAL_INSTRUCTIONS_INFERIOR

    return RICH_MOVE_EVALUATION_PROMPT_V2.format(
        system=SYSTEM_PROMPT_V2,
        level=level,
        fen=report.fen,
        perspective=_format_perspective(report.fen),
        user_move=uci_to_san(report.fen, report.user_move),
        user_eval_cp=report.user_eval_cp,
        best_move=uci_to_san(report.fen, report.best_move),
        best_eval_cp=report.best_eval_cp,
        eval_drop_cp=report.eval_drop_cp,
        classification=report.classification,
        nag=report.nag,
        best_move_idea=report.best_move_idea,
        sections="\n\n".join(sections),
        move_instructions=move_instructions,
        level_instructions=level_instructions,
        critical_section=critical_section,
    )
