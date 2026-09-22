"""A cause must describe something the opponent can act on.

`stopped_defending` diffs DEFENDER sets, so before this it fired on any piece that merely lost a
defender. Measured over 85 stored runs, 48 of 252 such causes named a square the opponent could
not attack at all; on the five v54 games, NONE of the 16 named a square that was actually attacked
after the move. Those turns pass every fidelity check because the claim is true, which is exactly
why no other instrument here could see them.

Positions are taken from real transcripts and asserted valid before use, per the standing rule that
four test FENs in one session named a piece that was not there.
"""

from __future__ import annotations

import chess

from chess_coach.error_diagnosis import KIND_STOPPED_DEFENDING, diagnose


def _kinds(fen: str, played: str, best: str = "") -> list[str]:
    board = chess.Board(fen)
    assert board.is_valid(), fen
    played_uci = board.parse_san(played).uci()
    best_uci = board.parse_san(best).uci() if best else ""
    return [d.kind for d in diagnose(fen, played_uci, best_uci)]


def test_no_cause_when_the_opponent_cannot_reach_the_square() -> None:
    """v54 seed 23 ply 13. Kd1 stops defending f2, and Black can never attack f2.

    The shipped coaching read "Moving your king to d1 left your pawn on f2 undefended, which you
    had previously protected." True, and useless: verified with python-chess that no black piece
    attacks f2 after Kd1, and none can attack it after any single legal black move.
    """
    fen = "1rb1k1nr/1ppp1ppp/p1n1p3/6B1/2QPP3/2N5/PP3PPP/R3KBNR w KQk - 0 9"
    board = chess.Board(fen)
    assert board.is_valid()
    after = board.copy(stack=False)
    after.push(board.parse_san("Kd1"))
    f2 = chess.F2
    assert after.piece_at(f2) is not None, "the pawn under discussion must actually be on f2"
    assert not after.attackers(chess.BLACK, f2), "f2 is not attacked, which is the whole point"

    assert KIND_STOPPED_DEFENDING not in _kinds(fen, "Kd1", "d5")


def test_no_cause_on_the_move_that_delivers_checkmate() -> None:
    """v54 seed 23 ply 71. Rhd1# is mate, and the coach discussed an undefended pawn on h2."""
    fen = "8/3k2p1/8/p6p/4Q3/4K3/PP4PP/2R4R w - - 4 38"
    board = chess.Board(fen)
    assert board.is_valid()
    after = board.copy(stack=False)
    after.push(board.parse_san("Rhd1#"))
    assert after.is_checkmate(), "position must really be mate for this test to mean anything"

    assert KIND_STOPPED_DEFENDING not in _kinds(fen, "Rhd1#", "Rhd1#")


def test_the_cause_still_fires_when_the_square_is_contested() -> None:
    """The negative control. Without this, silencing the detector entirely would pass.

    White rook on d4 defends d7; the black rook on d8 attacks d7 already. Moving the rook off the
    d-file stops defending d7 while Black plainly attacks it, so the cause is real and must survive.
    """
    fen = "3r2k1/3R4/8/8/3R4/8/6PP/6K1 w - - 0 1"
    board = chess.Board(fen)
    assert board.is_valid()
    assert board.piece_at(chess.D7) is not None
    assert board.attackers(chess.BLACK, chess.D7), "black must already attack d7"

    assert KIND_STOPPED_DEFENDING in _kinds(fen, "Ra4")


def test_the_cause_fires_when_the_square_becomes_reachable_in_one_move() -> None:
    """Generous by design: a piece the opponent is one tempo from hitting still earns a warning.

    A stricter "attacked right now" test would drop those, and being early is not the same as
    being irrelevant.

    v54 seed 23 ply 29, which is the instance the architecture review cited as a defect and which
    is NOT one: after Qc5 nothing attacks a2, but Nb4 puts an attacker on it next move. Verified
    below rather than asserted, after a first version of this test invented a position whose
    bishop already attacked a2.
    """
    fen = "r1bk3r/1p4p1/2n1p2n/p3pp1p/2QPP3/3B4/PP3PPP/1R1K2NR w - - 0 17"
    board = chess.Board(fen)
    assert board.is_valid()
    after = board.copy(stack=False)
    after.push(board.parse_san("Qc5"))
    assert after.piece_at(chess.A2) is not None
    assert not after.attackers(chess.BLACK, chess.A2), "a2 must not be attacked yet"
    reachable = any(_pushes_attacker(after, mv, chess.A2, chess.BLACK) for mv in after.legal_moves)
    assert reachable, "black must be able to attack a2 in one move (Nb4)"

    assert KIND_STOPPED_DEFENDING in _kinds(fen, "Qc5", "Nf3")


def _pushes_attacker(board: chess.Board, move: chess.Move, square: int, by: chess.Color) -> bool:
    nxt = board.copy(stack=False)
    nxt.push(move)
    return bool(nxt.attackers(by, square))
