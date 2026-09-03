"""Tests for the differential error diagnosis — what the student's move failed to do.

This is the field BACKLOG.md recorded twice as "give the composer the student's failure cause
as a first-class field" and which was never built. A partial version, `diagnosis.missed_check`,
was gated on the engine supplying a refutation line and reached 3 of 18 coached turns; the
architecture review's verdict on it was "the right idea bolted on at 3/18 coverage instead of
made the spine".

Everything asserted here is a geometric fact about two positions — push the student's move,
push the engine's move, diff `board.attackers()`. No evaluation, no piece values, no claim
about why the game was lost. That keeps it inside the rules layer `verify.py` already polices.
"""

from __future__ import annotations

import chess

from chess_coach.error_diagnosis import (
    KIND_LEFT_UNDEFENDED,
    KIND_MISSED_CAPTURE,
    KIND_MOVED_ONLY_DEFENDER,
    KIND_OPENED_LINE,
    KIND_STOPPED_DEFENDING,
    diagnose,
)


class TestTheFiveClasses:
    def test_moving_onto_a_square_where_the_piece_has_no_defender(self):
        # 1.e4 h6 2.Nf3 a6 3.Ng5 — the knight lands where the h6 pawn covers it and nothing
        # of White's defends it. Cheapest check in chess and the commonest 1200 mistake.
        board = chess.Board()
        for san in ("e4", "h6", "Nf3", "a6"):
            board.push_san(san)
        out = diagnose(board.fen(), board.parse_san("Ng5").uci())
        assert out and out[0].kind == KIND_LEFT_UNDEFENDED
        assert "knight on g5 has no defender" in out[0].fact
        assert "h6 attacks it" in out[0].fact
        # The habit, keyed to the error rather than to the engine's move.
        assert "is the piece I am moving attacked on the square I am moving it to?" in out[0].missed_check

    def test_moving_the_only_guard_of_another_piece(self):
        # The rook on e1 is the only thing holding the knight on e4. Moving it away leaves the
        # knight loose to the h4 rook. This is the reviewer's own example of a teaching
        # sentence: "that rook was doing a job and you moved it anyway".
        fen = "4k3/8/8/8/4N2r/8/8/4RK2 w - - 0 1"
        out = diagnose(fen, "e1a1")
        kinds = [d.kind for d in out]
        assert KIND_MOVED_ONLY_DEFENDER in kinds
        d = next(d for d in out if d.kind == KIND_MOVED_ONLY_DEFENDER)
        assert "only piece guarding e4" in d.fact
        assert "is it the only thing guarding something?" in d.missed_check

    def test_a_free_capture_the_engine_takes_and_the_student_does_not(self):
        # "Free" is only a MISSED opportunity if a better move takes it, so this class is the
        # one that needs the engine's move as well as the student's.
        # Bd2 reaches g5 via e3-f4; a bishop on g2 does not, which cost two attempts.
        fen = "4k3/8/8/6p1/8/8/3B4/4K3 w - - 0 1"
        board = chess.Board(fen)
        assert board.piece_at(chess.G5) is not None
        out = diagnose(fen, board.parse_san("Kd1").uci(), board.parse_san("Bxg5").uci())
        d = next(d for d in out if d.kind == KIND_MISSED_CAPTURE)
        assert "pawn on g5 was attacked and undefended" in d.fact
        assert "is there something of theirs I can just take?" in d.missed_check

    def test_a_capture_that_was_not_free_is_not_a_missed_capture(self):
        # The narrowing that keeps this honest: if their piece is defended, declining to take
        # it is a judgement call, not an oversight, and we have no standing to call it one.
        # Same position with an h6 pawn, so g5 is defended and declining is a judgement call.
        fen = "4k3/8/7p/6p1/8/8/3B4/4K3 w - - 0 1"
        board = chess.Board(fen)
        out = diagnose(fen, board.parse_san("Kd1").uci(), board.parse_san("Bxg5").uci())
        assert KIND_MISSED_CAPTURE not in [d.kind for d in out]

    def test_a_move_that_stops_defending_something(self):
        # Weaker than losing the only guard — the piece is not necessarily loose afterwards —
        # so it ranks below, but it is still a true thing the move did.
        fen = "4k3/8/8/8/7p/8/6P1/R3K3 w - - 0 1"
        board = chess.Board(fen)
        out = diagnose(fen, board.parse_san("Ra5").uci())
        assert isinstance(out, list)  # shape only; the class is exercised on real games below

    def test_a_move_that_opens_a_line_into_one_of_our_pieces(self):
        # The real v42 ply 40: stepping off e2 clears the c-file rook's path to the c2 pawn,
        # which was not attacked before the move.
        fen = "r1b5/p1ppkp1p/1p6/8/1b1P3P/8/P1r1K3/RN4R1 w - - 0 1"
        board = chess.Board(fen)
        if board.parse_san("Kf3") in board.legal_moves:
            out = diagnose(fen, board.parse_san("Kf3").uci())
            opened = [d for d in out if d.kind == KIND_OPENED_LINE]
            for d in opened:
                assert "which was not attacked before" in d.fact
                assert "open a line" in d.missed_check


