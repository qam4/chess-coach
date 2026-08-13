"""Tests for prompt construction."""

from __future__ import annotations

import dataclasses

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


# --------------------------------------------------------------------------
# BUG-011 regression: the rich prompts must state side-to-move / student color
# --------------------------------------------------------------------------

from chess_coach.coaching_phrases import uci_to_san as _uci_to_san  # noqa: E402
from chess_coach.models import (  # noqa: E402
    ComparisonReport,
    EvalBreakdown,
    HangingPiece,
    KingSafety,
    PawnFeatures,
    PositionReport,
    PVLine,
    Threat,
)
from chess_coach.prompts import (  # noqa: E402
    _format_perspective,
    _uci_line_to_san,
    build_engine_move_explanation_prompt,
    build_rich_coaching_prompt,
    build_rich_move_evaluation_prompt,
    build_socratic_prompt,
)

WHITE_TO_MOVE_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
# After 1.e4 e5 2.Qh5 — Black to move (the BUG-011 repro position).
BLACK_TO_MOVE_FEN = "rnbqkbnr/pppp1ppp/8/4p2Q/4P3/8/PPPP1PPP/RNB1KBNR b KQkq - 1 2"


def _position_report(fen: str) -> PositionReport:
    """Minimal valid PositionReport for prompt construction."""
    empty_pawns = PawnFeatures([], [], [])
    return PositionReport(
        fen=fen,
        eval_cp=17,
        eval_breakdown=EvalBreakdown(material=0, mobility=0, king_safety=0, pawn_structure=0),
        hanging_pieces={"white": [], "black": []},
        threats={"white": [], "black": []},
        pawn_structure={"white": empty_pawns, "black": empty_pawns},
        king_safety={"white": KingSafety(0, ""), "black": KingSafety(0, "")},
        top_lines=[],
        tactics=[],
        threat_map=[],
        threat_map_summary=None,
        critical_moment=False,
        critical_reason=None,
    )


def _comparison_report(fen: str) -> ComparisonReport:
    """Minimal valid ComparisonReport for prompt construction."""
    return ComparisonReport(
        fen=fen,
        user_move="g8f6",
        user_eval_cp=0,
        best_move="b8c6",
        best_eval_cp=17,
        eval_drop_cp=17,
        classification="good",
        nag="!?",
        best_move_idea="develop and defend",
        refutation_line=None,
        missed_tactics=[],
        top_lines=[],
        critical_moment=False,
        critical_reason=None,
    )


class TestPerspective:
    """The rich prompts must make side-to-move explicit (BUG-011)."""

    def test_format_perspective_black_to_move(self) -> None:
        text = _format_perspective(BLACK_TO_MOVE_FEN)
        assert "Side to move: Black" in text
        assert "Black pieces" in text

    def test_format_perspective_white_to_move(self) -> None:
        text = _format_perspective(WHITE_TO_MOVE_FEN)
        assert "Side to move: White" in text
        assert "White pieces" in text

    def test_format_perspective_defaults_to_white_on_malformed_fen(self) -> None:
        # A FEN with no active-color field should not raise.
        assert "Side to move: White" in _format_perspective("8/8/8/8/8/8/8/8")

    def test_coaching_prompt_names_black_side_to_move(self) -> None:
        prompt = build_rich_coaching_prompt(_position_report(BLACK_TO_MOVE_FEN), "beginner")
        assert "Side to move: Black" in prompt
        assert "Black pieces" in prompt

    def test_coaching_prompt_names_white_side_to_move(self) -> None:
        prompt = build_rich_coaching_prompt(_position_report(WHITE_TO_MOVE_FEN), "beginner")
        assert "Side to move: White" in prompt

    def test_coaching_prompt_states_eval_is_white_relative(self) -> None:
        prompt = build_rich_coaching_prompt(_position_report(BLACK_TO_MOVE_FEN), "beginner")
        assert "White's perspective" in prompt

    def test_move_evaluation_prompt_names_black_side_to_move(self) -> None:
        prompt = build_rich_move_evaluation_prompt(_comparison_report(BLACK_TO_MOVE_FEN), "beginner")
        assert "Side to move: Black" in prompt
        assert "Black pieces" in prompt

    def test_engine_move_explanation_prompt_names_black_side_to_move(self) -> None:
        # BUG-011's last unpatched path: web play-mode engine-move explanation.
        prompt = build_engine_move_explanation_prompt(
            fen_before=BLACK_TO_MOVE_FEN,
            engine_move="Be7",
            analysis_text="(analysis)",
            level="beginner",
        )
        assert "Side to move: Black" in prompt
        assert "Black pieces" in prompt


# --------------------------------------------------------------------------
# Move-decoding fix: prompts should present moves in SAN (named piece), not
# raw UCI coordinates the model misreads (move-feedback eval finding).
# --------------------------------------------------------------------------

# After 1.e4 e5 2.Nf3 Nc6 3.Bc4 Bc5 — White to move, castling is legal here.
CASTLE_FEN = "r1bqk1nr/pppp1ppp/2n5/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"


def _move_eval_report(fen: str, user_move: str, best_move: str, eval_drop_cp: int = 70) -> ComparisonReport:
    return ComparisonReport(
        fen=fen,
        user_move=user_move,
        user_eval_cp=-50,
        best_move=best_move,
        best_eval_cp=20,
        eval_drop_cp=eval_drop_cp,
        classification="mistake",
        nag="?",
        best_move_idea="develop a piece",
        refutation_line=None,
        missed_tactics=[],
        top_lines=[],
        critical_moment=False,
        critical_reason=None,
    )


