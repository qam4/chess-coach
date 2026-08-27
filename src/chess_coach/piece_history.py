"""Per-game provenance for the student's pieces: where each one came from.

Why this exists. Through v38 the coach was handed one position and the engine's
refutation of one move, and the reviewer's verdict on Diagnosis never moved off 5 in
four runs for a reason it stated plainly:

    "The blocker is that the coach sees one ply and the engine's refutation, so it can
    only ever report the consequence. The knight that dies at ply 20 walked to g5 at
    ply 6 ... the bishop that dies at ply 34 had been shuffled c4->e2->c4 with the
    student already told at ply 14 that it needed a defender. Every one of those is in
    the game record and none of it reaches the prompt."

A process failure is a statement about a sequence. We were asking the model to name one
while supplying a single position, which is the same mistake as asking it for a reason
we had not derived: it obliged, and invented. So this module keeps the record instead.

It is deliberately BOOKKEEPING, not analysis. Everything here is a fact about what
happened in the game: which move put a piece on its square, how long it has stood
there, how often it has been the subject of coaching. Nothing in it evaluates a
position, counts material or judges a move — that division of labour is the engine's
(docs/coaching-protocol.md), and inventing chess logic on this side is what
``engine_trust`` exists to prevent.

The map is reconciled against the FEN on every observation rather than tracking the
opponent's moves. We are handed ``fen_before`` for each of the student's turns and
nothing in between, so anything that happened while we were not looking — a capture,
a promotion — shows up as a square that no longer holds one of the student's pieces.
Reconciling is therefore both simpler and more robust than replaying.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import chess

__all__ = ["Arrival", "PieceHistory"]


@dataclass(frozen=True)
class Arrival:
    """When and how a piece reached the square it now occupies.

    ``move_number`` is the full move number as a player counts it ("move 6"), not a
    ply, because it is written for the student.
    """

    move_number: int
    san: str
    piece_type: int

    @property
    def piece_name(self) -> str:
        return chess.piece_name(self.piece_type)


@dataclass
class PieceHistory:
    """The student's pieces, tracked across one game.

    Two questions it answers, both of which the reviewer asked for by name:

    * *where did this piece come from* — :meth:`arrival_of`, so a turn can say "that
      knight has been on g5 since move 6" instead of only "the opponent takes it".
    * *have we been here before* — :meth:`warnings_for` and :meth:`recurrence_of`, so
      a repeat can be named as a repeat. This is also what Stream Behaviour was
      docked for in v38: the student's bishop was harassed on four separate turns and
      the king stepped into an attack on three, and no turn called either a pattern.

    One instance per game, held by :class:`~chess_coach.coach.Coach` and cleared by
    ``new_game()`` alongside the lesson ladder.
    """

    #: Square -> how the piece standing there arrived. Absent means it has not moved
    #: this game, which is itself a fact worth stating ("still on its starting square").
    _arrived: dict[chess.Square, Arrival] = field(default_factory=dict)
    #: Square -> the move numbers on which the coach spoke about the piece there. Travels
    #: with the piece, so moving it does not launder its history.
    _warned: dict[chess.Square, list[int]] = field(default_factory=dict)
    #: (piece type, motif) -> times the coach has raised that pairing this game. Keyed on
    #: TYPE rather than square: the point of a pattern is that it recurs somewhere else.
    _motifs: dict[tuple[int, str], int] = field(default_factory=dict)

    def clear(self) -> None:
        """Forget the game. Called from ``Coach.new_game()``."""
        self._arrived.clear()
        self._warned.clear()
        self._motifs.clear()

    # ----- recording -----

    def observe(self, fen_before: str, user_move_uci: str) -> None:
        """Record one move by the student, from the position it was played in.

        Safe to call with a move the position rejects: an unparseable or illegal move
        leaves the map reconciled but otherwise untouched. The caller is a coaching
        pipeline, not a rules engine, and a bad move here must not raise into it.
        """
        board = _safe_board(fen_before)
        if board is None:
            return
        self._reconcile(board)
        try:
            move = chess.Move.from_uci(user_move_uci)
        except ValueError:
            return
        if move not in board.legal_moves:
            return
        piece = board.piece_at(move.from_square)
        if piece is None:
            return
        san = board.san(move)
        number = board.fullmove_number

        # The destination's previous occupant is gone, and so is its history. Dropping
        # this first matters: without it a capture would inherit the victim's record and
        # report the wrong provenance.
        self._arrived.pop(move.to_square, None)
        self._warned.pop(move.to_square, None)

        self._arrived.pop(move.from_square, None)
        carried = self._warned.pop(move.from_square, [])
        landing = move.promotion or piece.piece_type
        self._arrived[move.to_square] = Arrival(move_number=number, san=san, piece_type=landing)
        if carried:
            self._warned[move.to_square] = carried

        # Castling moves two pieces. The rook's provenance has to follow it or the
        # king's history silently becomes the rook's.
        if board.is_castling(move):
            back = chess.square_rank(move.from_square)
            if chess.square_file(move.to_square) > chess.square_file(move.from_square):
                rook_from, rook_to = chess.square(7, back), chess.square(5, back)
            else:
                rook_from, rook_to = chess.square(0, back), chess.square(3, back)
            self._arrived.pop(rook_from, None)
            rook_warnings = self._warned.pop(rook_from, [])
            self._arrived[rook_to] = Arrival(move_number=number, san=san, piece_type=chess.ROOK)
            if rook_warnings:
                self._warned[rook_to] = rook_warnings

    def record_warning(self, fen: str, square: chess.Square, motif: str = "") -> None:
        """Note that the coach has just spoken about the piece on ``square``.

        ``motif`` is the label the turn used ("undefended piece"). It is counted per
        piece TYPE, because a pattern the student needs to see is one that recurs on a
        different square — the harassed bishop moves and gets harassed again.
        """
        board = _safe_board(fen)
        if board is None:
            return
        self._warned.setdefault(square, []).append(board.fullmove_number)
        piece = board.piece_at(square)
        if piece is not None and motif:
            key = (piece.piece_type, motif)
            self._motifs[key] = self._motifs.get(key, 0) + 1

    # ----- reading -----

    def arrival_of(self, square: chess.Square) -> Arrival | None:
        """How the piece on ``square`` got there, or ``None`` if it has never moved."""
        return self._arrived.get(square)

    def warnings_for(self, square: chess.Square) -> list[int]:
        """Move numbers on which the coach already spoke about the piece on ``square``."""
        return list(self._warned.get(square, ()))

    def recurrence_of(self, piece_type: int, motif: str) -> int:
        """How many times this piece type has been raised with this motif already."""
        return self._motifs.get((piece_type, motif), 0)

    # ----- internals -----

    def _reconcile(self, board: chess.Board) -> None:
        """Drop entries for squares that no longer hold one of the student's pieces.

        The student is ``board.turn``: we are called with the position they are about to
        move in. Anything captured or vacated while we were not looking disappears here.
        """
        for square in list(self._arrived):
            piece = board.piece_at(square)
            if piece is None or piece.color != board.turn:
                del self._arrived[square]
        for square in list(self._warned):
            piece = board.piece_at(square)
            if piece is None or piece.color != board.turn:
                del self._warned[square]


def _safe_board(fen: str) -> chess.Board | None:
    """A board from ``fen``, or ``None`` if it will not parse.

    Mirrors the same helper in the prompt and template modules: a malformed FEN must
    degrade the coaching, never raise into the pipeline.
    """
    try:
        return chess.Board(fen)
    except ValueError:
        return None
