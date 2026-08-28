"""Tests for the process-failure and topic-selection halves of Diagnosis.

Diagnosis is 25 of the 95 rubric weight and read 5 in every run measured: v33, v35, v36,
v38, v39. The reviewer gave two reasons and they need different fixes.

    "On the blunders it names the right board feature and the correct refutation
    (anchor 6), but never the thinking failure ... It drops to anchor 4 on the small
    inaccuracies, where a full-length message goes to a secondary feature — king
    repositioning at 26 (34cp) and an isolated a2 pawn at 42 — while the game was
    actually being decided by pieces left en prise."

The anchor for 8 is "names the specific process failure (e.g. 'that rook was doing a job
and you moved it anyway')". So the sentence has to be about the student's thinking, and
the turn has to be about the right thing.
"""

from __future__ import annotations

import chess

from chess_coach.diagnosis import missed_check


class TestMissedCheck:
    def test_moving_onto_a_square_the_opponent_already_covers(self):
        # The commonest 1200 mistake, and the cheapest to teach: the answer was on the
        # board before the move was played, so no calculation was needed to avoid it.
        # 1.e4 h6 2.Nf3 a6 3.Ng5 walks onto a square the h6 pawn covers.
        board = chess.Board()
        for san in ["e4", "h6", "Nf3", "a6"]:
            board.push_san(san)
        out = missed_check(board.fen(), board.parse_san("Ng5").uci(), "hxg5")
        assert out is not None and out.kind == "moved_onto_attacked_square"
        assert "already attacking g5 before you moved there" in out.sentence
        # Phrased as the habit, not the board fact. That is the whole point.
        assert "what of theirs attacks the square I am going to?" in out.sentence

    def test_moving_the_only_defender_of_another_piece(self):
        # The reviewer's own example of an anchor-8 sentence: "that rook was doing a job
        # and you moved it anyway". White's rook on e1 is the only guard of the knight on
        # e4; moving the rook away loses it.
        fen = "4k3/8/8/8/4N3/8/8/4RK2 w - - 0 1"
        board = chess.Board(fen)
        assert board.piece_at(chess.E4) is not None  # the knight the rook is holding
        out = missed_check(fen, board.parse_san("Ra1").uci(), "Ke7")
        # Ke7 takes nothing, so there is no material consequence and nothing is claimed.
        assert out is None
        # With a black rook that can actually take on e4, the diagnosis appears.
        fen2 = "4k3/8/8/8/4N2r/8/8/4RK2 w - - 0 1"
        board2 = chess.Board(fen2)
        out2 = missed_check(fen2, board2.parse_san("Ra1").uci(), "Rxe4")
        assert out2 is not None and out2.kind == "abandoned_defender"
        assert "only piece guarding e4" in out2.sentence
        assert "is the piece I am moving holding something in place?" in out2.sentence

    def test_ignoring_something_that_was_already_hanging(self):
        # A failure of priority, not of sight: the bishop on a6 is attacked and undefended
        # before the move, and the move improves something else instead.
        fen = "4k3/8/b7/8/8/8/6P1/4K1NR w K - 0 1"
        fen = "4k3/8/n7/8/8/8/6P1/R3K1N1 w Q - 0 1"
        board = chess.Board(fen)
        # White's rook on a1 attacks the undefended knight on a6; instead White plays g3.
        assert board.attackers(chess.WHITE, chess.A6)
        # Flip it around: give BLACK the standing threat against a white piece.
        fen3 = "4k1r1/8/8/8/8/8/6N1/4K3 w - - 0 1"
        board3 = chess.Board(fen3)
        assert board3.attackers(chess.BLACK, chess.G2)  # rook on g8 hits the knight
        assert not board3.attackers(chess.WHITE, chess.G2)  # and nothing defends it
        out = missed_check(fen3, board3.parse_san("Kd1").uci(), "Rxg2")
        assert out is not None and out.kind == "ignored_standing_threat"
        assert "already attacked and undefended before this move" in out.sentence
        assert "is anything of mine already under attack" in out.sentence

    def test_a_square_nothing_attacked_until_the_move_opened_it(self):
        # The move itself lets the capture in: the rook on a4 is what blocks the a-file,
        # so a2 is safe until the rook steps down to it and unblocks the line behind
        # itself. Nothing was visible beforehand, so the only check that would have caught
        # it is looking one move ahead — and the sentence says that rather than pretending
        # the danger was on the board already.
        fen = "r5k1/8/8/8/R7/8/8/6K1 w - - 0 1"
        board = chess.Board(fen)
        assert not board.attackers(chess.BLACK, chess.A2)  # blocked by our own rook
        out = missed_check(fen, "a4a2", "Rxa2")
        assert out is not None and out.kind == "no_look_ahead"
        assert "Nothing was attacking a2 until you moved there" in out.sentence
        assert "what does my opponent get to play?" in out.sentence

    def test_nothing_is_claimed_when_the_refutation_takes_nothing(self):
        # No material consequence, no missed check to infer. Guessing at one here is how
        # the invented reasons of v36 happened.
        board = chess.Board()
        out = missed_check(board.fen(), board.parse_san("e4").uci(), "e5")
        assert out is None

    def test_bad_input_is_ignored_rather_than_raised(self):
        board = chess.Board()
        assert missed_check("not a fen", "e2e4", "e5") is None
        assert missed_check(board.fen(), "wat", "e5") is None
        assert missed_check(board.fen(), "e2e5", "e5") is None  # illegal
        assert missed_check(board.fen(), board.parse_san("e4").uci(), "") is None
        assert missed_check(board.fen(), board.parse_san("e4").uci(), "zz9") is None