class TestUciToSan:
    """UCI->SAN conversion with safe fallback."""

    def test_king_move(self) -> None:
        # Black to move (after 1.e4 e5 2.Qh5); e8e7 is a king move.
        assert _uci_to_san(BLACK_TO_MOVE_FEN, "e8e7") == "Ke7"

    def test_knight_move(self) -> None:
        assert _uci_to_san(BLACK_TO_MOVE_FEN, "b8c6") == "Nc6"

    def test_castling(self) -> None:
        assert _uci_to_san(CASTLE_FEN, "e1g1") == "O-O"

    def test_illegal_move_falls_back_to_uci(self) -> None:
        assert _uci_to_san(BLACK_TO_MOVE_FEN, "a1a8") == "a1a8"

    def test_garbage_falls_back(self) -> None:
        assert _uci_to_san(BLACK_TO_MOVE_FEN, "notamove") == "notamove"

    def test_line_converts_to_san(self) -> None:
        # b8c6 (Nc6) then f1c4 (Bc4) is a legal sequence from this position.
        assert _uci_line_to_san(BLACK_TO_MOVE_FEN, ["b8c6", "f1c4"]) == "Nc6 Bc4"

    def test_line_truncates_at_unreplayable_move(self) -> None:
        # First move legal (Nc6), second unreplayable -> TRUNCATE with an
        # ellipsis. Raw coordinates must never reach the prompt: they are
        # unreadable for a student and invite the model to guess a piece.
        out = _uci_line_to_san(BLACK_TO_MOVE_FEN, ["b8c6", "z9z9"])
        assert out == "Nc6 ..."

    def test_line_empty_when_nothing_converts(self) -> None:
        # Not even the first move replays -> empty, so callers omit the section.
        assert _uci_line_to_san(BLACK_TO_MOVE_FEN, ["z9z9", "b8c6"]) == ""


class TestMoveEvaluationUsesSan:
    """The move-evaluation prompt must name the moved piece, not show UCI."""

    def test_king_move_shown_as_san(self) -> None:
        report = _move_eval_report(BLACK_TO_MOVE_FEN, "e8e7", "b8c6")
        prompt = build_rich_move_evaluation_prompt(report, "beginner")
        assert "Ke7" in prompt  # student's move, named
        assert "Nc6" in prompt  # best move, named
        assert "e8e7" not in prompt  # raw UCI gone
        assert "b8c6" not in prompt

    def test_castling_shown_as_san(self) -> None:
        report = _move_eval_report(CASTLE_FEN, "e1g1", "d2d3")
        prompt = build_rich_move_evaluation_prompt(report, "beginner")
        assert "O-O" in prompt
        assert "e1g1" not in prompt


class TestPlayedBestMove:
    """BUG-014: when the student played the engine's top move, the prompt must
    affirm it and forbid inventing a 'better' alternative."""

    def test_played_best_affirms_and_forbids_alternative(self) -> None:
        report = _move_eval_report(BLACK_TO_MOVE_FEN, "b8c6", "b8c6")  # user == best
        prompt = build_rich_move_evaluation_prompt(report, "intermediate")
        assert "there is no better move here" in prompt
        assert 'Do NOT suggest a different or "better" move' in prompt
        assert "No motivational sign-off" in prompt  # severity/verbosity fix (lever 3)
        # Lever 9: voice the engine's specific idea, not a generic principle.
        assert 'use "What the best move achieves"' in prompt
        # Not the mistake-tier framing.
        assert "serious mistake" not in prompt
        assert "slightly missed the mark" not in prompt

    def test_sound_move_affirms_but_may_note_stronger_move(self) -> None:
        # user != best, small eval drop (within the sound band): affirm the move,
        # a genuinely better move may be a refinement (BUG-016), kept short.
        report = _move_eval_report(BLACK_TO_MOVE_FEN, "e8e7", "b8c6", eval_drop_cp=30)
        prompt = build_rich_move_evaluation_prompt(report, "intermediate")
        assert "sound, reasonable move" in prompt
        assert "as a refinement" in prompt
        assert "there is no better move here" not in prompt
        assert "serious mistake" not in prompt

    def test_inaccuracy_uses_brief_redirect(self) -> None:
        # drop in (SOUND, DUBIOUS] -> inaccuracy tier: brief, not dramatized.
        report = _move_eval_report(BLACK_TO_MOVE_FEN, "e8e7", "b8c6", eval_drop_cp=70)
        prompt = build_rich_move_evaluation_prompt(report, "intermediate")
        assert "slightly missed the mark" in prompt
        assert "serious mistake" not in prompt
        assert "sound, reasonable move" not in prompt

    def test_serious_mistake_is_direct(self) -> None:
        # drop past the dubious band -> serious tier: direct, lead with the cost.
        report = _move_eval_report(BLACK_TO_MOVE_FEN, "e8e7", "b8c6", eval_drop_cp=300)
        prompt = build_rich_move_evaluation_prompt(report, "intermediate")
        assert "serious mistake" in prompt
        assert "Lead with the cost" in prompt
        assert "slightly missed the mark" not in prompt
        assert "No motivational sign-off" in prompt