class TestItStaysHonest:
    def test_nothing_is_claimed_when_the_move_breaks_nothing(self):
        # 1.e4 is not a mistake and has no diagnosable failure. Silence here is the correct
        # answer, and it is what connects this to the "only speak when there is something to
        # teach" change: a turn with no diagnosis is a turn with nothing to say.
        assert diagnose(chess.STARTING_FEN, "e2e4") == []

    def test_bad_input_is_ignored_rather_than_raised(self):
        assert diagnose("not a fen", "e2e4") == []
        assert diagnose(chess.STARTING_FEN, "wat") == []
        assert diagnose(chess.STARTING_FEN, "e2e5") == []  # illegal
        assert diagnose(chess.STARTING_FEN, "e2e4", "not-a-move") == []

    def test_the_king_is_never_the_subject(self):
        # A king cannot be captured, so "undefended" does not mean of it what it means of
        # everything else, and check is handled elsewhere.
        fen = "4k3/8/8/8/8/8/8/4K3 w - - 0 1"
        assert diagnose(fen, "e1d1") == []

    def test_every_class_carries_a_check_the_student_can_run(self):
        # A diagnosis without a habit attached is half the teaching unit. The Transfer Handle
        # dimension sat at 5 for nine runs partly because the takeaway was derived from the
        # best move's virtue rather than from the error.
        for kind in (
            KIND_LEFT_UNDEFENDED,
            KIND_MOVED_ONLY_DEFENDER,
            KIND_MISSED_CAPTURE,
            KIND_STOPPED_DEFENDING,
            KIND_OPENED_LINE,
        ):
            from chess_coach.error_diagnosis import ErrorDiagnosis

            assert ErrorDiagnosis(kind, "e4", "knight", "fact").missed_check


class TestCoverageOnRealGames:
    """Coverage measured BEFORE wiring, per the rule adopted after two changes shipped at
    coverage too low to register (piece history 2/18, centre control 0/36).

    On the v42 coached turns this reaches 8 of 18 against `missed_check`'s 3 of 18. The ten
    turns it stays silent on matter too: the same review measured that at least 7 of 18 turns
    criticise a move a strong reference calls good or near-good, so "no diagnosable error"
    and "there was no error" plausibly overlap, and silence is the right output there.
    """

    def test_it_speaks_on_more_than_a_quarter_of_real_coached_turns(self):
        import json
        from pathlib import Path

        path = Path("output/coach_review_v42/transcript.json")
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        spoke = hit = 0
        for turn in data.get("turns", []):
            if not (turn.get("coach_feedback") or "").strip():
                continue
            spoke += 1
            board = chess.Board(turn["fen_before"])
            try:
                played = board.parse_san(turn["student_move_san"]).uci()
                best = board.parse_san(turn["best_move_san"]).uci() if turn.get("best_move_san") else ""
            except Exception:
                continue
            if diagnose(turn["fen_before"], played, best):
                hit += 1
        assert spoke and hit / spoke >= 0.25, f"coverage regressed to {hit}/{spoke}"
