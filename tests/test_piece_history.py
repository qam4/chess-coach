"""Tests for the per-game piece provenance record.

This is the record the reviewer said was missing. Diagnosis sat at 5 for four straight
runs (v33, v35, v36, v38) and the stated blocker was never the wording: "the coach sees
one ply and the engine's refutation, so it can only ever report the consequence ...
Every one of those is in the game record and none of it reaches the prompt."

Everything asserted here is bookkeeping about what happened in the game. Nothing in the
module under test evaluates a position, so nothing here does either.
"""

from __future__ import annotations

import chess

from chess_coach.piece_history import PieceHistory

START = chess.STARTING_FEN


def _play(history: PieceHistory, moves: list[str]) -> chess.Board:
    """Play SAN ``moves`` from the start, showing the student's turns to ``history``.

    The student is White. Only White's turns are observed, which is exactly what the
    Coach sees: one ``fen_before`` per coached move and nothing in between.
    """
    board = chess.Board()
    for san in moves:
        move = board.parse_san(san)
        if board.turn == chess.WHITE:
            history.observe(board.fen(), move.uci())
        board.push(move)
    return board


class TestArrival:
    def test_a_piece_that_has_not_moved_has_no_arrival(self):
        h = PieceHistory()
        _play(h, ["e4"])
        # The g1 knight is where it started. "None" is a fact in its own right, and the
        # caller renders it as "still on its starting square" rather than inventing one.
        assert h.arrival_of(chess.G1) is None

    def test_arrival_records_the_move_number_the_student_would_say(self):
        h = PieceHistory()
        # 1.e4 e5 2.Nf3 Nc6 3.Ng5 — the knight reaches g5 on move 3.
        _play(h, ["e4", "e5", "Nf3", "Nc6", "Ng5"])
        arrival = h.arrival_of(chess.G5)
        assert arrival is not None
        assert arrival.move_number == 3
        assert arrival.san == "Ng5"
        assert arrival.piece_name == "knight"

    def test_provenance_follows_the_piece_across_moves(self):
        h = PieceHistory()
        # The v38 case: a bishop shuffled c4 -> e2 -> c4. Its record must describe the
        # LAST arrival, not the first, or the turn reports a stale square.
        _play(h, ["e4", "e5", "Bc4", "Nc6", "Be2", "Nf6", "Bc4"])
        arrival = h.arrival_of(chess.C4)
        assert arrival is not None and arrival.move_number == 4 and arrival.san == "Bc4"
        assert h.arrival_of(chess.E2) is None  # vacated

    def test_a_captured_piece_leaves_no_record_behind(self):
        h = PieceHistory()
        # 1.e4 d5 2.exd5 — the white pawn arrives on d5 by capture. It must not inherit
        # the record of the black pawn it took.
        _play(h, ["e4", "d5", "exd5"])
        arrival = h.arrival_of(chess.D5)
        assert arrival is not None and arrival.san == "exd5" and arrival.move_number == 2

    def test_our_piece_taken_while_we_were_not_looking_is_forgotten(self):
        h = PieceHistory()
        # The knight walks to g5 and is taken by a pawn. We never see Black's move; the
        # entry has to disappear on reconciliation or we would go on describing a piece
        # that is no longer there.
        _play(h, ["e4", "h6", "Nf3", "a6", "Ng5", "hxg5", "d4"])
        assert h.arrival_of(chess.G5) is None

    def test_castling_moves_the_rook_record_too(self):
        h = PieceHistory()
        _play(h, ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5", "O-O"])
        king, rook = h.arrival_of(chess.G1), h.arrival_of(chess.F1)
        assert king is not None and king.piece_type == chess.KING
        # Without this the rook's provenance stays on h1 and the king's record is read
        # for a rook that has quietly moved.
        assert rook is not None and rook.piece_type == chess.ROOK
        assert h.arrival_of(chess.H1) is None

    def test_a_promoted_pawn_is_recorded_as_what_it_became(self):
        h = PieceHistory()
        board = chess.Board("8/P7/8/8/8/8/8/K6k w - - 0 1")
        h.observe(board.fen(), "a7a8q")
        arrival = h.arrival_of(chess.A8)
        assert arrival is not None and arrival.piece_name == "queen"


class TestWarningMemory:
    def test_a_warning_travels_with_the_piece(self):
        h = PieceHistory()
        board = _play(h, ["e4", "e5", "Bc4", "Nc6"])
        h.record_warning(board.fen(), chess.C4, motif="undefended piece")
        # The bishop is warned about on c4, then moves. The record has to follow it, or
        # moving a piece launders its history and every turn looks like the first.
        _play(PieceHistory(), [])
        board2 = board.copy()
        h.observe(board2.fen(), board2.parse_san("Be2").uci())
        assert h.warnings_for(chess.E2) == [3]
        assert h.warnings_for(chess.C4) == []

    def test_recurrence_counts_the_piece_type_not_the_square(self):
        h = PieceHistory()
        board = _play(h, ["e4", "e5", "Bc4", "Nc6"])
        h.record_warning(board.fen(), chess.C4, motif="undefended piece")
        h.observe(board.fen(), board.parse_san("Be2").uci())
        board.push_san("Be2")
        board.push_san("Nf6")
        h.record_warning(board.fen(), chess.E2, motif="undefended piece")
        # This is the Stream Behaviour finding: "the light-squared bishop that gets
        # harassed on c4 over and over ... never named as patterns". A pattern that only
        # counts on one square cannot see it.
        assert h.recurrence_of(chess.BISHOP, "undefended piece") == 2
        assert h.recurrence_of(chess.KNIGHT, "undefended piece") == 0

    def test_an_unmotivated_warning_still_records_the_move_number(self):
        h = PieceHistory()
        board = _play(h, ["e4"])
        h.record_warning(board.fen(), chess.E4)
        assert h.warnings_for(chess.E4) == [1]
        assert h.recurrence_of(chess.PAWN, "") == 0


class TestRobustness:
    def test_a_malformed_fen_is_ignored_rather_than_raised(self):
        h = PieceHistory()
        h.observe("not a fen", "e2e4")
        h.record_warning("not a fen", chess.E4, motif="x")
        assert h.arrival_of(chess.E4) is None
        assert h.warnings_for(chess.E4) == []

    def test_an_illegal_or_unparseable_move_is_ignored(self):
        h = PieceHistory()
        h.observe(START, "e2e5")  # not legal
        h.observe(START, "wat")  # not a move
        assert h.arrival_of(chess.E5) is None

    def test_clear_forgets_the_game(self):
        h = PieceHistory()
        board = _play(h, ["e4", "e5", "Nf3"])
        h.record_warning(board.fen(), chess.F3, motif="undefended piece")
        h.clear()
        assert h.arrival_of(chess.F3) is None
        assert h.warnings_for(chess.F3) == []
        assert h.recurrence_of(chess.KNIGHT, "undefended piece") == 0


class TestHistoryReachesThePrompt:
    """The record is worth nothing if it stops short of the prompt.

    That was the actual defect. The reviewer: "Every one of those is in the game record
    and none of it reaches the prompt." These tests walk the whole path — play a game,
    let the piece sit, then check the built prompt carries the provenance and binds the
    model to it.
    """

    @staticmethod
    def _report(fen: str, user_move: str, refutation: list[str], best: str):
        from chess_coach.models import ComparisonReport

        return ComparisonReport(
            fen=fen,
            user_move=user_move,
            user_eval_cp=-300,
            best_move=best,
            best_eval_cp=0,
            eval_drop_cp=300,
            classification="blunder",
            nag="??",
            best_move_idea="",
            refutation_line=refutation,
            missed_tactics=[],
            top_lines=[],
            critical_moment=False,
            critical_reason=None,
        )

    def test_the_prompt_says_how_long_the_piece_had_been_there(self):
        from chess_coach.prompts import build_rich_move_evaluation_prompt

        h = PieceHistory()
        # The reviewer's own example: a knight walks to g5 early and is taken later.
        # 1.e4 h6 2.Nf3 a6 3.Ng5 — the knight arrives on move 3, then sits.
        board = _play(h, ["e4", "h6", "Nf3", "a6", "Ng5", "b6"])
        # The student now plays something irrelevant and ...hxg5 takes the knight.
        h.observe(board.fen(), board.parse_san("d4").uci())
        report = self._report(board.fen(), board.parse_san("d4").uci(), ["hxg5"], board.parse_san("Nf3").uci())
        prompt = build_rich_move_evaluation_prompt(report, history=h)

        assert "--- How this came about ---" in prompt
        # This is the sentence Diagnosis was missing: cause, not just consequence.
        assert "knight has been on g5 since move 3" in prompt
        assert "HOW IT CAME ABOUT" in prompt
        # And the model is fenced in, exactly as it is for the reason clause.
        assert "do not say the piece had no escape" in prompt

    def test_a_piece_that_just_moved_there_gets_no_history_line(self):
        from chess_coach.prompts import build_rich_move_evaluation_prompt

        h = PieceHistory()
        board = _play(h, ["e4", "h6", "Nf3", "a6"])
        # The knight moves to g5 and is taken immediately. "Has been on g5 since move 3"
        # would just restate the move under discussion, so nothing is claimed.
        move = board.parse_san("Ng5").uci()
        h.observe(board.fen(), move)
        report = self._report(board.fen(), move, ["hxg5"], board.parse_san("d4").uci())
        prompt = build_rich_move_evaluation_prompt(report, history=h)
        assert "How this came about" not in prompt
        assert "HOW IT CAME ABOUT" not in prompt

    def test_a_prior_warning_about_the_same_piece_is_named(self):
        from chess_coach.prompts import build_rich_move_evaluation_prompt

        h = PieceHistory()
        # Play up to the knight landing on g5 (move 3), and let the coach speak about it
        # there — that is where the move number in the warning comes from.
        board = _play(h, ["e4", "h6", "Nf3", "a6", "Ng5"])
        h.record_warning(board.fen(), chess.G5, motif="undefended piece")
        board.push_san("b6")
        h.observe(board.fen(), board.parse_san("d4").uci())
        report = self._report(board.fen(), board.parse_san("d4").uci(), ["hxg5"], board.parse_san("Nf3").uci())
        prompt = build_rich_move_evaluation_prompt(report, history=h)
        # Naming the repeat is what Stream Behaviour was docked for not doing.
        assert "already came up on move 3" in prompt

    def test_no_history_line_when_the_refutation_takes_nothing(self):
        from chess_coach.prompts import build_rich_move_evaluation_prompt

        h = PieceHistory()
        board = _play(h, ["e4", "h6", "Nf3", "a6", "Ng5", "b6"])
        h.observe(board.fen(), board.parse_san("d4").uci())
        # A quiet reply. There is no doomed piece, so there is no story to tell.
        report = self._report(board.fen(), board.parse_san("d4").uci(), ["c6"], board.parse_san("Nf3").uci())
        prompt = build_rich_move_evaluation_prompt(report, history=h)
        assert "How this came about" not in prompt

    def test_the_coach_wires_the_history_through_and_resets_it(self):
        # The Coach owns the instance and must clear it between games, on the same
        # footing as the lesson ladder.
        from chess_coach.coach import Coach

        coach = Coach.__new__(Coach)
        coach._piece_history = PieceHistory()
        _play(coach._piece_history, ["e4", "e5", "Nf3"])
        assert coach._piece_history.arrival_of(chess.F3) is not None
        coach._piece_history.clear()
        assert coach._piece_history.arrival_of(chess.F3) is None