def test_refutation_renders_only_first_reply() -> None:
    # The opponent's reply section surfaces only the FIRST ply (a single move),
    # not the whole PV — feeding the full line made the model recite move-salad.
    report = ComparisonReport(
        fen="rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
        user_move="e1e2",  # Ke2, a mistake
        user_eval_cp=-100,
        best_move="g1f3",
        best_eval_cp=20,
        eval_drop_cp=120,  # serious tier
        classification="mistake",
        nag="?",
        best_move_idea="develop a piece",
        refutation_line=["d8h4", "e2e1"],  # Qh4 then a second ply that must NOT be rendered
        missed_tactics=[],
        top_lines=[],
        critical_moment=False,
        critical_reason=None,
    )
    prompt = build_rich_move_evaluation_prompt(report, "intermediate")
    assert "Opponent's reply" in prompt
    assert "strongest reply is Qh4" in prompt  # single move rendered
    assert "name that single reply" in prompt  # serious tier voices one reply


def test_move_eval_prompt_requires_named_principle_and_hook() -> None:
    # Lever 10 (the judge's #1): replace the generic trailing maxim with a named
    # principle + a transferable "next time..., ask yourself..." hook — end-1 of
    # the bridge every turn. Applies across tiers (shared closing directive).
    for drop in (0, 30, 70, 300):
        report = _move_eval_report(BLACK_TO_MOVE_FEN, "e8e7", "b8c6", eval_drop_cp=drop)
        prompt = build_rich_move_evaluation_prompt(report, "intermediate")
        assert "CLOSE with one transferable takeaway" in prompt
        assert "ask yourself" in prompt


def test_takeaway_lesson_is_composed_from_what_the_move_does() -> None:
    # The coach used to pick the lesson and reached for the same three ideas on 68%
    # of turns — closing with "next time you see a fork opportunity" about a move
    # that forks nothing. The subject now comes from the verified effect.
    import chess

    from chess_coach.prompts import _build_takeaway_instruction

    # After 1.e4 e5 2.Qh5, the queen attacks e5 and Nc6 defends it — so the lesson
    # is defending, not developing. Worth pinning: the composed lesson tracks what
    # the move actually does, which is not always the move's most obvious feature.
    report = _move_eval_report(BLACK_TO_MOVE_FEN, "e8e7", "b8c6", eval_drop_cp=300)
    instruction = _build_takeaway_instruction(report)
    assert "on THIS lesson and no other" in instruction
    assert "defending what you already have" in instruction
    assert "fork" not in instruction

    # An endgame king walk gets the endgame lesson, which the judge said never
    # appeared once across 18 endgame turns.
    endgame = dataclasses.replace(
        _move_eval_report("8/8/4k3/8/4P3/4K3/8/8 w - - 0 1", "e3f3", "e3d4"),
        best_move="e3d4",
    )
    assert "king is a fighting piece" in _build_takeaway_instruction(endgame)

    # A capture gets the capture-value lesson, not a developing one.
    board = chess.Board(CASTLE_FEN)
    assert board.piece_at(chess.E5) is not None  # the pawn Nxe5 takes
    capture = dataclasses.replace(_move_eval_report(CASTLE_FEN, "d2d3", "f3e5"), best_move="f3e5")
    assert "what a capture is worth" in _build_takeaway_instruction(capture)


def test_takeaway_falls_back_when_the_move_cannot_be_verified() -> None:
    # No verifiable effect means no composed lesson: the model chooses, rather than
    # us inventing one. Same rule the clause composer follows.
    from chess_coach.prompts import _build_takeaway_instruction

    # A bishop landing on e4 with nothing to show for it (see the Change A tests).
    quiet = dataclasses.replace(
        _move_eval_report("7k/8/8/8/8/8/8/K6B w - - 0 1", "a1a2", "h1e4"),
        best_move="h1e4",
    )
    instruction = _build_takeaway_instruction(quiet)
    assert 'Do NOT end with "focus on developing your pieces"' in instruction
    assert "on THIS lesson and no other" not in instruction


def test_refutation_states_captured_piece() -> None:
    # Lever 8: the opponent's-reply block states WHAT the reply captures,
    # computed from the board (verified) — the coach voices it, never invents it.
    report = ComparisonReport(
        fen="4k3/8/5p2/6N1/8/8/8/3K4 w - - 0 1",  # White Ng5; Black f6 pawn can take it
        user_move="d1c1",  # a quiet king move that leaves the knight hanging
        user_eval_cp=-300,
        best_move="g5f3",  # save the knight
        best_eval_cp=0,
        eval_drop_cp=300,
        classification="blunder",
        nag="??",
        best_move_idea="save the knight",
        refutation_line=["f6g5"],  # ...fxg5 captures the knight
        missed_tactics=[],
        top_lines=[],
        critical_moment=False,
        critical_reason=None,
    )
    prompt = build_rich_move_evaluation_prompt(report, "intermediate")
    assert "Opponent's reply" in prompt
    assert "capturing your knight on g5" in prompt


