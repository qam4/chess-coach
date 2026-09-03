"""What the student's move failed to do, computed by diffing attack maps.

This is the spine the pipeline never had. Everything the coach composes today is derived
from the ENGINE's preferred move — the achievement clause, the guidance selection, the
closing takeaway. So the system's primary object is "what is good about a3", which is
analysis. A teacher's primary object is "what did the student fail to do, and what habit
would have caught it". Those are different computations over different data, and until now
we only ever computed the first.

That one fact accounts for the two rubric dimensions that never moved across nine measured
runs. Diagnosis sat at 5 because we never computed a diagnosis. Transfer Handle sat at 5
because the takeaway was derived from the best move's virtue and therefore inherited the
best move's stability — the engine wanted a3 on four separate plies for the same true
reason, so the coach taught the same lesson four times, and the anti-repetition ladders were
treating a symptom of the key being wrong.

It has been recorded twice in BACKLOG.md as "give the composer the student's failure cause as
a first-class field" and never built. A partial version exists — ``diagnosis.missed_check`` —
gated on the engine supplying a refutation line, which reached 3 of 18 coached turns. The
reviewer's assessment of that was exact: "the right idea bolted on at 3/18 coverage instead
of made the spine."

How it works, and why it is safe. Push the student's move; push the engine's move; diff
``board.attackers()`` per square for both colours. Everything emitted is a geometric fact
about those two positions — no evaluation, no piece values, no claim about why the game was
lost. That keeps it inside the rules layer ``verify.py`` already polices, so it is
accuracy-safe by construction, and it keeps the judgement of what a position is WORTH with
the engine where it belongs.

Coverage is the point of the design: almost any move changes an attack map, so unlike the
refutation-gated version this can speak on most turns. Measured before wiring, per the rule
adopted after two changes shipped at coverage too low to register.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

__all__ = ["ErrorDiagnosis", "STRONG_KINDS", "diagnose"]

#: Diagnosis classes, ordered by how instructive they are to a 1200. The order matters:
#: where a move exhibits several, the first is the subject of the turn.
KIND_LEFT_UNDEFENDED = "left_undefended"
KIND_MOVED_ONLY_DEFENDER = "moved_only_defender"
KIND_MISSED_CAPTURE = "missed_capture"
KIND_STOPPED_DEFENDING = "stopped_defending"
KIND_OPENED_LINE = "opened_line_into"

#: The habit that would have caught each class. This is the Transfer Handle half: a cue
#: paired with a check the student can run in seconds, keyed to the ERROR rather than to the
#: virtue of the engine's move — which is why it varies where the best move does not.
_CHECKS: dict[str, str] = {
    KIND_LEFT_UNDEFENDED: "before I commit, is the piece I am moving attacked on the square I am moving it to?",
    KIND_MOVED_ONLY_DEFENDER: "before I move a piece, is it the only thing guarding something?",
    KIND_MISSED_CAPTURE: "before anything else, is there something of theirs I can just take?",
    KIND_STOPPED_DEFENDING: "after my move, is everything I was defending still defended?",
    KIND_OPENED_LINE: "does my move open a line for one of their pieces?",
}


@dataclass(frozen=True)
class ErrorDiagnosis:
    """One thing the student's move failed to do, as a checkable geometric fact.

    ``fact`` is what the coach may say — stated so a student can verify it on the board.
    ``missed_check`` is the habit that would have caught it. Deliberately no severity and no
    causal claim: "the knight on g5 has no defender and the f6 pawn attacks it" is ours to
    assert, "this is why you lost" is not.
    """

    kind: str
    square: str
    piece: str
    fact: str

    @property
    def missed_check(self) -> str:
        return _CHECKS.get(self.kind, "")


def _safe_board(fen: str) -> chess.Board | None:
    try:
        return chess.Board(fen)
    except ValueError:
        return None


def _loose(board: chess.Board, colour: chess.Color, square: chess.Square) -> bool:
    """Is ``colour``'s piece on ``square`` attacked and undefended? Pure geometry."""
    piece = board.piece_at(square)
    if piece is None or piece.color != colour or piece.piece_type == chess.KING:
        return False
    return bool(board.attackers(not colour, square)) and not board.attackers(colour, square)


def _defended_squares(board: chess.Board, colour: chess.Color) -> set[chess.Square]:
    """Squares holding ``colour``'s pieces that ``colour`` also defends."""
    return {
        sq
        for sq, pc in board.piece_map().items()
        if pc.color == colour and pc.piece_type != chess.KING and board.attackers(colour, sq)
    }