class TestTopicSelection:
    """The engine's hanging pieces must reach the move prompt and set the subject.

    This is the half that needed no new chess logic, only the facts being present. On the
    v39 transcript, ZERO of the 18 turns the coach spoke on were told what was hanging or
    threatened — they got piece placement, pawn structure and engine lines. So the coach
    wrote about pawn structure, and the reviewer marked it down for exactly that.
    """

    @staticmethod
    def _position(fen: str, hanging: dict[str, list[tuple[str, str]]]):
        """Minimal valid PositionReport carrying the hanging pieces under test."""
        from chess_coach.models import EvalBreakdown, HangingPiece, KingSafety, PawnFeatures, PositionReport

        empty_pawns = PawnFeatures([], [], [])
        return PositionReport(
            fen=fen,
            eval_cp=0,
            eval_breakdown=EvalBreakdown(material=0, mobility=0, king_safety=0, pawn_structure=0),
            hanging_pieces={
                side: [HangingPiece(square=sq, piece=pc, color=side) for sq, pc in items]
                for side, items in hanging.items()
            },
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

    def _report(self, fen: str, user_move: str, best: str):
        from chess_coach.models import ComparisonReport

        return ComparisonReport(
            fen=fen,
            user_move=user_move,
            user_eval_cp=-40,
            best_move=best,
            best_eval_cp=0,
            eval_drop_cp=40,
            classification="inaccuracy",
            nag="?!",
            best_move_idea="",
            refutation_line=None,
            missed_tactics=[],
            top_lines=[],
            critical_moment=False,
            critical_reason=None,
        )

    def test_the_data_describes_the_position_after_the_move(self):
        """The v40 gate-firing bug: right facts, wrong position.

        The list came from the position the student moved IN, and the coaching describes
        the position the move PRODUCES. On 4 of 13 turns the student had moved the very
        piece we announced as undefended, and the reviewer read one back: "the student
        plays c5 and is told it 'leaves your undefended pawn on c4 vulnerable' — the pawn
        just left c4". The engine is now asked about the right board, so the two cannot
        drift apart again.
        """
        from chess_coach.prompts import build_rich_move_evaluation_prompt

        # White's knight sits on g2 BEFORE the move and moves away to f4. A before-move
        # list would still name g2; the after-move list names nothing of ours.
        fen = "4k3/8/8/8/8/8/6N1/4K3 w - - 0 1"
        after = self._position("4k3/8/8/8/5N2/8/8/4K3 b - - 1 1", {"white": [], "black": []})
        prompt = build_rich_move_evaluation_prompt(self._report(fen, "g2f4", "e1e2"), position_after=after)
        assert "WHAT MATTERS HERE" not in prompt
        assert "g2" not in prompt.split("--- Board")[0]

    def test_our_hanging_piece_becomes_the_subject_of_the_turn(self):
        from chess_coach.prompts import build_rich_move_evaluation_prompt

        fen = "4k3/8/8/8/8/8/6N1/4K3 w - - 0 1"
        pos = self._position(fen, {"white": [("g2", "knight")], "black": []})
        prompt = build_rich_move_evaluation_prompt(self._report(fen, "e1d1", "g2f4"), position_after=pos)
        assert "WHAT MATTERS HERE" in prompt
        # Stated ONCE. v41 scored Load Discipline 4 for inventory-dumping and the reviewer
        # put the cure in one phrase: the coach "can hit anchor 8 when the fact budget is
        # one". The cause sentence already names the piece, so the standalone undefended
        # line stands down rather than saying it a second time.
        assert prompt.count("your knight on g2 is undefended") == 1
        assert "--- Undefended AFTER your move ---" not in prompt
        # Steered off the features that were previously all it had ...
        assert "not pawn structure, king repositioning or piece placement" in prompt
        # ... and forbidden from inventing a rescue. v40: "Ke2 addresses the immediate
        # threat to your pawn on g2", which a king on e2 does not touch. Naming the problem
        # and stopping is the honest option when we have not supplied the fix.
        assert "Do NOT claim that any move defends it" in prompt
        # The same fact also becomes the missed check, which needs no refutation line.
        assert "is anything of mine left where it can simply be taken?" in prompt

    def test_the_opponents_hanging_pieces_do_not_set_our_subject(self):
        from chess_coach.prompts import build_rich_move_evaluation_prompt

        fen = "4k3/8/8/8/8/8/6n1/4K3 w - - 0 1"
        pos = self._position(fen, {"white": [], "black": [("g2", "knight")]})
        prompt = build_rich_move_evaluation_prompt(self._report(fen, "e1d1", "e1f2"), position_after=pos)
        # Dropped entirely, not merely unframed. On a turn spent diagnosing the student's
        # own move the opponent's loose pieces are a different lesson, and merging the two
        # lists is what produced v41 ply 34: "your pawn on g5 is undefended, and the knight
        # on e3 is also undefended" — where the second piece is BLACK's and the sentence
        # never says so. The reviewer read it as a mislabelled piece; the engine had it
        # right and the coach had dropped the ownership.
        assert "Undefended AFTER your move" not in prompt
        assert "WHAT MATTERS HERE" not in prompt
        # It may still be named as the REASON the recommended move is good ("Kf2 attacks
        # their undefended knight on g2") — that is a different clause with its own
        # provenance, and it is about the opportunity rather than the student's problem.

    def test_no_position_report_means_no_new_sections(self):
        from chess_coach.prompts import build_rich_move_evaluation_prompt

        fen = "4k3/8/8/8/8/8/6N1/4K3 w - - 0 1"
        prompt = build_rich_move_evaluation_prompt(self._report(fen, "e1d1", "g2f4"))
        assert "Undefended AFTER your move" not in prompt
        assert "WHAT MATTERS HERE" not in prompt

    def test_several_hanging_pieces_are_all_named(self):
        from chess_coach.prompts import build_rich_move_evaluation_prompt

        fen = "4k3/8/8/8/8/1b6/6N1/4K3 w - - 0 1"
        pos = self._position(fen, {"white": [("g2", "knight"), ("b3", "bishop")], "black": []})
        prompt = build_rich_move_evaluation_prompt(self._report(fen, "e1d1", "g2f4"), position_after=pos)
        assert "your knight on g2 and your bishop on b3 are undefended" in prompt