def test_sentinel_no_raw_uci_survives_in_move_eval_prompt() -> None:
    # SENTINEL (CI guard): _uci_line_to_san degrades to raw UCI when handed the
    # wrong base position, silently. A log warning is not a guard — nobody reads
    # logs — so assert here that NO bare UCI token (e.g. "f6g4") survives in a
    # rendered comparison prompt, across every severity tier.
    import re

    uci_token = re.compile(r"\b[a-h][1-8][a-h][1-8][qrbn]?\b")
    fen = "r1bqkb1r/pppp1ppp/4pn2/4n1N1/2B5/4P3/PPPP1PPP/RNBQK2R w KQkq - 2 5"
    for drop in (0, 30, 70, 300):
        report = ComparisonReport(
            fen=fen,
            user_move="b2b3",
            user_eval_cp=-183,
            best_move="g5f3",  # a legal white move in this position
            best_eval_cp=-45,
            eval_drop_cp=drop,
            classification="mistake",
            nag="?",
            best_move_idea="piece activity",
            refutation_line=["f6g4", "f2f4"],
            missed_tactics=[],
            top_lines=[PVLine(depth=11, eval_cp=183, moves=["f6g4", "f2f4"], theme="general play")],
            critical_moment=False,
            critical_reason=None,
        )
        prompt = build_rich_move_evaluation_prompt(report, "intermediate")
        leaked = uci_token.findall(prompt)
        assert not leaked, f"raw UCI leaked into the prompt (drop={drop}): {leaked}"


def test_best_move_achievement_is_position_specific() -> None:
    # Item 3: best_move_idea is a category label ("pawn structure — improving
    # pawn position"), so voicing it can only yield category sentences. Prepend
    # a board-derived fact; keep the label as the theme. Real position from the
    # game: a3 is best because it hits an undefended bishop on b4, which the
    # label never says.
    from chess_coach.prompts import _best_move_achievement

    report = ComparisonReport(
        fen="rn1qkb1r/pppp1ppp/4pn2/6N1/1b6/1P2P3/P1PP1PPP/RNBQKB1R w KQkq - 0 6",
        user_move="d2d4",
        user_eval_cp=0,
        best_move="a2a3",
        best_eval_cp=90,
        eval_drop_cp=90,
        classification="inaccuracy",
        nag="?!",
        best_move_idea="pawn structure — improving pawn position",
        refutation_line=None,
        missed_tactics=[],
        top_lines=[],
        critical_moment=False,
        critical_reason=None,
    )
    # (the b4 bishop is defended by the f8 bishop along f8-b4, so it is
    # "attacking their bishop", not "undefended" — verified against the board)
    out = _best_move_achievement(report)
    assert out == "attacking their bishop on b4 (pawn structure — improving pawn position)"
    assert out in build_rich_move_evaluation_prompt(report, "intermediate")


def test_best_move_achievement_falls_back_to_label_without_invention() -> None:
    # Nothing verifiable about a quiet move -> return the label unchanged rather
    # than inventing a concrete-sounding reason.
    from chess_coach.prompts import _best_move_achievement

    report = _move_eval_report(CASTLE_FEN, "e1g1", "d2d3")
    report = dataclasses.replace(report, best_move_idea="pawn structure — improving pawn position")
    assert _best_move_achievement(report) == "pawn structure — improving pawn position"


# White Kf2, pawn d5, black Ke7 — a king-and-pawn endgame by the shared phase
# heuristic (major/minor count is 0).
ENDGAME_KINGS_FEN = "8/4k3/8/3P4/8/8/5K2/8 w - - 0 40"


def test_king_safety_label_dropped_in_the_endgame() -> None:
    # The label inverts in an endgame: the king is a fighting piece there, so
    # "king safety — repositioning the king" told the student to do the opposite
    # of the winning idea. It arrived on 8 of 18 endgame turns in a 44-turn game,
    # in the highest-value line of the prompt. No substitute label — swapping one
    # category word for another is what failed when the lesson table was
    # phase-gated — so the line is omitted entirely.
    from chess_coach.prompts import _best_move_achievement, _best_move_achievement_line

    report = _move_eval_report(ENDGAME_KINGS_FEN, "f2e3", "f2f3")
    report = dataclasses.replace(report, best_move_idea="king safety — repositioning the king")
    assert _best_move_achievement(report) == ""
    assert _best_move_achievement_line(report) == ""
    prompt = build_rich_move_evaluation_prompt(report, "intermediate")
    assert "What the best move achieves:" not in prompt
    # And the instructions must not still point at the dropped section — a
    # dangling reference is an invitation to invent what it would have said.
    assert '"What the best move achieves" shown above' not in prompt
    # The only surviving mention is the instruction telling it NOT to close on
    # king safety; nothing asserts king safety as a fact about this position.
    assert "king safety — repositioning" not in prompt


def test_endgame_keeps_the_verified_clause_and_drops_only_the_label() -> None:
    # The common case: on 6 of the 8 affected turns in a real game the composer
    # HAD a board-derived clause and the engine's label was simply the wrong frame
    # for it. Keep the fact, drop the frame — never the other way round.
    from chess_coach.prompts import _best_move_achievement

    # White Kf2 with a black rook on f4 attacking down the file; Ke3 steps off f2.
    fen = "8/4k3/8/8/5r2/8/5K2/8 w - - 0 40"
    report = _move_eval_report(fen, "f2e2", "f2e3")
    report = dataclasses.replace(report, best_move_idea="king safety — repositioning the king")
    out = _best_move_achievement(report)
    assert out
    assert "king safety" not in out
    assert "(" not in out  # no empty parenthetical left behind


def test_king_safety_label_kept_outside_the_endgame() -> None:
    # Same label, middlegame position: here it is correct advice and stays.
    from chess_coach.prompts import _best_move_achievement

    report = _move_eval_report(CASTLE_FEN, "e1g1", "d2d3")
    report = dataclasses.replace(report, best_move_idea="king safety — castling to a safer position")
    assert "king safety" in _best_move_achievement(report)