def diagnose(fen: str, user_move_uci: str, best_move_uci: str = "") -> list[ErrorDiagnosis]:
    """What the student's move failed to do, most instructive first; ``[]`` if nothing.

    ``best_move_uci`` is optional and only used for the differential classes — a capture is
    only "missed" if a better move takes it. Without it the self-contained classes still fire.
    """
    board = _safe_board(fen)
    if board is None:
        return []
    try:
        played = chess.Move.from_uci(user_move_uci)
    except ValueError:
        return []
    if played not in board.legal_moves:
        return []
    us = board.turn
    mover = board.piece_at(played.from_square)
    if mover is None:
        return []

    after = board.copy(stack=False)
    after.push(played)
    out: list[ErrorDiagnosis] = []

    # 1. The piece just moved is now attacked and undefended. The commonest 1200 mistake and
    #    the one whose check is cheapest to run.
    if _loose(after, us, played.to_square):
        attackers = sorted(chess.square_name(s) for s in after.attackers(not us, played.to_square))
        name = chess.piece_name(mover.piece_type)
        to_name = chess.square_name(played.to_square)
        out.append(
            ErrorDiagnosis(
                KIND_LEFT_UNDEFENDED,
                to_name,
                name,
                # Phrased WITHOUT "your <piece> on <square>". This class names the move's
                # DESTINATION, which is empty in the position the checker verifies against, so
                # "your pawn on c6" read as a present-tense placement claim and our own fidelity
                # gate flagged the fallback text — the one message with nothing behind it if it
                # fails. True as written, wrong shape. The other four classes name squares that
                # are already occupied, so only this one needed rewording.
                f"after {board.san(played)} nothing of yours defends {to_name}, and {'/'.join(attackers)} attacks it",
            )
        )

    # 2. The moved piece was the only guard of something, which is now loose. The reviewer's
    #    own example of a teaching sentence: "that rook was doing a job and you moved it".
    for square in sorted(board.piece_map()):
        if square == played.from_square:
            continue
        piece = board.piece_at(square)
        if piece is None or piece.color != us or piece.piece_type == chess.KING:
            continue
        guarded_before = played.from_square in board.attackers(us, square)
        if not guarded_before or not _loose(after, us, square):
            continue
        sq_name = chess.square_name(square)
        out.append(
            ErrorDiagnosis(
                KIND_MOVED_ONLY_DEFENDER,
                sq_name,
                chess.piece_name(piece.piece_type),
                f"your {chess.piece_name(mover.piece_type)} was the only piece guarding {sq_name}, "
                f"and after {board.san(played)} the {chess.piece_name(piece.piece_type)} there has no defender",
            )
        )

    # 3. Something of theirs was free to take and the engine's move takes it. Needs the
    #    engine's move, because "free" is only a missed opportunity if a better move took it.
    if best_move_uci and best_move_uci != user_move_uci:
        try:
            best = chess.Move.from_uci(best_move_uci)
        except ValueError:
            best = None
        if best is not None and best in board.legal_moves and board.is_capture(best):
            victim = board.piece_at(best.to_square)
            if victim is not None and _loose(board, not us, best.to_square):
                sq_name = chess.square_name(best.to_square)
                out.append(
                    ErrorDiagnosis(
                        KIND_MISSED_CAPTURE,
                        sq_name,
                        chess.piece_name(victim.piece_type),
                        f"their {chess.piece_name(victim.piece_type)} on {sq_name} was attacked and undefended "
                        f"before your move, and {board.san(played)} does not take it",
                    )
                )

    # 4. The move stopped defending something that stays on the board. Weaker than 2 (the
    #    piece is not necessarily loose now) so it ranks below.
    lost_defence = _defended_squares(board, us) - _defended_squares(after, us) - {played.from_square}
    for square in sorted(lost_defence):
        piece = after.piece_at(square)
        if piece is None or piece.color != us:
            continue
        sq_name = chess.square_name(square)
        out.append(
            ErrorDiagnosis(
                KIND_STOPPED_DEFENDING,
                sq_name,
                chess.piece_name(piece.piece_type),
                f"before {board.san(played)} your {chess.piece_name(piece.piece_type)} on {sq_name} "
                f"was defended; after it, it is not",
            )
        )

    # 5. The move vacated a square and opened a line: one of THEIR pieces now attacks one of
    #    ours that it could not reach before. Attributed to the vacated square, which is what
    #    makes it a fact about the move rather than about the position.
    newly_hit: list[chess.Square] = []
    for square, piece in after.piece_map().items():
        if piece.color != us or piece.piece_type == chess.KING or square == played.to_square:
            continue
        if after.attackers(not us, square) and not board.attackers(not us, square):
            newly_hit.append(square)
    for square in sorted(newly_hit):
        piece = after.piece_at(square)
        if piece is None:
            continue
        sq_name = chess.square_name(square)
        out.append(
            ErrorDiagnosis(
                KIND_OPENED_LINE,
                sq_name,
                chess.piece_name(piece.piece_type),
                f"moving off {chess.square_name(played.from_square)} lets them attack your "
                f"{chess.piece_name(piece.piece_type)} on {sq_name}, which was not attacked before",
            )
        )

    order = {
        KIND_LEFT_UNDEFENDED: 0,
        KIND_MOVED_ONLY_DEFENDER: 1,
        KIND_MISSED_CAPTURE: 2,
        KIND_STOPPED_DEFENDING: 3,
        KIND_OPENED_LINE: 4,
    }
    out.sort(key=lambda d: (order.get(d.kind, 9), d.square))
    return out


#: The classes strong enough to become the SUBJECT of a turn and to own its takeaway.
#:
#: The two omitted ones are true but weak. "You stopped defending something" does not mean the
#: piece is now loose, and "your move opened a line" may be irrelevant if nothing comes of it.
#: Letting them own the takeaway measurably cost real teaching: on an endgame position with a
#: rook and a passed pawn, `stopped_defending` displaced "put your rook behind your passed
#: pawn" with "is everything I was defending still defended?" — a generic check beating a
#: phase-specific technique, which is the opposite of what this whole change is for.
#:
#: They still get computed and can still be stated as facts; they just do not outrank a
#: composed lesson.
STRONG_KINDS = frozenset({KIND_LEFT_UNDEFENDED, KIND_MOVED_ONLY_DEFENDER, KIND_MISSED_CAPTURE})
