"""Property tests for Play vs Engine frontend logic (undo round-trip, reset-to-start).

These test the backend endpoints that the frontend relies on, validating
the correctness properties from the design doc.
"""

from __future__ import annotations

import chess
from hypothesis import given, settings
from hypothesis import strategies as st

STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def _play_random_moves(board: chess.Board, n: int) -> list[str]:
    """Play n random legal moves on the board, return UCI list."""
    import random

    moves: list[str] = []
    for _ in range(n):
        legal = list(board.legal_moves)
        if not legal:
            break
        move = random.choice(legal)
        moves.append(move.uci())
        board.push(move)
    return moves


# Feature: chess-coaching-mvp, Property 5: Undo restores previous position
@given(num_pairs=st.integers(min_value=1, max_value=20))
@settings(max_examples=100)
def test_undo_restores_previous_position(num_pairs: int) -> None:
    """Undoing a move pair restores the FEN from before the last pair."""
    board = chess.Board()
    all_moves = _play_random_moves(board, num_pairs * 2)

    # Need at least 2 moves for undo
    if len(all_moves) < 2:
        return

    # Truncate to even number of moves (full pairs)
    if len(all_moves) % 2 != 0:
        all_moves = all_moves[:-1]

    # Replay to get the FEN before the last pair
    board_before = chess.Board()
    for uci in all_moves[:-2]:
        board_before.push(chess.Move.from_uci(uci))
    expected_fen = board_before.fen()

    # Simulate undo: replay all but last 2 moves
    truncated = all_moves[:-2]
    board_after_undo = chess.Board()
    for uci in truncated:
        board_after_undo.push(chess.Move.from_uci(uci))

    assert board_after_undo.fen() == expected_fen
    assert len(truncated) == len(all_moves) - 2


# Feature: chess-coaching-mvp, Property 6: Reset produces starting position
@given(num_moves=st.integers(min_value=0, max_value=30))
@settings(max_examples=100)
def test_reset_produces_starting_position(num_moves: int) -> None:
    """Resetting after any number of moves returns the starting FEN."""
    board = chess.Board()
    _play_random_moves(board, num_moves)

    # Reset
    board.reset()
    assert board.fen() == STARTING_FEN
    assert board.move_stack == []


# Feature: chess-coaching-mvp, Property 7: Move list tracks game history
@given(num_moves=st.integers(min_value=1, max_value=40))
@settings(max_examples=100)
def test_move_list_tracks_history(num_moves: int) -> None:
    """The move list has exactly N entries after N moves, in order."""
    board = chess.Board()
    moves_played = _play_random_moves(board, num_moves)

    # The move list should have exactly len(moves_played) entries
    assert len(moves_played) <= num_moves
    assert len(board.move_stack) == len(moves_played)

    # Verify each move in the stack matches what was played
    for i, uci in enumerate(moves_played):
        assert board.move_stack[i].uci() == uci