def test_pedagogy_block_does_not_plant_king_safety_every_turn() -> None:
    # The hardcoded example seeded "is my king safe?" into all 44 turns of a game,
    # endgames included — the same wrong lesson the guidance exclusion removed,
    # arriving by another route.
    from chess_coach.prompts import SYSTEM_PROMPT_V2

    assert "is my king safe" not in SYSTEM_PROMPT_V2.lower()


def test_numbered_san_marks_whose_move_it_is() -> None:
    # A bare SAN sequence hid side: the coach read "Nfg4 f4" and announced "the
    # opponent plays f4" — f4 is the STUDENT's move. Numbering makes the
    # alternation explicit. Move numbers come from the board, so the Black-start
    # convention and truncation must both stay correct (off-by-one hazard).
    import chess

    from chess_coach.prompts import _uci_line_to_numbered_san

    after_b3 = chess.Board("r1bqkb1r/pppp1ppp/4pn2/4n1N1/2B5/4P3/PPPP1PPP/RNBQK2R w KQkq - 2 5")
    after_b3.push_uci("b2b3")
    assert _uci_line_to_numbered_san(after_b3.fen(), ["f6g4", "f2f4", "e5c4", "b3c4"]) == "5...Nfg4 6.f4 Nxc4 7.bxc4"

    # White to move -> no "..." prefix.
    assert _uci_line_to_numbered_san(chess.STARTING_FEN, ["e2e4", "e7e5", "g1f3"]) == "1.e4 e5 2.Nf3"

    # Numbering survives truncation of the engine's corrupt tail (BUG-019).
    after_nf3 = chess.Board(chess.STARTING_FEN)
    after_nf3.push_uci("g1f3")
    corrupt = ["b8c6", "b1c3", "g8f6", "e2e3", "e7e6", "f1d3", "c6b4", "e8g8", "b4d3"]
    assert _uci_line_to_numbered_san(after_nf3.fen(), corrupt) == "1...Nc6 2.Nc3 Nf6 3.e3 e6 4.Bd3 Nb4 ..."

    # Nothing convertible -> empty, so the caller omits the section.
    assert _uci_line_to_numbered_san(chess.STARTING_FEN, ["z9z9"]) == ""


def test_top_lines_section_names_which_side_is_the_opponent() -> None:
    # The fixture needs a real line: the header is only emitted when at least one
    # line renders. It used to be printed unconditionally, which is how 19 of 44
    # prompts ended up carrying a header with nothing under it while the
    # instructions told the coach to use only facts from that section.
    report = dataclasses.replace(
        _move_eval_report(BLACK_TO_MOVE_FEN, "e8e7", "b8c6", eval_drop_cp=300),
        top_lines=[PVLine(depth=8, eval_cp=120, moves=["b8c6", "h5e5"], theme="material win")],
    )
    prompt = build_rich_move_evaluation_prompt(report, "intermediate")
    # Student is Black here, so White is the opponent — stated explicitly.
    assert "White = your opponent" in prompt
    assert "Black = you" in prompt


def test_top_lines_section_is_omitted_entirely_when_nothing_renders() -> None:
    # No header without content. An empty section is worse than no section: the
    # grounding instructions point at it, so the coach was told to rely on facts
    # that were not there.
    report = _move_eval_report(BLACK_TO_MOVE_FEN, "e8e7", "b8c6", eval_drop_cp=300)
    assert "Top Engine Lines" not in build_rich_move_evaluation_prompt(report, "intermediate")


def test_top_lines_say_which_position_they_start_from() -> None:
    # The engine's lines are relative to the position BEFORE the student's move
    # (they include the student's own alternatives), so the coach is told that —
    # otherwise a line of alternatives and a line of refutation read identically.
    report = dataclasses.replace(
        _move_eval_report(BLACK_TO_MOVE_FEN, "e8e7", "b8c6", eval_drop_cp=300),
        top_lines=[PVLine(depth=8, eval_cp=120, moves=["b8c6", "h5e5"], theme="material win")],
    )
    prompt = build_rich_move_evaluation_prompt(report, "intermediate")
    assert "from the position you were in" in prompt
    # Rendered as SAN, from the right base — never coordinates.
    assert "Nc6" in prompt
    assert "b8c6" not in prompt


def test_comparison_top_lines_render_san_not_uci() -> None:
    # Regression (found via the report card): a ComparisonReport's top_lines
    # describe the position AFTER the student's move, so converting from
    # report.fen made the first move illegal and dumped the whole line as raw
    # UCI ("f6g4 f2f4 ..."). The coach then parroted coordinates and invented
    # what the move did. Real position + line from the v14 transcript.
    report = ComparisonReport(
        fen="r1bqkb1r/pppp1ppp/4pn2/4n1N1/2B5/4P3/PPPP1PPP/RNBQK2R w KQkq - 2 5",
        user_move="b2b3",  # the student's mistake
        user_eval_cp=-183,
        best_move="f1e2",
        best_eval_cp=-45,
        eval_drop_cp=138,
        classification="mistake",
        nag="?",
        best_move_idea="piece activity",
        refutation_line=None,
        missed_tactics=[],
        top_lines=[PVLine(depth=11, eval_cp=183, moves=["f6g4", "f2f4"], theme="general play")],
        critical_moment=False,
        critical_reason=None,
    )
    prompt = build_rich_move_evaluation_prompt(report, "intermediate")
    assert "Nfg4" in prompt  # SAN, from the post-move position
    assert "f6g4" not in prompt  # raw coordinates gone


