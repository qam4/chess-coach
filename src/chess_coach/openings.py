"""Opening book lookup using the Lichess chess-openings dataset.

Provides instant opening identification by matching board positions (EPD)
against a database of 3600+ named openings from the Encyclopedia of Chess
Openings (ECO).

Data source: https://github.com/lichess-org/chess-openings (CC0 public domain)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import chess

_DATA_FILE = Path(__file__).parent / "data" / "openings.json"

# Lazy-loaded lookup table: EPD -> opening info
_LOOKUP: dict[str, dict[str, str]] | None = None


@dataclass(frozen=True)
class OpeningInfo:
    """Information about a recognized chess opening."""

    eco: str  # e.g. "C50"
    name: str  # e.g. "Italian Game"
    pgn: str  # e.g. "1. e4 e5 2. Nf3 Nc6 3. Bc4"


def _load() -> dict[str, dict[str, str]]:
    """Load the openings database (lazy, cached)."""
    global _LOOKUP
    if _LOOKUP is None:
        with open(_DATA_FILE) as f:
            _LOOKUP = json.load(f)
    return _LOOKUP


def _epd_from_fen(fen: str) -> str:
    """Extract EPD (first 4 FEN fields) from a full FEN string."""
    return " ".join(fen.split()[:4])


def lookup_fen(fen: str) -> OpeningInfo | None:
    """Look up an opening by FEN position.

    Returns the opening info if the position matches a known opening,
    or None if the position is not in the database.
    """
    db = _load()
    epd = _epd_from_fen(fen)
    entry = db.get(epd)
    if entry is None:
        return None
    return OpeningInfo(eco=entry["eco"], name=entry["name"], pgn=entry["pgn"])


def lookup_moves(moves: list[str]) -> OpeningInfo | None:
    """Look up the most specific opening matching a sequence of UCI moves.

    Replays the moves on a board and checks each resulting position
    against the database, returning the last (most specific) match.
    """
    db = _load()
    board = chess.Board()
    best: OpeningInfo | None = None

    for uci_str in moves:
        try:
            move = chess.Move.from_uci(uci_str)
            if move not in board.legal_moves:
                break
            board.push(move)
        except ValueError:
            break

        epd = _epd_from_fen(board.fen())
        entry = db.get(epd)
        if entry is not None:
            best = OpeningInfo(eco=entry["eco"], name=entry["name"], pgn=entry["pgn"])

    return best


def is_book_move(fen_before: str, user_move_uci: str) -> bool:
    """Check whether a move leads to a known opening position.

    If the position after the move is in the ECO opening database,
    the move is a recognized book move and should not be penalized
    by the coach regardless of the engine's eval at shallow depth.
    """
    try:
        board = chess.Board(fen_before)
        board.push(chess.Move.from_uci(user_move_uci))
        return lookup_fen(board.fen()) is not None
    except (ValueError, chess.InvalidMoveError):
        return False
