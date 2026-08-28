"""What the student failed to CHECK, and what actually mattered on the turn.

Diagnosis is worth 25 of the 95 rubric weight and has read 5 in every run measured —
v33, v35, v36, v38, v39. The reviewer gave two reasons for that 5 and they need
different fixes:

    "On the blunders it names the right board feature and the correct refutation
    (anchor 6), but never the thinking failure ... It drops to anchor 4 on the small
    inaccuracies, where a full-length message goes to a secondary feature — king
    repositioning at 26 (34cp) and an isolated a2 pawn at 42 — while the game was
    actually being decided by pieces left en prise."

The anchor for 8 is "names the specific process failure (e.g. 'that rook was doing a
job and you moved it anyway')". So the sentence has to be about the student's
THINKING, not about the board. v39 tried to reach it with piece provenance — "your
knight has been on g5 since move 4" — and the reviewer rejected the whole idea in one
line: "a piece-history fact, not a cause". It was right. Where a piece has been is not
what the student got wrong.

:func:`missed_check` answers the first half. The second half turned out not to need new
code at all: the engine already reports hanging pieces and threats, and the
move-evaluation prompt simply never included them. Measured on v39, not one of the 18
coached turns was told what was under attack — it got piece placement, pawn structure
and engine lines, and was asked to explain a blunder from that. Which is why it wrote
about pawn structure. An earlier draft of this module computed "attacked and undefended"
here instead; it was deleted, because on the v39 game it found only loose pawns and
missed the knight that actually died on g5 (defended once, but attacked by a pawn).
Telling those apart needs piece values, and piece values are the engine's to hold
(ledger row 60: our own material counter was removed for exactly this reason).

On the division of labour. Everything here is a RULES question — which squares does a
piece attack, who defends this square — answered by python-chess, the same rules engine
:mod:`chess_coach.verify` already uses to catch the model's false claims. None of it
evaluates a position, scores a move or compares two moves; that is the engine's work
and stays there (docs/coaching-protocol.md). If board geometry is trustworthy enough to
falsify what the coach says, it is trustworthy enough to tell the coach what to say.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

__all__ = ["MissedCheck", "missed_check"]


@dataclass(frozen=True)
class MissedCheck:
    """A process failure: the question the student did not ask before moving.

    ``kind`` is for measurement and tests. ``sentence`` is what the coach is given, and
    it is deliberately phrased as the skipped CHECK rather than the board fact — "the
    square you moved to was already attacked" describes the board; "before you move,
    ask what attacks the square you are going to" is the habit that would have caught
    it, which is what the rubric is asking for.
    """

    kind: str
    sentence: str


def _safe_board(fen: str) -> chess.Board | None:
    try:
        return chess.Board(fen)
    except ValueError:
        return None


def _parse_reply(board: chess.Board, token: str) -> chess.Move | None:
    """The opponent's reply, from SAN or UCI, or ``None`` if it is neither."""
    try:
        return board.parse_san(token)
    except (chess.InvalidMoveError, chess.IllegalMoveError, chess.AmbiguousMoveError, ValueError):
        pass
    try:
        move = chess.Move.from_uci(token)
    except ValueError:
        return None
    return move if move in board.legal_moves else None


def missed_check(fen: str, user_move_uci: str, refutation_first: str) -> MissedCheck | None:
    """The check the student skipped, given how the opponent refutes their move.

    Four shapes, tried in the order that makes the most instructive one win. Each is
    decided entirely by which squares attack which — nothing here weighs a position.

    Returns ``None`` when the refutation takes nothing of ours, because then there is no
    material consequence to trace back to a missed check and guessing at one is how the
    invented reasons of v36 happened.
    """
    board = _safe_board(fen)
    if board is None or not refutation_first:
        return None
    try:
        move = chess.Move.from_uci(user_move_uci)
    except ValueError:
        return None
    if move not in board.legal_moves:
        return None
    mover = board.piece_at(move.from_square)
    if mover is None:
        return None
    us = board.turn
    after = board.copy(stack=False)
    after.push(move)
    reply = _parse_reply(after, refutation_first)
    if reply is None:
        return None
    victim = after.piece_at(reply.to_square)
    if victim is None or victim.color != us:
        return None
    victim_name = chess.piece_name(victim.piece_type)
    victim_square = chess.square_name(reply.to_square)
    moved_name = chess.piece_name(mover.piece_type)
    landed = chess.square_name(move.to_square)

    # 1. The piece that just moved is the one that gets taken, onto a square the
    #    opponent was ALREADY covering. The most common 1200 mistake and the cheapest
    #    check to teach, because the answer was on the board before the move.
    if reply.to_square == move.to_square and board.attackers(not us, move.to_square):
        return MissedCheck(
            "moved_onto_attacked_square",
            f"The opponent was already attacking {landed} before you moved there. "
            f"The check that was skipped: before I move, what of theirs attacks the square I am going to?",
        )

    # 2. The moved piece was the only thing guarding the square where a different piece
    #    now dies. This is the reviewer's own example of an anchor-8 sentence: "that rook
    #    was doing a job and you moved it anyway".
    if reply.to_square != move.to_square:
        defended_before = move.from_square in board.attackers(us, reply.to_square)
        defended_after = bool(after.attackers(us, reply.to_square))
        if defended_before and not defended_after:
            return MissedCheck(
                "abandoned_defender",
                f"Your {moved_name} was the only piece guarding {victim_square}. Moving it left the "
                f"{victim_name} there undefended. The check that was skipped: is the piece I am moving "
                f"holding something in place?",
            )

    # 3. The victim was already attacked and already undefended before the move, and the
    #    move addressed something else. A failure of priority rather than of sight.
    if reply.to_square != move.to_square:
        was_attacked = bool(board.attackers(not us, reply.to_square))
        was_undefended = not board.attackers(us, reply.to_square)
        if was_attacked and was_undefended:
            return MissedCheck(
                "ignored_standing_threat",
                f"Your {victim_name} on {victim_square} was already attacked and undefended before this "
                f"move, and the move went elsewhere. The check that was skipped: is anything of mine "
                f"already under attack, before I look for something to improve?",
            )

    # 4. The piece that moved gets taken on a square nothing attacked beforehand, so the
    #    move itself opened the way. Phrased as looking one move ahead, which is the only
    #    check that would have caught it.
    if reply.to_square == move.to_square:
        return MissedCheck(
            "no_look_ahead",
            f"Nothing was attacking {landed} until you moved there; the move is what allows it. "
            f"The check that was skipped: after my move, what does my opponent get to play?",
        )
    return None