def test_refutation_clause_describes_non_captures() -> None:
    # Item 2: non-capture refutations previously reached the coach as a bare
    # move, so the model invented the "why". Now the clause is composed from the
    # board. Positions verified against python-chess; black (opponent) to move.
    import chess

    from chess_coach.prompts import _refutation_capture_clause

    fork = chess.Board("7k/8/8/6Q1/5R2/8/8/K5n1 b - - 0 1")
    assert _refutation_capture_clause(fork, "g1h3") == ", hitting your queen on g5 and your rook on f4"

    undefended = chess.Board("7k/8/8/8/5R2/8/8/K5n1 b - - 0 1")
    assert _refutation_capture_clause(undefended, "g1h3") == ", attacking your undefended rook on f4"

    check_only = chess.Board("4k2q/8/8/8/8/8/PPPP2PP/4K3 b - - 0 1")
    assert _refutation_capture_clause(check_only, "h8e5") == ", giving check"

    # A quiet move that hits nothing yields no invented clause.
    quiet = chess.Board("4k3/8/8/8/8/8/8/K5n1 b - - 0 1")
    assert _refutation_capture_clause(quiet, "g1e2") == ""
    # Captures still take precedence and keep their wording.
    cap = chess.Board("4k3/8/5p2/6N1/8/8/8/4K3 b - - 0 1")
    assert _refutation_capture_clause(cap, "f6g5") == ", capturing your knight on g5"


def test_move_eval_word_limit_scales_with_severity() -> None:
    # Lever 4: a best move gets a tight word limit; a serious mistake gets more
    # room. Also expose the per-tier max_tokens ordering.
    from chess_coach.prompts import move_feedback_max_tokens

    best = _move_eval_report(BLACK_TO_MOVE_FEN, "b8c6", "b8c6")  # exact best
    serious = _move_eval_report(BLACK_TO_MOVE_FEN, "e8e7", "b8c6", eval_drop_cp=300)
    assert "under 40 words" in build_rich_move_evaluation_prompt(best, "intermediate")
    assert "under 120 words" in build_rich_move_evaluation_prompt(serious, "intermediate")
    assert move_feedback_max_tokens(best) < move_feedback_max_tokens(serious)


def test_move_eval_prompt_grounds_pawn_structure() -> None:
    # BUG-018: the move-eval prompt must carry board-derived pawn-structure
    # facts so the coach grounds isolated/doubled claims instead of guessing.
    # White: a2 isolated, c-file doubled (c2,c3); a legal white move exists.
    fen = "4k3/4pp2/8/8/8/2P5/P1P1PP2/4K3 w - - 0 1"
    report = _move_eval_report(fen, "e2e4", "c3c4")
    prompt = build_rich_move_evaluation_prompt(report, "intermediate")
    assert "--- Pawn structure (from the board) ---" in prompt
    assert "isolated pawns: a2" in prompt
    assert "doubled pawns: c-file" in prompt


# --------------------------------------------------------------------------
# Socratic mode: the prompt must ask guiding questions and must NOT leak the
# answer (best move, top lines, or the evaluation).
# --------------------------------------------------------------------------


def _socratic_report() -> PositionReport:
    """A report with a threat, a hanging pawn, a strong eval, and a PV.

    Used to confirm the Socratic prompt grounds questions in the qualitative
    features while withholding the eval (250cp) and the solution moves.
    """
    empty_pawns = PawnFeatures([], [], [])
    return PositionReport(
        fen=BLACK_TO_MOVE_FEN,
        eval_cp=250,
        eval_breakdown=EvalBreakdown(material=250, mobility=10, king_safety=0, pawn_structure=0),
        hanging_pieces={
            "white": [],
            "black": [HangingPiece(square="e5", piece="pawn", color="black")],
        },
        threats={
            "white": [
                Threat(
                    type="capture",
                    source_square="h5",
                    target_squares=["e5"],
                    description="White queen can capture the undefended e5 pawn",
                    uci_move="h5e5",
                )
            ],
            "black": [],
        },
        pawn_structure={"white": empty_pawns, "black": empty_pawns},
        king_safety={"white": KingSafety(0, "castled"), "black": KingSafety(-20, "king exposed")},
        top_lines=[PVLine(depth=12, eval_cp=250, moves=["b8c6", "f1c4"], theme="")],
        tactics=[],
        threat_map=[],
        threat_map_summary=None,
        critical_moment=False,
        critical_reason=None,
    )


class TestSocraticPrompt:
    """build_socratic_prompt asks questions, grounded, without the answer."""

    def test_asks_guiding_questions(self) -> None:
        prompt = build_socratic_prompt(_socratic_report(), "beginner")
        assert "guiding questions" in prompt
        assert "Do not give the answer, the best move, or the evaluation" in prompt

    def test_states_side_to_move(self) -> None:
        prompt = build_socratic_prompt(_socratic_report(), "beginner")
        assert "Side to move: Black" in prompt

    def test_grounded_in_features(self) -> None:
        # The questions should be able to point at the real hanging pawn / threat.
        prompt = build_socratic_prompt(_socratic_report(), "beginner")
        assert "e5" in prompt  # the hanging pawn the student should notice

    def test_does_not_reveal_evaluation(self) -> None:
        prompt = build_socratic_prompt(_socratic_report(), "beginner")
        assert "250" not in prompt
        assert "+2.5" not in prompt
        assert "--- Material Balance ---" not in prompt

    def test_does_not_reveal_best_move_or_pv(self) -> None:
        prompt = build_socratic_prompt(_socratic_report(), "beginner")
        assert "Top Engine Lines" not in prompt
        assert "b8c6" not in prompt  # raw best move withheld
        assert "Nc6" not in prompt  # and its SAN

    def test_grounding_rules_present(self) -> None:
        prompt = build_socratic_prompt(_socratic_report(), "beginner")
        assert "Never reveal or name the best move" in prompt


