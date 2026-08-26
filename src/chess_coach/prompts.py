"""Prompt templates for chess coaching."""

from __future__ import annotations

import logging

import chess

from chess_coach.coaching_phrases import (
    DUBIOUS_MAX_DROP_CP,
    EQUAL_MAX_DROP_CP,
    SOUND_MAX_DROP_CP,
    build_move_menu,
    describe_eval,
    describe_hanging,
    describe_king_safety,
    describe_move_menu,
    describe_pawn_structure,
    describe_pawn_structure_from_board,
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
from chess_coach.pedagogy.features import PHASE_ENDGAME, PHASE_OPENING, phase_of_board
from chess_coach.pedagogy.inject import format_guidance_block
from chess_coach.pedagogy.instantiate import feature_facts
from chess_coach.pedagogy.resource import GuidanceEntry

logger = logging.getLogger(__name__)


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
- Do not narrate "and then..." move sequences or follow-up variations unless \
those exact moves appear in the engine lines above. Explain the plan or idea \
in words rather than inventing concrete continuations — a made-up line is the \
most misleading error you can make.
- If the engine data is empty or incomplete, say so honestly.

PEDAGOGY:
- Teach the student how to think about the position (e.g., "before moving, \
check if any of your pieces are undefended" or "ask yourself: what is my \
opponent threatening?").
- Connect advice to a general chess principle — help the student build \
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

# NOTE: the v1 rich templates (``RICH_COACHING_PROMPT`` and
# ``RICH_MOVE_EVALUATION_PROMPT``) were deleted here. They had no call site left —
# every path builds the V2 prompt — but they were not harmless dead code:
# ``engine_trust`` recorded ``ComparisonReport.best_move_idea`` as DROPPED_PARTIAL
# *because* the v1 move template still rendered it, and dead text is exactly how a
# dropped field creeps back. Deleting them turns that partial drop into a real one.

RICH_COACHING_PROMPT_V2 = """\
{system}

Student level: {level}

You are given a structured engine analysis of a chess position. Use ONLY the \
data below — do not add your own analysis or invent ideas not present here.

Position (FEN): {fen}
{standing}
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

# No evaluations, no eval drop, no engine classification, no NAG.
#
# Measured, not stylistic. Blunder's reported cp are not conventional centipawns
# (a pawn is 124 MG to 206 EG, unnormalized), and against Stockfish 18 the
# magnitude carries a signed +122cp error on the turns the coach actually speaks,
# with a 50-60cp residual under every conversion we tried — wider than the 50/100
# bands we were sorting moves into. So "Evaluation drop: 90 centipawns" asserted a
# precision we do not have, and "Classification: inaccuracy" relayed the engine's
# verdict computed on those same units with cut points of unknown provenance.
#
# They are WITHHELD rather than accompanied by an instruction not to repeat them.
# Three ledger rows say that is the only thing that works on this model: a bare
# grounding rule against invented causes did nothing (row 2), renaming a header the
# model kept copying made it worse (0 -> 6 -> 8 echoes, row 39), and removing the
# header outright fixed it (8 -> 0, row 41).
#
# What survives is the engine's move ORDERING, which is what a 2500 engine is
# actually good at, and the board-derived clauses in ``{best_move_line}`` and the
# sections — facts a student can check on the board. Severity now reaches the model
# only through the tier's tone and word limit, not as a number it can quote.
RICH_MOVE_EVALUATION_PROMPT_V2 = """\
{system}

Student level: {level}

You are given a structured comparison of the student's move against the \
engine's preferred move. Use ONLY the data below — do not re-analyze the \
position or add ideas not present here.

Position (FEN): {fen}
{perspective}

Student's move: {user_move}
{alternative_line}{best_move_line}
{sections}

{move_instructions}\
{takeaway_instruction}
{level_instructions}\
{critical_section}\
Keep your response concise (under {word_limit} words).\
"""

# Severity-tiered move-feedback instructions (lever 3). The response's
# directness AND length scale with how far the move fell short, so a blunder and
# a best move never read the same. Tiers are chosen from OUR own eval-drop bands
# (SOUND_MAX_DROP_CP / DUBIOUS_MAX_DROP_CP) — never the engine's classification
# label, whose thresholds are the engine's to change (BUG-016). No motivational
# sign-offs in any tier (they were pure filler that diluted the signal).

# Student PLAYED the engine's top move — affirm briefly, never invent a "better"
# alternative (BUG-014).
_MOVE_EVAL_INSTRUCTIONS_BEST = """\
COACHING INSTRUCTIONS:
- The student played the engine's top move — there is no better move here. \
Do NOT suggest a different or "better" move, and do NOT imply a superior \
alternative exists.
- Keep it SHORT (1-2 sentences): affirm the move, then state the specific idea \
it achieves — use the line above stating what the move does (that is this \
move) — not a generic principle. No motivational sign-off.
- Stay grounded: only facts in the data above; no invented analysis, \
placements, tactics, or "and then..." continuations.
"""

# Student's move was EQUAL to the engine's in practical terms (drop under
# EQUAL_MAX_DROP_CP). No alternative is named and none is described in the prompt,
# so there is nothing to compare against — the positive form of the rule, because
# an instruction NOT to mention something we supplied has never worked on this
# model (lever 2), while withholding it has.
_MOVE_EVAL_INSTRUCTIONS_EQUAL = """\
COACHING INSTRUCTIONS:
- The student's move is as good as anything else here. Endorse it and move on. \
Do NOT offer an alternative, a refinement, or a "better" move — there isn't one.
- Keep it SHORT (1-2 sentences): say what their move achieves, using the line \
above stating what the move does, then the takeaway. Write it in your own words. \
No motivational sign-off.
- Stay grounded: only facts in the data above; no invented analysis, \
placements, tactics, or "and then..." continuations.
"""

# Student played a SOUND move (small eval drop, not the top move). Affirm; a
# genuinely better move may be noted as a refinement, never a rebuke (BUG-016).
_MOVE_EVAL_INSTRUCTIONS_SOUND = """\
COACHING INSTRUCTIONS:
- The student played a sound, reasonable move — do NOT call it a mistake or \
invent a correction the data does not support.
- Keep it SHORT (2-3 sentences): affirm it and state the specific idea it \
achieves (use the line above stating what the move does), not a generic \
principle. If the engine's top move differs, you may briefly point it out as a \
refinement — affirm first, never imply the move was bad. No motivational \
sign-off.
- Stay grounded: only facts in the data above; no invented analysis, \
placements, tactics, or "and then..." continuations.
"""

# Student's move fell short, but by how much is NOT something we can state. The two
# lower tiers used to assert a size — "a small inaccuracy, not a disaster" and "this
# was a serious mistake" — and those are the sentences the measurement took away: on
# the 18 turns the coach spoke in one game, at least 7 criticised a move Stockfish
# scores good or near-good, and the residual under every conversion is as wide as the
# band that separates these two tiers. So neither claims a size. What they lead with
# instead is the board-verified consequence, which is a fact either way: if the
# opponent's reply wins a rook, saying so IS the severity, and the student can check
# it. The tiers still differ, in directness and in length.
_MOVE_EVAL_INSTRUCTIONS_INACCURACY = """\
COACHING INSTRUCTIONS:
- There was a stronger move here. Give a BRIEF redirect (2-3 sentences): \
acknowledge the intent in a few words, then name the stronger move and its \
specific idea — use the line above stating what the move does — not a generic \
principle. No motivational sign-off.
- Do NOT grade the move or say how much it cost. Do not call it an \
inaccuracy, a mistake or a blunder, and do not quantify what was lost. \
Describe what the stronger move does; that is the lesson.
- Stay grounded: only facts in the data above; no invented analysis, \
placements, tactics, or "and then..." continuations.
"""

_MOVE_EVAL_INSTRUCTIONS_SERIOUS = """\
COACHING INSTRUCTIONS:
- This move let something concrete happen. Do NOT open with praise or "great \
job". Lead with the consequence: if an "Opponent's reply" is shown, name that \
single reply ("after your move, the opponent plays X") and what it wins, using \
the threats shown. Do NOT list a longer sequence of moves.
- Then give the concrete better move and the specific idea it achieves \
(squares, pieces, threats). Be direct and specific, not generic. No \
motivational sign-off.
- Do NOT grade the move or say how much it cost. Do not call it an \
inaccuracy, a mistake or a blunder, and do not quantify what was lost. The \
reply and what it wins are the cost, stated as a fact the student can check.
- Stay grounded: only facts in the data above; no invented analysis, \
placements, tactics, or "and then..." continuations.
"""


# Lever 4 — enforce response depth/length per severity tier (prompt text alone
# under-delivered: the model wrote 3-5 sentences regardless). Each tier gets a
# tight WORD LIMIT (the prominent final instruction the model follows) plus a
# MAX_TOKENS ceiling (a mechanical backstop, sized well above the word target so
# it caps runaway length without truncating a normal answer). A best move gets
# The exact phrases the tier blocks above use to point at the achievement line.
# Kept as constants so dropping that line can redirect the reference instead of
# leaving the model pointed at a section that is not in the prompt.
_ACHIEVEMENT_REFERENCES = ("the line above stating what the move does",)

# one sentence; a serious mistake gets room to be specific.
_TIER_INSTRUCTIONS = {
    "best": _MOVE_EVAL_INSTRUCTIONS_BEST,
    "equal": _MOVE_EVAL_INSTRUCTIONS_EQUAL,
    "sound": _MOVE_EVAL_INSTRUCTIONS_SOUND,
    "inaccuracy": _MOVE_EVAL_INSTRUCTIONS_INACCURACY,
    "serious": _MOVE_EVAL_INSTRUCTIONS_SERIOUS,
}
_TIER_WORD_LIMIT = {"best": 40, "equal": 40, "sound": 55, "inaccuracy": 80, "serious": 120}
_TIER_MAX_TOKENS = {"best": 120, "equal": 120, "sound": 150, "inaccuracy": 200, "serious": 300}

#: Tiers where the coach describes the STUDENT's move rather than the engine's,
#: because no comparison is being made.
_OWN_MOVE_TIERS = frozenset({"best", "equal"})


def _move_feedback_tier(report: ComparisonReport) -> str:
    """Severity tier for a played move, from OUR own eval-drop bands (BUG-016).

    ``best`` (played the engine's top move) / ``sound`` (small drop) /
    ``inaccuracy`` (within the dubious band) / ``serious`` (past it). Shared by
    the instruction, word-limit, and max-tokens selection so they never drift.
    """
    if report.user_move == report.best_move:
        return "best"
    if report.eval_drop_cp <= EQUAL_MAX_DROP_CP:
        return "equal"
    if report.eval_drop_cp <= SOUND_MAX_DROP_CP:
        return "sound"
    if report.eval_drop_cp <= DUBIOUS_MAX_DROP_CP:
        return "inaccuracy"
    return "serious"


def move_feedback_max_tokens(report: ComparisonReport) -> int:
    """Per-tier generation ceiling for move feedback (lever 4).

    Callers (the runtime coach, the report-card driver) pass this as
    ``max_tokens`` so a best-move reply is short and a serious-mistake reply has
    room to be specific — enforcing the length differentiation the prompt text
    alone did not achieve.
    """
    return _TIER_MAX_TOKENS[_move_feedback_tier(report)]


# ---------------------------------------------------------------------------
# Rich prompt builder helpers
# ---------------------------------------------------------------------------


def _uci_line_to_san(fen: str, ucis: list[str]) -> str:
    """Convert a UCI move sequence to a space-joined SAN line from ``fen``.

    **Never emits raw UCI.** Walks the position move by move and TRUNCATES at the
    first move that is illegal/unparseable from the running position, appending
    ``...`` to show the line was cut. Raw coordinates are unreadable for a
    student and invite the model to guess the wrong piece, so a short valid SAN
    prefix is strictly better than a long broken one.

    Truncation happens for real reasons beyond a caller mistake: the engine can
    emit an internally inconsistent PV (observed: ``... c6b4 e8g8 ...`` — two
    Black moves in a row, a missing White ply), so the tail genuinely cannot be
    replayed. Returns ``""`` when not even the first move converts; callers omit
    the section rather than print an empty line.
    """
    try:
        board = chess.Board(fen)
    except (ValueError, AssertionError):
        logger.warning("SAN conversion skipped: invalid base FEN %r (%d moves dropped)", fen, len(ucis))
        return ""
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
        logger.warning(
            "SAN line truncated at move %d (%r) from %r — unreplayable (engine PV inconsistency?)",
            i,
            uci,
            fen,
        )
        if out:
            out.append("...")
        break
    return " ".join(out)


def _uci_line_to_numbered_san(fen: str, ucis: list[str]) -> str:
    """Like :func:`_uci_line_to_san` but with move numbers marking WHOSE move.

    A bare SAN sequence hides side: given ``Nfg4 f4 Nxc4`` the model grabbed
    ``f4`` — the STUDENT's move — and announced "the opponent plays f4".
    Numbering makes the alternation explicit, using the standard convention
    where a line starting on Black's move is written ``12...Nfg4 13.f4``.

    The move number and side come from the board (``fullmove_number`` /
    ``turn``), never inferred from position in the list — an off-by-one here
    would be exactly the kind of silent wrongness this whole fix chased.
    Truncation semantics match :func:`_uci_line_to_san`: stop at the first
    unreplayable move, append ``...``, and return ``""`` if nothing converts.
    """
    try:
        board = chess.Board(fen)
    except (ValueError, AssertionError):
        logger.warning("numbered SAN skipped: invalid base FEN %r (%d moves dropped)", fen, len(ucis))
        return ""
    out: list[str] = []
    for i, uci in enumerate(ucis):
        try:
            move = chess.Move.from_uci(uci)
            if move in board.legal_moves:
                number = board.fullmove_number
                white_to_move = board.turn == chess.WHITE
                san = board.san(move)
                if white_to_move:
                    out.append(f"{number}.{san}")
                elif not out:
                    # Line opens on Black's move: "12...Nfg4".
                    out.append(f"{number}...{san}")
                else:
                    out.append(san)
                board.push(move)
                continue
        except (ValueError, AssertionError):
            pass
        logger.warning(
            "numbered SAN line truncated at move %d (%r) from %r — unreplayable (engine PV inconsistency?)",
            i,
            uci,
            fen,
        )
        if out:
            out.append("...")
        break
    return " ".join(out)


# NOTE: there is deliberately no material section here any more.
#
# The old one printed the engine's own `material` and `mobility` terms as "N cp",
# both in Blunder units where a pawn is 124 (MG) to 206 (EG) — so "Material: 206"
# read as two pawns and meant one. Those are gone for the reasons in row 63.
#
# A first replacement counted material from the board in points, and that was the
# wrong instinct: it is chess logic in the wrong repo. The agreed division of labour
# (BACKLOG, 2026-08-21) is that when engine data cannot be trusted we DROP it, record
# the drop, and accept a quieter coach until the engine improves — not that we build a
# substitute. Piece values are contested knowledge, and `pedagogy.features` already
# restricts its own copy of them to keying guidance, "never to evaluate a position".
#
# Nothing is actually lost from the model's point of view: the placement block above
# lists every piece on both sides, so material is countable from what it already has,
# and any claim it makes about the board is checked by verify.py before the student
# sees it. Supply facts, let the model reason, verify the output.


def _format_placement(fen: str) -> str | None:
    """Format the explicit piece-placement section, or None if FEN is bad.

    Gives the model the board as plain text (it can't reliably read the FEN),
    so it stops inventing pieces / mis-stating what's developed.
    """
    board = _safe_board(fen)
    text = describe_placement(board)
    if not text:
        return None
    # Mark which side list is the student's, in the block itself. The side names
    # were already there, but on the line ABOVE the developed/home summary, and the
    # model did not carry them down: at v27 ply 44 it called Black's b4 bishop "your
    # own bishop on b4" while the prompt listed it under "Black:" with the summary
    # line "developed minors: Bb4" carrying no side at all. A frontier review named
    # the cause as facts reaching the model without an owner. Labelling costs
    # nothing and removes the guess.
    if board is not None:
        student = "White" if board.turn == chess.WHITE else "Black"
        opponent = "Black" if board.turn == chess.WHITE else "White"
        text = text.replace(f"\n{student}:", f"\n{student} (YOURS — the student):").replace(
            f"\n{opponent}:", f"\n{opponent} (THEIRS — the opponent):"
        )
    return "--- Board (piece placement) ---\n" + text


def _format_pawn_structure_grounding(fen: str) -> str | None:
    """Board-derived isolated/doubled pawn facts, or None if unavailable.

    Grounds the coach's pawn-structure claims (isolated/doubled) so it states
    the fact instead of guessing — the move-eval ComparisonReport carries no
    pawn-structure data, so it is composed from the board here (BUG-018).
    """
    text = describe_pawn_structure_from_board(_safe_board(fen))
    return text or None


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

    # Beginner + intermediate: plain language, and no invented numbers.
    #
    # This used to enumerate "centipawns, PV lines, depth numbers" — all things the
    # prompt itself was handing over three sections earlier, which made it an
    # instruction not to repeat our own data, the one shape of constraint this model
    # reliably ignores. None of them are supplied any more, so the enumeration is
    # stale; what remains is about the model's OWN vocabulary, where it can still
    # produce a rating out of its pretraining even though nothing here suggests one.
    if level in ("beginner", "intermediate"):
        parts.append(
            "- Plain language, no engine jargon: describe what is happening "
            "on the board in words the student can check against the pieces. "
            "Do not rate the position or the move with a number or a score."
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
    # Instantiate each theme with the board fact that fired it. This path has
    # the PositionReport in hand, so it composes the facts itself. Hypothesis
    # being tested: instantiation should matter MORE here than on the move-eval
    # path, because position coaching has no specific move to anchor to.
    guidance_block = format_guidance_block(guidance or [], level=level, facts=feature_facts(report))
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
        # ``critical_reason`` is deliberately not passed on, matching the move path.
        # Its only format is "eval spread between best and 3rd-best line is 107cp" —
        # our own bookkeeping in units that are not centipawns. Handed it, the coach
        # dutifully voiced it. This was the last live half of that drop:
        # engine_trust recorded it as DROPPED_PARTIAL, suppressed on the move path
        # and still rendered here. The flag still earns a fuller explanation; the
        # number never reaches the student.
        critical_section = (
            "⚠ CRITICAL MOMENT: This position demands precise play.\n"
            "Please provide a MORE DETAILED explanation of this position, "
            "covering all key features and why accuracy matters here — in terms of "
            "the position, never in terms of evaluations or engine line rankings.\n\n"
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
        # Qualitative standing, not "Overall evaluation: N centipawns". Same reason
        # as the move prompt: the number was not in centipawns and its magnitude is
        # not defensible, while the band word survives a 50-60cp error.
        standing=describe_eval(report),
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
    """Render the opponent's IMMEDIATE punishing reply (a single move), or None.

    Only the FIRST ply of the refutation is surfaced. Handing the model the full
    multi-move PV made it recite move-salad ("Black plays fxg5, fxg5, Ne5, ...")
    that read badly and tripped the fidelity checks; the concrete-consequence
    coaching only needs the opponent's one immediate reply — the coach conveys
    "why it hurts" from the eval and threats. Rendered in SAN from the position
    AFTER the student's move (falling back to ``report.fen`` if it can't apply).
    """
    if not report.refutation_line:
        return None
    board: chess.Board | None = None
    try:
        board = chess.Board(report.fen)
        board.push_uci(report.user_move)
    except (ValueError, AssertionError):
        board = None
    base_fen = board.fen() if board is not None else report.fen
    first_uci = report.refutation_line[0]
    reply_san = _uci_line_to_san(base_fen, [first_uci]).removesuffix(" ...").strip()
    if not reply_san:
        return None  # can't name the reply honestly — omit the section
    # Deterministically state WHAT the reply captures (verified from the board),
    # so the coach voices "capturing your knight on g5" instead of a vague
    # "winning material" it might get wrong. Composed, never derived by the LLM.
    capture_clause = _refutation_capture_clause(board, first_uci)
    return f"--- Opponent's reply ---\nAfter your move, the opponent's strongest reply is {reply_san}{capture_clause}."


#: What a move was found to DO. One per branch of :func:`_move_effect`, so a
#: category is only ever assigned where the clause was verified from the board.
EFFECT_CAPTURE = "capture"
EFFECT_FORK = "fork"
EFFECT_CHECK = "check"
EFFECT_ATTACK = "attack"
EFFECT_ESCAPE = "escape"
EFFECT_DEFEND = "defend"
EFFECT_CASTLE = "castle"
EFFECT_OPEN_FILE = "open_file"
EFFECT_MOBILITY = "mobility"
EFFECT_KING_ACTIVITY = "king_activity"
EFFECT_EXTRA_DEFENDER = "extra_defender"

#: Phase-specific lessons, keyed ``(category, phase)``, consulted before the
#: phase-agnostic table below. Only the cases where the lesson GENUINELY differs by
#: phase are listed — the rest fall through, so this stays a short table rather
#: than a speculative 33-cell matrix.
#:
#: Added because the judge's follow-up review named phase-blindness as the problem
#: with the composed lessons, with specific examples: ply 74 centralised the king in
#: a pawn endgame and was taught "move it somewhere safe and active", when the
#: endgame principle is the king as an ATTACKER; ply 72 got a generic
#: rook-on-an-open-file tip when the endgame principle is the rook behind the passed
#: pawn or cutting the enemy king off. Same board fact, different lesson depending
#: on when it happens.
_PHASE_TAKEAWAYS: dict[tuple[str, str], str] = {
    (EFFECT_OPEN_FILE, PHASE_ENDGAME): (
        "rook placement in an endgame — behind your passed pawn to push it, or across a rank to cut the enemy king off"
    ),
    (EFFECT_CAPTURE, PHASE_ENDGAME): (
        "in an endgame a single pawn usually decides the result, so a capture that wins one is worth more than it looks"
    ),
    (EFFECT_ATTACK, PHASE_ENDGAME): (
        "in an endgame go after the pawns that could promote, and the pieces guarding them"
    ),
    (EFFECT_ESCAPE, PHASE_ENDGAME): (
        "with few pieces left, move a threatened piece somewhere it keeps doing a job — guarding a passed "
        "pawn or holding a key square"
    ),
    (EFFECT_MOBILITY, PHASE_OPENING): (
        "development — a piece still on its starting square is doing nothing, so bring it out towards the centre early"
    ),
    (EFFECT_ATTACK, PHASE_OPENING): (
        "do not start an attack before your pieces are out — develop first, then look for targets"
    ),
}

#: The lesson each effect category teaches, as CONTENT for the closing takeaway —
#: not as finished prose. The model still writes the sentence; it just no longer
#: chooses the subject.
#:
#: Why compose this at all: left to choose, the coach reached for the same three
#: ideas on 68% of turns, and worse, chose ones that did not apply — on ply 32 it
#: closed with "next time you see a fork opportunity" about a move that forks
#: nothing, and three of four verified-correct turns ended with that same hook.
#: The category is already derived from the board, so keying the lesson to it makes
#: the takeaway follow the position instead of the model's habits.
#:
#: The judge's own suggestion was to forbid repetition in the prompt. That is a
#: negative constraint, and those have never worked on this model (the grounding
#: rule, lever 2, had no measurable effect). Supplying the subject is the positive
#: form of the same idea.
_EFFECT_TAKEAWAYS: dict[str, str] = {
    EFFECT_CAPTURE: (
        "what a capture is worth — check what you win, what recaptures, and whether the trade favours you"
    ),
    EFFECT_FORK: "hitting two pieces with one move, so the opponent can only save one",
    EFFECT_CHECK: "a check forces an answer, which buys you a move to use elsewhere",
    EFFECT_ATTACK: "going after a piece that has too few defenders",
    EFFECT_ESCAPE: "when one of your pieces is attacked, move it somewhere it is both safe and useful",
    EFFECT_DEFEND: "defending what you already have before starting something new",
    EFFECT_CASTLE: "getting the king to safety before the centre opens up",
    EFFECT_OPEN_FILE: "putting a rook on a file with no pawns in its way",
    EFFECT_MOBILITY: "a piece with almost no squares is doing almost nothing — find it a better home",
    EFFECT_KING_ACTIVITY: (
        "in an endgame the king is a fighting piece, not something to hide — walk it towards the action"
    ),
    EFFECT_EXTRA_DEFENDER: "counting attackers and defenders on a square before you commit to it",
}


def effect_takeaway(category: str, phase: str = "") -> str:
    """The lesson to close on for a verified effect ``category``, or ``''``.

    Prefers the phase-specific lesson where one exists, because the same board
    fact carries a different lesson at different stages — a king walking forward is
    a mistake in the opening and the winning method in an endgame.

    Empty for an unrecognised or absent category, in which case the caller leaves
    the takeaway to the model rather than inventing a lesson — the same rule the
    clause composer follows when nothing about a move can be verified.
    """
    if phase and (category, phase) in _PHASE_TAKEAWAYS:
        return _PHASE_TAKEAWAYS[(category, phase)]
    return _EFFECT_TAKEAWAYS.get(category, "")


def _move_effect_clause(board: chess.Board | None, uci: str, *, target_possessive: str) -> str:
    """The clause half of :func:`_move_effect` — see there for the detail."""
    return _move_effect(board, uci, target_possessive=target_possessive)[1]


def _move_effect(
    board: chess.Board | None,
    uci: str,
    *,
    target_possessive: str,
    rival_uci: str = "",
) -> tuple[str, str]:
    """``(category, clause)`` for what a move DOES; ``("", "")`` if nothing is certain.

    The category is the same judgement the clause is built from, returned rather
    than thrown away so the closing takeaway can be keyed to it. Otherwise the
    model picks its own lesson and reaches for the same three every time — three
    ideas covered 68% of turns, and on ply 32 it closed with "next time you see a
    fork opportunity" about a move that forks nothing. One derivation, two uses,
    so the clause and the lesson cannot disagree.

    Everything is computed from ``board`` (the position the move is played in),
    so the result is a fact the model only has to voice — never an inference it
    has to make. ``target_possessive`` is the wording for the pieces the move
    acts against (``"your "`` when the opponent is moving, ``"their "`` when the
    student is). Priority: capture, then fork, then check/attack, then escaping
    an attack, then defending an attacked piece.

    Pawns and the king are excluded as *named targets*: an early version turned
    a real check into a pawn inventory ("giving check and hitting your pawn on
    b2 and your pawn on h2").

    ``rival_uci`` is the move this one is being compared against (the student's,
    when describing the engine's choice). It suppresses claims that are true of
    the move in isolation but misleading as a *reason to prefer it* — see the
    king-walk branch in :func:`_quiet_move_effect`.
    """
    if board is None:
        return ("", "")
    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        return ("", "")
    if move not in board.legal_moves:
        return ("", "")

    mover = board.turn
    if board.is_capture(move):
        if board.is_en_passant(move):
            cap_sq = chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
            return (EFFECT_CAPTURE, f", capturing {target_possessive}pawn on {chess.square_name(cap_sq)}")
        victim = board.piece_at(move.to_square)
        if victim is not None:
            name = chess.piece_name(victim.piece_type)
            return (
                EFFECT_CAPTURE,
                f", capturing {target_possessive}{name} on {chess.square_name(move.to_square)}",
            )
        return ("", "")

    moved = board.piece_at(move.from_square)
    was_attacked = bool(board.attackers(not mover, move.from_square))
    after = board.copy(stack=False)
    after.push(move)
    check = after.is_check()

    targets: list[tuple[int, str]] = []
    for sq in after.attacks(move.to_square):
        piece = after.piece_at(sq)
        if piece is None or piece.color == mover or piece.piece_type in (chess.KING, chess.PAWN):
            continue
        undefended = not after.attackers(not mover, sq)
        adj = "undefended " if undefended else ""
        label = f"{target_possessive}{adj}{chess.piece_name(piece.piece_type)} on {chess.square_name(sq)}"
        targets.append((piece.piece_type, label))
    targets.sort(key=lambda t: t[0], reverse=True)

    if len(targets) >= 2:
        two = " and ".join(t[1].replace("undefended ", "") for t in targets[:2])
        return (EFFECT_FORK, f", giving check and hitting {two}" if check else f", hitting {two}")
    if targets:
        phrase = targets[0][1]
        return (
            EFFECT_ATTACK,
            f", giving check and attacking {phrase}" if check else f", attacking {phrase}",
        )
    if check:
        return (EFFECT_CHECK, ", giving check")

    # Defensive motives, in the mover's own terms.
    if was_attacked and not after.attackers(not mover, move.to_square) and moved is not None:
        name = chess.piece_name(moved.piece_type)
        return (
            EFFECT_ESCAPE,
            f", moving your {name} off {chess.square_name(move.from_square)} where it was attacked",
        )
    for sq in after.attacks(move.to_square):
        piece = after.piece_at(sq)
        if piece is None or piece.color != mover or piece.piece_type == chess.KING:
            continue
        if after.attackers(not mover, sq) and len(after.attackers(mover, sq)) == 1:
            name = chess.piece_name(piece.piece_type)
            return (EFFECT_DEFEND, f", defending your {name} on {chess.square_name(sq)}")
    return _quiet_move_effect(board, after, move, rival_uci=rival_uci)


def _quiet_move_clause(board: chess.Board, after: chess.Board, move: chess.Move) -> str:
    """The clause half of :func:`_quiet_move_effect`."""
    return _quiet_move_effect(board, after, move)[1]


def _quiet_move_effect(
    board: chess.Board,
    after: chess.Board,
    move: chess.Move,
    *,
    rival_uci: str = "",
) -> tuple[str, str]:
    """Describe a move that captures, attacks and defends nothing.

    Measured on one game: 13 of 44 best moves reached this point and got only the
    engine's category label ("rook activity — improving rook placement"), which
    the coach can do nothing with but restate. A label is the *name* of an idea;
    these clauses are the facts on the board that the name stands for, which is
    the difference between "Kf3 improves your king's activity" and "your king
    steps to f3, one square closer to the centre".

    Deliberately says nothing about mere centralisation on its own: "toward the
    centre" was the biggest bucket in that measurement and is just another label,
    and we already flag the coach elsewhere for calling non-central squares
    central. Every branch here states squares, counts or a file — things a student
    can check on the board.
    """
    mover = board.turn
    piece = board.piece_at(move.from_square)
    if piece is None:
        return ("", "")
    from_name = chess.square_name(move.from_square)
    to_name = chess.square_name(move.to_square)

    if board.is_castling(move):
        side = "short" if chess.square_file(move.to_square) > chess.square_file(move.from_square) else "long"
        return (
            EFFECT_CASTLE,
            f", castling {side} to tuck your king onto {to_name} and connect your rooks",
        )

    # A rook or queen reaching a file with no pawns in the way.
    if piece.piece_type in (chess.ROOK, chess.QUEEN):
        file_index = chess.square_file(move.to_square)
        mask = chess.BB_FILES[file_index]
        own_pawns = after.pieces_mask(chess.PAWN, mover) & mask
        their_pawns = after.pieces_mask(chess.PAWN, not mover) & mask
        file_name = chess.FILE_NAMES[file_index]
        name = chess.piece_name(piece.piece_type)
        if not own_pawns and not their_pawns:
            return (EFFECT_OPEN_FILE, f", moving your {name} to {to_name} on the open {file_name}-file")
        if not own_pawns:
            return (
                EFFECT_OPEN_FILE,
                f", moving your {name} to {to_name} on the half-open {file_name}-file",
            )

    # A piece that had almost nowhere to go and now has somewhere. The counts are
    # the point: the student can recount them on the board.
    #
    # Both sides of the comparison must be the SAME measurement — squares the
    # piece attacks that its own side does not occupy. A first version counted
    # legal moves before and attacked squares after, which compares two different
    # things. The king is excluded: it may not move into check, so an attacked-
    # square count overstates where it can actually go, and the move that
    # triggered this (an early Ke2 after losing castling rights) is usually forced
    # rather than an improvement.
    if piece.piece_type != chess.KING:
        before_squares = _reachable_count(board, move.from_square, mover)
        after_squares = _reachable_count(after, move.to_square, mover)
        if before_squares <= 2 and after_squares >= before_squares + 3:
            name = chess.piece_name(piece.piece_type)
            return (
                EFFECT_MOBILITY,
                f", moving your {name} from {from_name} to {to_name}, where it covers "
                f"{after_squares} squares instead of {before_squares}",
            )

    # An endgame king walking in. Gated on the project's own endgame test, NOT on
    # castling rights: a first probe used "has no castling rights", which called
    # an early-game Ke2 king activity — false, and usually the move is forced.
    if piece.piece_type == chess.KING and phase_of_board(board) == PHASE_ENDGAME:
        before_dist = _centre_distance(move.from_square)
        after_dist = _centre_distance(move.to_square)
        # Only claim centralisation when it actually distinguishes this move from
        # the one it is being compared against. Otherwise the clause is true in
        # isolation and wrong as a reason: with white Kf2 and the student playing
        # the MORE central Ke3, we told the coach that Kf3 was "closer to the
        # centre", and it duly told the student their more central move was less
        # central. If the centre is not what separates the two moves, the engine
        # preferred it for a reason we cannot see — so say nothing.
        rival_is_at_least_as_central = False
        if rival_uci:
            try:
                rival = chess.Move.from_uci(rival_uci)
                rival_is_at_least_as_central = _centre_distance(rival.to_square) <= after_dist
            except ValueError:
                rival_is_at_least_as_central = False
        if after_dist < before_dist and not rival_is_at_least_as_central:
            return (
                EFFECT_KING_ACTIVITY,
                f", walking your king from {from_name} to {to_name}, closer to the centre",
            )

    # Adding a defender to something already under attack. Weaker than the
    # single-defender case handled above, so it comes last and says so.
    for sq in after.attacks(move.to_square):
        defended = after.piece_at(sq)
        if defended is None or defended.color != mover or defended.piece_type == chess.KING:
            continue
        if after.attackers(not mover, sq):
            name = chess.piece_name(defended.piece_type)
            return (
                EFFECT_EXTRA_DEFENDER,
                f", adding a defender to your {name} on {chess.square_name(sq)}",
            )
    return ("", "")


def _reachable_count(board: chess.Board, square: int, color: chess.Color) -> int:
    """Squares the piece on ``square`` attacks that ``color`` does not occupy."""
    return chess.popcount(int(board.attacks(square)) & ~board.occupied_co[color])


def _centre_distance(square: int) -> int:
    """Chebyshev distance from ``square`` to the nearest of d4/d5/e4/e5."""
    file_index, rank = chess.square_file(square), chess.square_rank(square)
    return max(min(abs(file_index - 3), abs(file_index - 4)), min(abs(rank - 3), abs(rank - 4)))


#: Closing instruction when we could NOT verify what the best move does, so there
#: is no composed lesson to hand over. Unchanged from the original wording: the
#: model chooses, because inventing a lesson would be worse.
_TAKEAWAY_FALLBACK = (
    "CLOSE with one transferable takeaway, not a generic maxim: name the principle in a few words, then a short "
    '"next time you see ..., ask yourself ..." hook the student can reuse. Do NOT end with "focus on developing '
    'your pieces" or "focus on king safety" unless that is the specific lesson of this move. (This is a teaching '
    "heuristic, not a board fact — do not assert new pieces or squares in it.)"
)


def composed_lesson(report: ComparisonReport, tier: str | None = None) -> tuple[str, str]:
    """``(key, lesson)`` for the takeaway this turn would close on; ``("", "")`` if none.

    Exposed so the caller can remember what it has already taught. The key is the
    ``category:phase`` pair :func:`effect_takeaway` looks up, which is the right
    granularity for "same lesson": two turns whose best move attacks an
    under-defended piece close on the identical sentence, and keying on the rendered
    text instead would treat a phase-specific variant as a different lesson.

    ``tier`` defaults to this report's own severity tier, so a caller tracking lesson
    history does not need the tier machinery — which is private to this module — just
    to ask what a turn would teach.
    """
    if tier is None:
        tier = _move_feedback_tier(report)
    board = _safe_board(report.fen)
    # On the tiers that make no comparison, the lesson must come from the move the
    # student actually played — keying it to an alternative we are not naming would
    # close on a lesson the rest of the response never mentions.
    subject = report.user_move if tier in _OWN_MOVE_TIERS else report.best_move
    rival = "" if tier in _OWN_MOVE_TIERS else report.user_move
    category, _clause = _move_effect(board, subject, target_possessive="their ", rival_uci=rival)
    phase = phase_of_board(board) if board is not None else ""
    lesson = effect_takeaway(category, phase)
    if not lesson:
        return "", ""
    return f"{category}:{phase}", lesson


#: Second time a lesson comes up, name the recurrence instead of teaching it again.
_TAKEAWAY_ESCALATE = (
    "CLOSE by pointing out that this is the SAME idea as earlier in the game, not by "
    "teaching it again: the student has now met this lesson more than once — {lesson}. "
    "Say so in one short sentence, as an observation about the pattern they keep running "
    "into, and do not restate the lesson as if it were new. Do not assert new pieces or "
    "squares in it."
)

#: How many times one lesson may be taught in a game before it is retired.
#:
#: Two: teach it once, name the recurrence once, then stop. Measured need — in v33 the
#: coach closed on "going after a piece that has too few defenders" on five of eighteen
#: turns (plies 20, 30, 38, 44, 46), because the engine kept recommending the same move
#: and the composer kept describing it identically. Every sentence was true; a frontier
#: reviewer still called it "one lesson, five times, with no escalation and no memory".
#:
#: Retiring is deliberately silence rather than a substitute lesson. There is only one
#: verified effect per move, so a replacement would have to be invented, and inventing
#: a lesson is what composing the subject was introduced to stop.
LESSON_RETIRE_AFTER = 2


def _build_takeaway_instruction(report: ComparisonReport, tier: str = "serious", times_taught: int = 0) -> str:
    """The closing-takeaway instruction, with the lesson composed where possible.

    The subject of the takeaway is derived from what the relevant move verifiably DOES
    (:func:`_move_effect`), not chosen by the model. Left to choose, the coach
    closed on one of the same three ideas on 68% of turns and sometimes on an idea
    that did not apply at all — "next time you see a fork opportunity" about a move
    that forks nothing. The model still writes the sentence; it no longer picks the
    topic.

    ``times_taught`` is how many times this same lesson has already closed a turn in
    this game, which the caller tracks. It drives a three-step ladder: teach it, then
    name the recurrence, then say nothing. Composing the subject fixed the coach
    choosing an idea that did not apply; it could not fix the coach teaching an idea
    that applied five times, because each instance was individually correct.

    Falls back to the original open-ended instruction when nothing about the move
    can be verified, on the same principle as the clause composer: no fact, no
    claim.
    """
    _key, lesson = composed_lesson(report, tier)
    if not lesson:
        return _TAKEAWAY_FALLBACK
    if times_taught >= LESSON_RETIRE_AFTER:
        # Taught, then flagged as recurring. A third telling adds nothing, and the
        # response is still a complete piece of coaching without it: the move, what
        # the stronger one does, and why. Silence beats a maxim on its fourth outing.
        return ""
    if times_taught > 0:
        return _TAKEAWAY_ESCALATE.format(lesson=lesson)
    return (
        "CLOSE with one transferable takeaway on THIS lesson and no other: "
        f"{lesson}. Put it in your own words as a short "
        '"next time you see ..., ask yourself ..." hook the student can reuse. Do not substitute a '
        "different principle, and do not assert new pieces or squares in it."
    )


def _best_move_achievement(report: ComparisonReport) -> str:
    """What the engine's best move achieves — position-specific where possible.

    The engine's ``best_move_idea`` is a CATEGORY LABEL, not a fact: across a
    44-turn game there were only 10 distinct values ("king safety — repositioning
    the king" x13, "rook activity — improving rook placement" x8). Voicing a
    label can only produce category sentences, which is the mechanical cause of
    the generic best-move explanations the report card kept flagging.

    So prepend a concrete, board-derived clause when one can be verified (what
    the move captures / attacks / defends / escapes), and keep the label as the
    theme. Composed, never derived — if nothing is verifiable, the label alone
    is returned unchanged.
    """
    return _move_achievement(report, report.best_move, rival_uci=report.user_move)


def _move_achievement(report: ComparisonReport, uci: str, *, rival_uci: str = "") -> str:
    """What ``uci`` achieves, as a composed clause plus the engine's label.

    ``uci`` is the best move on the tiers that compare, and the STUDENT's own move
    on the tiers that do not (see :data:`_OWN_MOVE_TIERS`). The engine's
    ``best_move_idea`` describes the best move only, so it is dropped when
    describing anything else rather than misattributed.
    """
    board = _safe_board(report.fen)
    # ``rival_uci`` is the move this description is implicitly compared against, if
    # any: a clause that does not distinguish the two moves is not a reason.
    _category, effect = _move_effect(board, uci, target_possessive="their ", rival_uci=rival_uci)
    label = report.best_move_idea if uci == report.best_move else ""
    if label and board is not None and _label_wrong_for_phase(label, board):
        # No substitute label: swapping one category word for another is what
        # failed when the lesson table was phase-gated. Say the verified thing or
        # say nothing.
        label = ""
    if not effect:
        return label
    concrete = effect.removeprefix(", ").strip()
    return f"{concrete} ({label})" if label else concrete


# The engine's king-safety ideas (MoveComparator.cpp: "king safety — castling to
# a safer position" / "king safety — repositioning the king"). They are correct
# in the opening and middlegame and INVERTED in an endgame, where the king is a
# fighting piece and centralising it is how you win.
_KING_SAFETY_IDEA = "king safety"


def _label_wrong_for_phase(label: str, board: chess.Board) -> bool:
    """Is the engine's idea label actively misleading in this phase?

    Only one case so far, and it is the one a frontier review kept flagging: the
    king-safety label on an endgame turn. It arrived on 8 of 18 endgame turns in a
    44-turn game and, unlike the guidance entry that was excluded alongside it,
    it sits in the highest-value line of the prompt — so the coach kept preaching
    "get your king safe" while the correct lesson was to march the king in.
    """
    return _KING_SAFETY_IDEA in label.lower() and phase_of_board(board) == PHASE_ENDGAME


def _terminal_feedback(board: chess.Board, uci: str) -> str:
    """Feedback for a move that ends the game, or '' if it does not end it."""
    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        return ""
    if move not in board.legal_moves:
        return ""
    san = board.san(move)
    after = board.copy(stack=False)
    after.push(move)
    if after.is_checkmate():
        return (
            f"That's checkmate — {san} ends the game. "
            "Worth remembering: to mate with a rook, cut the enemy king off from the "
            "squares it could run to, then bring your own king up to take away the rest."
        )
    if after.is_stalemate():
        return (
            f"{san} is stalemate — the opponent has no legal move and is not in check, "
            "so the game is a draw rather than a win. Worth remembering: when the enemy "
            "king is nearly trapped, leave it one safe square until you can deliver mate."
        )
    if after.is_insufficient_material():
        return f"{san} leaves too little material to mate, so the game is drawn."
    return ""


def compose_safe_move_feedback(report: ComparisonReport) -> str:
    """Composed move feedback for the fidelity gate's fallback, or '' if nothing verifies.

    This is what a student reads precisely when the model could not be trusted, so it
    has to be the best sentence we can build without one — and until now it was the
    worst. The general template was reused, which in one 44-turn game (a) showed the
    cost in pawn units, a defect the coaching-standard audit names alongside
    centipawns, (b) named an off-menu move, and (c) emitted raw tactic data — "moving
    d5 reveals Bc8 hitting Rg4" — which the reviewer called unusable, "no owner or
    purpose".

    So: severity in words rather than numbers, the stronger move with the SAME
    board-verified clause the prompt supplies, and the composed lesson, keeping the
    cue-and-check shape. No evaluations, no variations, no tactic dumps. Every part is
    derived from the board, so it cannot contain the class of claim that sent us here.
    """
    board = _safe_board(report.fen)
    if board is None:
        return ""

    # Mate first: with the game over there is no "next move" to teach, and the generic
    # branches below would close on a takeaway about future play — which is exactly the
    # defect that made this the reviewer's decisive item (v29 ply 1003 asked whether
    # checkmate "buys me time to develop or improve another piece").
    terminal = _terminal_feedback(board, report.user_move)
    if terminal:
        return terminal

    tier = _move_feedback_tier(report)
    # The two lower tiers no longer state a size. "That slightly missed the mark" and
    # "That was a serious mistake" are claims resting on an eval drop whose error is as
    # wide as the band between them, and this text is what a student reads precisely
    # when we did not trust the model — the last place to assert something we cannot
    # support. The board-derived clause below carries the weight honestly instead.
    #
    # On those two tiers there is deliberately NO opener: the named stronger move leads.
    # A first version opened with "There was a stronger move here." and a live run
    # produced "There was a stronger move here. Bc3 was stronger here — attacking their
    # undefended bishop on b4." Saying it twice is worse than the number was. The
    # affirming tiers keep their opener, because there affirmation IS the content and
    # "sound" has to affirm before it offers a refinement (BUG-016).
    opening = {
        "best": "Good move.",
        "equal": "That works — it is as good as anything else here.",
        "sound": "A reasonable move.",
        "inaccuracy": "",
        "serious": "",
    }[tier]
    parts = [opening] if opening else []

    if tier in _OWN_MOVE_TIERS:
        category, clause = _move_effect(board, report.user_move, target_possessive="their ")
    else:
        category, clause = _move_effect(board, report.best_move, target_possessive="their ", rival_uci=report.user_move)
        best_san = uci_to_san(report.fen, report.best_move)
        if best_san:
            detail = clause.removeprefix(", ").strip()
            parts.append(f"{best_san} was stronger here{' — ' + detail if detail else ''}.")
        elif not opening:
            # Nothing nameable and no opener would leave the student with only a
            # takeaway and no idea what prompted it.
            parts.append("There was a stronger move here.")
    if tier in _OWN_MOVE_TIERS and clause:
        parts.append(f"Your move is {clause.removeprefix(', ').strip()}.")

    lesson = effect_takeaway(category, phase_of_board(board))
    if lesson:
        parts.append(f"Worth remembering: {lesson}.")
    return " ".join(parts)


def _achievement_line(report: ComparisonReport, tier: str) -> str:
    """The rendered achievement line for ``tier``, or '' to omit it.

    On the tiers that make no comparison the line describes the STUDENT's move and
    is headed accordingly, so the alternative is never put in front of the model at
    all. Supplying the engine's move and instructing the coach not to mention it
    would be a negative constraint, and those do not work here.
    """
    if tier in _OWN_MOVE_TIERS:
        achievement = _move_achievement(report, report.user_move)
        subject = "Your move"
    else:
        achievement = _best_move_achievement(report)
        subject = f"The best move ({uci_to_san(report.fen, report.best_move) or report.best_move})"
    if not achievement:
        return ""
    # A bare statement, not a labelled field. Renaming the label did not stop the
    # model copying it — turns echoing a prompt header went 0 -> 6 -> 8 across three
    # runs, and the rename happened between the last two. It copies whatever label it
    # is given, so there is no label: the line now reads as a sentence it can absorb
    # rather than a heading it can quote.
    return f"\n{subject} does this: {achievement}.\n"


def _best_move_achievement_line(report: ComparisonReport) -> str:
    """The rendered "What the best move achieves" line, or '' to omit it.

    The line is omitted rather than left blank: a dangling header is an invitation
    for the model to fill it in from its own vocabulary, which is exactly how
    "closer to the center" appeared on a turn where we supplied nothing.
    """
    achievement = _best_move_achievement(report)
    if not achievement:
        return ""
    return f"\nWhat the best move achieves: {achievement}\n"


def _refutation_capture_clause(board: chess.Board | None, first_uci: str) -> str:
    """A verified clause describing what the opponent's reply DOES, or ''.

    Everything here is computed from the position AFTER the student's move (the
    opponent is to move), so it is a fact, never a model inference. Covers:
    - captures: ", capturing your <piece> on <square>" (en-passant aware);
    - checks: ", giving check";
    - attacks on an undefended piece: ", attacking your undefended <piece> on
      <square>";
    - forks: ", hitting your <piece> on <sq> and <piece> on <sq>".
    Without this, non-capture refutations reached the coach as a bare move and
    the model invented the "why" (e.g. calling the knight move f6g4 "gaining a
    strong central pawn"). Returns '' when nothing can be verified.

    Thin wrapper over :func:`_move_effect_clause` so the opponent's reply and
    the engine's best move share one verified implementation (no drift).
    """
    return _move_effect_clause(board, first_uci, target_possessive="your ")


def _line_base_fen(report: ComparisonReport, moves: list[str]) -> str | None:
    """Which position does this PV line start from — before or after the move?

    It has to be decided per line, because the engine's ``top_lines`` field means
    two different things depending on the move played (verified against a live
    engine, and visible in ``MoveComparator::compare``, which ends with
    ``report.top_lines = multipv_results`` after a second search may have
    overwritten that variable):

    * student played the engine's best move -> the MultiPV lines are for the
      position BEFORE the move, and open with the student's own alternatives;
    * student played anything else -> they are for the position AFTER the move,
      open with the opponent's reply, and match ``refutation_line``.

    Assuming one base cost us the whole section: on the 14 turns of a 44-turn
    game where the student found the best move, every line was discarded and the
    coach was handed an empty "Top Engine Lines" block while the instructions
    told it to grind only on facts from that block.

    So try the pre-move position first, fall back to the post-move one, and
    return ``None`` when the line replays in neither (genuine engine PV
    inconsistency — BUG-019). A line is only ever rendered from a base it
    actually replays in, which cannot be wrong whatever the engine changes to.
    """
    if not moves:
        return None
    try:
        pre = chess.Board(report.fen)
    except ValueError:
        return None
    try:
        first = chess.Move.from_uci(moves[0])
    except ValueError:
        return None
    if first in pre.legal_moves:
        return report.fen
    post = pre.copy(stack=False)
    try:
        post.push_uci(report.user_move)
    except (ValueError, AssertionError):
        return None
    return post.fen() if first in post.legal_moves else None


def _format_comparison_top_lines(report: ComparisonReport) -> str:
    """Format the top engine lines from a ComparisonReport, in SAN.

    The base position is chosen per line by :func:`_line_base_fen`, because the
    engine's ``top_lines`` are relative to the position before the student's move
    in some cases and after it in others. Rendering from the wrong base makes the
    first move illegal, which used to fall the WHOLE line back to raw UCI —
    coordinate strings like ``f6g4`` reached the coach, which parroted them and
    invented what the move did (the correct SAN is ``Nfg4``, a knight move). It
    now truncates instead, so a wrong base silently costs the line entirely.
    """
    student_is_white = report.fen.split()[1] == "w" if len(report.fen.split()) > 1 else True
    opp = "Black" if student_is_white else "White"
    you = "White" if student_is_white else "Black"
    header_shown = False
    lines: list[str] = []
    for i, pv in enumerate(report.top_lines, 1):
        base_fen = _line_base_fen(report, pv.moves)
        if base_fen is None:
            continue  # replays from neither position — omit rather than mislead
        moves_str = _uci_line_to_numbered_san(base_fen, pv.moves)
        if not moves_str:
            continue  # nothing replayable — omit rather than show coordinates
        # Say which position the line starts from: a line of the student's own
        # alternatives and a line of the opponent's refutation read identically
        # otherwise, and the coach has no way to tell them apart.
        whose = "after your move" if base_fen != report.fen else "from the position you were in"
        if not header_shown:
            lines.append(f"--- Top Engine Lines ({opp} = your opponent, {you} = you) ---")
            header_shown = True
        # No eval and no depth. Both were engine bookkeeping in units we cannot
        # defend, and the level instructions already had to ask the model not to
        # repeat the very numbers we were handing it. The line's POSITION in this
        # list carries the engine's preference, which is the trustworthy part.
        lines.append(f"Line {i} ({whose}): {moves_str} — theme: {pv.theme}")
    return "\n".join(lines)


def build_rich_move_evaluation_prompt(
    report: ComparisonReport,
    level: str = "intermediate",
    guidance: list[GuidanceEntry] | None = None,
    guidance_facts: dict[str, str] | None = None,
    lesson_times_taught: int = 0,
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
        guidance: Optional selector-chosen guidance entries.
        guidance_facts: Board facts instantiating each guidance theme.
        lesson_times_taught: How many times this turn's composed lesson has already
            closed a turn in this game. Drives the teach / name-the-recurrence /
            say-nothing ladder in :func:`_build_takeaway_instruction`. Zero (the
            default) reproduces the memoryless behaviour.

    Returns:
        The complete prompt string ready to send to the LLM.
    """
    sections: list[str] = []

    # The tier is needed while assembling the sections, not just after: on the tiers
    # that make no comparison it decides whether the engine's alternative is put in
    # front of the model at all.
    tier = _move_feedback_tier(report)
    compares = tier not in _OWN_MOVE_TIERS

    # Curated guidance (the "what to focus on" half of the teaching bridge),
    # level-filtered. Inserted first so the move feedback LEADS with the
    # selected themes; the engine-grounding instructions below are untouched.
    # An empty selection adds nothing, so feedback is unchanged without guidance.
    # ``guidance_facts`` instantiates each theme with the board fact that fired
    # it, so the model receives a specific reason instead of abstract prose.
    guidance_block = format_guidance_block(guidance or [], level=level, facts=guidance_facts)
    if guidance_block:
        sections.append(guidance_block)

    placement_section = _format_placement(report.fen)
    if placement_section is not None:
        sections.append(placement_section)

    # Board-derived pawn-structure facts so the coach grounds isolated/doubled
    # claims instead of guessing (BUG-018) — the ComparisonReport carries none.
    pawn_structure_section = _format_pawn_structure_grounding(report.fen)
    if pawn_structure_section is not None:
        sections.append(pawn_structure_section)

    # Conditionally-present sections
    missed_section = _format_missed_tactics(report)
    if missed_section is not None:
        sections.append(missed_section)

    refutation_section = _format_refutation_line(report)
    if refutation_section is not None:
        sections.append(refutation_section)

    # Top lines for context — but ONLY on the tiers that compare. On the
    # no-comparison tiers this section was the remaining half of a withhold that the
    # ledger already recorded as complete: with `Best move:` suppressed, the engine's
    # preferred move still arrived here as "Line 1 (from the position you were in):
    # 3.Nd5", three lines above an instruction reading "Do NOT offer an alternative —
    # there isn't one". Caught by a cross-surface test, not by review, which is the
    # argument for having one. On the `best` tier the top line IS the student's move,
    # so nothing is lost; on `equal` the whole point is that no alternative is named.
    if compares:
        top_lines_section = _format_comparison_top_lines(report)
        if top_lines_section:
            sections.append(top_lines_section)

    # Critical moment. The engine's ``critical_reason`` is DELIBERATELY not passed
    # on: its only format is "eval spread between best and 3rd-best line is 107cp"
    # (MoveComparator/PositionAnalyzer), which is our own bookkeeping, not a chess
    # reason. Handed it, the coach dutifully voiced it — "this was a critical moment
    # because the best move was also your move, and the evaluation spread shows it
    # was a key decision" on plies 12, 18 and 24 — occupying the slot where a reason
    # belongs. The flag still earns a fuller explanation; the number never reaches
    # the student. (It also carried BUG-021 into the prompt: 98542cp at a mate.)
    if report.critical_moment:
        critical_section = (
            "⚠ CRITICAL MOMENT: This was a critical decision point.\n"
            "Please provide a MORE DETAILED explanation of what was missed "
            "and why this moment was so important, in terms of the pieces and "
            "squares on the board.\n\n"
        )
    else:
        critical_section = ""

    # Level-adaptive instructions
    level_instructions = _build_level_instructions(level)

    # Severity-tiered framing (lever 3) + per-tier length (lever 4), chosen from
    # OUR own eval-drop bands (client-owned SOUND_MAX_DROP_CP /
    # DUBIOUS_MAX_DROP_CP) and move identity — never the engine's classification
    # label, whose thresholds are the engine's to change (BUG-016). Directness
    # AND length scale with severity: best -> short affirm (BUG-014); sound ->
    # affirm, a better move may be a refinement (BUG-016); inaccuracy -> brief
    # redirect; serious -> direct, lead with the cost. The word limit is set per
    # tier so a best move gets one sentence and a blunder gets room to be
    # specific.
    best_move_line = _achievement_line(report, tier)
    move_instructions = _TIER_INSTRUCTIONS[tier]
    if not best_move_line:
        # Four tier blocks tell the model to "use '<header>' shown above". With the
        # line dropped that points at nothing, which is an invitation to invent one —
        # so redirect the instruction to the data that IS there.
        for reference in _ACHIEVEMENT_REFERENCES:
            move_instructions = move_instructions.replace(reference, "the position facts above")
    word_limit = _TIER_WORD_LIMIT[tier]
    # ``lesson_times_taught`` comes from the caller's per-game memory: the coach used to
    # treat every turn as if it were the first, and taught one lesson five times.
    takeaway_instruction = _build_takeaway_instruction(report, tier, lesson_times_taught)

    # The engine's move, named only on the tiers that actually compare against it.
    # It used to be rendered unconditionally, so on the `equal` tier the prompt said
    # "Best move: d4" three lines above an instruction reading "Do NOT offer an
    # alternative — there isn't one". That is a negative constraint over data we
    # supplied ourselves, the one pattern this model reliably ignores, and it means
    # the tier was never the clean withhold the ledger recorded (row 28): only the
    # achievement line and the engine's label were withheld, never the move.
    alternative_line = f"Best move: {uci_to_san(report.fen, report.best_move)}\n" if compares else ""

    return RICH_MOVE_EVALUATION_PROMPT_V2.format(
        system=SYSTEM_PROMPT_V2,
        level=level,
        fen=report.fen,
        perspective=_format_perspective(report.fen),
        user_move=uci_to_san(report.fen, report.user_move),
        alternative_line=alternative_line,
        best_move_line=best_move_line,
        sections="\n\n".join(sections),
        move_instructions=move_instructions,
        takeaway_instruction=takeaway_instruction,
        level_instructions=level_instructions,
        critical_section=critical_section,
        word_limit=word_limit,
    )