# --------------------------------------------------------------------------
# Candidate move menu + move-sourcing constraint (grounded-move-advice spec)
# --------------------------------------------------------------------------


def _report_with_lines(fen: str, lines: list[PVLine]) -> PositionReport:
    return dataclasses.replace(_position_report(fen), top_lines=lines)


_MENU_LINES = [
    PVLine(depth=18, eval_cp=30, moves=["e2e4"], theme="central pawn break"),
    PVLine(depth=18, eval_cp=10, moves=["g1f3"], theme="piece development"),
    PVLine(depth=18, eval_cp=-80, moves=["a2a3"], theme="general play"),
]


def test_rich_prompt_shows_candidate_menu_with_tags() -> None:
    prompt = build_rich_coaching_prompt(_report_with_lines(WHITE_TO_MOVE_FEN, _MENU_LINES))
    assert "Candidate moves (engine-verified)" in prompt
    assert "Top Engine Lines" not in prompt  # menu replaces the raw lines
    # SAN, not coordinates.
    assert "e4" in prompt and "Nf3" in prompt
    assert "e2e4" not in prompt
    # Soundness tags present.
    assert "best" in prompt and "sound" in prompt and "blunder" in prompt


def test_rich_prompt_move_sourcing_rule_present_when_constrained() -> None:
    prompt = build_rich_coaching_prompt(_report_with_lines(WHITE_TO_MOVE_FEN, _MENU_LINES), constrain_moves=True)
    assert "Choosing a move" in prompt
    assert "not in the menu" in prompt


def test_rich_prompt_move_sourcing_rule_absent_when_unconstrained() -> None:
    prompt = build_rich_coaching_prompt(_report_with_lines(WHITE_TO_MOVE_FEN, _MENU_LINES), constrain_moves=False)
    assert "Choosing a move" not in prompt
    # The menu is still shown; only the restriction is dropped.
    assert "Candidate moves (engine-verified)" in prompt


def test_rich_prompt_san_instruction_always_present() -> None:
    report = _report_with_lines(WHITE_TO_MOVE_FEN, _MENU_LINES)
    for constrain in (True, False):
        prompt = build_rich_coaching_prompt(report, constrain_moves=constrain)
        assert "standard algebraic notation" in prompt


def test_rich_prompt_grounding_rules_retained() -> None:
    prompt = build_rich_coaching_prompt(_report_with_lines(WHITE_TO_MOVE_FEN, _MENU_LINES))
    assert "Never invent" in prompt
    assert "Only use information from the engine data" in prompt


def test_rich_prompts_forbid_invented_continuations() -> None:
    # BUG-013: the coach must not narrate fabricated multi-move follow-up lines.
    # The shared system grounding rule carries the constraint into both paths.
    coaching = build_rich_coaching_prompt(_report_with_lines(WHITE_TO_MOVE_FEN, _MENU_LINES))
    assert "inventing concrete continuations" in coaching
    assert '"and then..."' in coaching

    move_eval = build_rich_move_evaluation_prompt(_move_eval_report(BLACK_TO_MOVE_FEN, "e8e7", "b8c6"), "intermediate")
    assert "inventing concrete continuations" in move_eval  # shared system rule
    assert '"and then..." continuations' in move_eval  # reinforced in the move-eval tier


def test_rich_prompt_no_menu_no_sourcing_rule_when_lines_empty() -> None:
    # Empty top_lines -> no menu -> the move-sourcing rule is omitted even
    # when the constraint is on (there is no sound move to name).
    prompt = build_rich_coaching_prompt(_position_report(WHITE_TO_MOVE_FEN), constrain_moves=True)
    assert "Candidate moves (engine-verified)" not in prompt
    assert "Choosing a move" not in prompt


# --- Change A: describe the quiet moves too -------------------------------
#
# Measured before writing any of it: 13 of 44 best moves in one game reached the
# composer with nothing to say and got only the engine's category label ("rook
# activity — improving rook placement"), which the coach can only restate. Each
# clause below states squares, counts or a file — things a student can check on
# the board — rather than naming the idea the label already named.


def _clause(fen: str, san: str) -> str:
    import chess

    from chess_coach.prompts import _move_effect_clause

    board = chess.Board(fen)
    move = board.parse_san(san)
    return _move_effect_clause(board, move.uci(), target_possessive="their ").removeprefix(", ")


def test_quiet_clause_names_the_open_file() -> None:
    assert _clause("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1", "Ra4") == "moving your rook to a4 on the open a-file"


def test_quiet_clause_distinguishes_half_open_from_open() -> None:
    # Black has a pawn on a7, we have none on the a-file: half-open for us.
    assert _clause("r5k1/p4ppp/8/8/8/8/5PPP/R5K1 w - - 0 1", "Ra4") == "moving your rook to a4 on the half-open a-file"


def test_quiet_clause_counts_the_squares_a_piece_gains() -> None:
    # The counts are the teaching content: the student can recount them.
    import chess

    out = _clause(chess.STARTING_FEN, "Nc3")
    assert out == "moving your knight from b1 to c3, where it covers 5 squares instead of 2"


def test_quiet_clause_excludes_the_king_from_the_square_count() -> None:
    # A king may not move into check, so counting attacked squares overstates
    # where it can actually go — and the move this came from (an early Ke2 after
    # losing castling rights) is usually forced rather than an improvement.
    out = _clause("rnbqkbnr/pppppppp/8/8/8/8/PPPPKPPP/RNBQ1BNR w kq - 0 1", "Ke1")
    assert "squares instead of" not in out


def test_quiet_clause_describes_castling_concretely() -> None:
    out = _clause(CASTLE_FEN, "O-O")
    assert out == "castling short to tuck your king onto g1 and connect your rooks"


def test_quiet_clause_walks_the_king_in_only_in_an_endgame() -> None:
    # King and pawn versus king: the project's own endgame test passes, and d4 is
    # genuinely closer to the centre than e3.
    endgame = "8/8/4k3/8/4P3/4K3/8/8 w - - 0 1"
    assert _clause(endgame, "Kd4") == "walking your king from e3 to d4, closer to the centre"
    # The same shape of move with a full board is not an endgame, so no claim.
    assert "closer to the centre" not in _clause(CASTLE_FEN, "Kf1")


def test_quiet_clause_reports_an_extra_defender_as_extra() -> None:
    # Bishop c4 is attacked by the a6 bishop and already defended by the b3 pawn,
    # so Na3 ADDS a defender rather than being the only one — said as such.
    fen = "rn1qkbnr/pppp1ppp/b7/4p3/2B1P3/1P6/P1PP1PPP/RNBQK1NR w KQkq - 0 1"
    assert _clause(fen, "Na3") == "adding a defender to your bishop on c4"


def test_quiet_clause_says_nothing_about_bare_centralisation() -> None:
    # "Toward the centre" was the largest bucket in the measurement and is just
    # another label — and we flag the coach elsewhere for calling non-central
    # squares central. A bishop landing squarely on e4 with nothing else to show
    # for it gets no invented reason.
    assert _clause("7k/8/8/8/8/8/8/K6B w - - 0 1", "Be4") == ""


def test_takeaway_lesson_is_phase_specific() -> None:
    # The judge's follow-up: the composed lessons were phase-blind. Ply 72 got a
    # generic "rook on an open file" tip in a rook endgame, where the real principle
    # is the rook behind the passed pawn or cutting the enemy king off; ply 74
    # centralised the king in a pawn endgame and was taught about safety, when in an
    # endgame the king is an attacker. Same board fact, different lesson.
    from chess_coach.pedagogy.features import PHASE_ENDGAME, PHASE_MIDDLEGAME
    from chess_coach.prompts import EFFECT_OPEN_FILE, effect_takeaway

    middlegame = effect_takeaway(EFFECT_OPEN_FILE, PHASE_MIDDLEGAME)
    endgame = effect_takeaway(EFFECT_OPEN_FILE, PHASE_ENDGAME)
    assert "no pawns in its way" in middlegame
    assert "behind your passed pawn" in endgame
    assert "cut the enemy king off" in endgame
    assert middlegame != endgame

    # A phase with no special case falls through to the shared lesson, so the table
    # stays short instead of becoming a speculative matrix.
    assert effect_takeaway(EFFECT_OPEN_FILE, PHASE_MIDDLEGAME) == effect_takeaway(EFFECT_OPEN_FILE)
    # And an unknown category still yields nothing rather than an invented lesson.
    assert effect_takeaway("no_such_effect", PHASE_ENDGAME) == ""


def test_endgame_rook_takeaway_reaches_the_prompt() -> None:
    # End to end: a rook reaching an open file in a rook endgame should teach the
    # endgame principle, not the generic one.
    from chess_coach.prompts import _build_takeaway_instruction

    endgame = dataclasses.replace(
        _move_eval_report("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1", "g1h1", "a1a4"),
        best_move="a1a4",
    )
    instruction = _build_takeaway_instruction(endgame)
    assert "behind your passed pawn" in instruction
    assert "no pawns in its way" not in instruction


def test_king_walk_clause_needs_to_beat_the_students_move() -> None:
    # Found by the frontier judge at ply 1002. White Kf2, pawn d5, black Kf7: the
    # student played the MORE central Ke3, and we told the coach that Kf3 was
    # "closer to the centre" — so it informed the student their more central move
    # was less central. The clause was true of Kf3 in isolation (f2 -> f3 does
    # approach the centre) and wrong as a reason to prefer it.
    import chess

    from chess_coach.prompts import _build_takeaway_instruction, _move_effect

    fen = "8/5k2/8/3P4/8/8/5K2/8 w - - 0 1"
    board = chess.Board(fen)

    # Against a rival that is equally central (e3 vs f3), say nothing.
    assert _move_effect(board, "f2f3", target_possessive="their ", rival_uci="f2e3") == ("", "")
    # Against a rival that stays put on the rim, the claim is a real distinction.
    _category, clause = _move_effect(board, "f2f3", target_possessive="their ", rival_uci="f2g1")
    assert "closer to the centre" in clause
    # And with no rival supplied at all, the isolated fact still stands.
    assert "closer to the centre" in _move_effect(board, "f2f3", target_possessive="their ")[1]

    # End to end: the takeaway must not preach king activity when centralisation is
    # not what separates the moves.
    report = dataclasses.replace(_move_eval_report(fen, "f2e3", "f2f3"), best_move="f2f3")
    assert "fighting piece" not in _build_takeaway_instruction(report)
