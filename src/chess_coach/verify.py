"""Rules-tier verifier: drop engine-supplied threats that aren't legal moves.

The engine's coaching protocol can emit *pseudo-legal* threats — moves that
ignore pins or the fact that the side to move is in check (observed live: a
pinned knight "capturing" the checking queen, and a pawn "capturing" while its
king is in check). chess-coach already holds the FEN and ``python-chess``, an
independent implementation of the rules of chess, so it can validate each
threat's move against the legal moves of the owning side and silently discard
the impossible ones before they reach the LLM or the quick-mode templates.

This checks *rules* truth only (legality), which ``python-chess`` knows
independently of any engine — so using it to check the engine is not circular.
It does **not** check *evaluation* truth (whether a move is actually best or a
position is really winning); the engine remains the sole oracle for that.

Scope: only :class:`~chess_coach.models.Threat` entries are filtered, and only
when a concrete move can be identified for them (an explicit ``uci_move`` or a
``via <uci>`` token in the description). Relational facts with no move (a pin or
skewer description) carry no UCI token and are kept. Tactics
(:class:`~chess_coach.models.TacticalMotif`) are left untouched — they carry no
single move to validate, and "in-PV" motifs describe the principal variation
rather than the current position.
"""

from __future__ import annotations

import dataclasses
import re

import chess

from chess_coach.models import PositionReport, Threat

_SIDE_COLOR = {"white": chess.WHITE, "black": chess.BLACK}

# A UCI move token: from-square, to-square, optional promotion piece.
_UCI_RE = re.compile(r"\b([a-h][1-8][a-h][1-8][qrbnQRBN]?)\b")
# Prefer the move named after "via" (the engine's own "... via c3e4" convention).
_VIA_RE = re.compile(r"via\s+([a-h][1-8][a-h][1-8][qrbnQRBN]?)\b", re.IGNORECASE)


def _candidate_move(threat: Threat) -> str | None:
    """Return the UCI move a threat asserts, or None if it asserts no move.

    Priority: the structured ``uci_move`` field, then a ``via <uci>`` token in
    the description, then any UCI-looking token. Relational descriptions (pins,
    skewers) contain no such token and yield None.
    """
    if threat.uci_move:
        return threat.uci_move
    via = _VIA_RE.search(threat.description)
    if via:
        return via.group(1)
    token = _UCI_RE.search(threat.description)
    if token:
        return token.group(1)
    return None


def _is_legal_for(board: chess.Board, uci_move: str, color: chess.Color) -> bool:
    """True if *uci_move* is a legal move for *color* in *board*.

    For the side to move this is a direct legality check, so pins and the
    in-check constraint are respected. For the opponent we simulate their turn
    on a copy so a "what they threaten next" move can still be validated.
    """
    try:
        move = chess.Move.from_uci(uci_move)
    except (ValueError, chess.InvalidMoveError):
        return False
    probe = board
    if board.turn != color:
        probe = board.copy(stack=False)
        probe.turn = color
    return move in probe.legal_moves


def filter_illegal_threats(report: PositionReport) -> PositionReport:
    """Return *report* with rule-illegal threats removed.

    A threat is dropped only when a concrete move can be identified for it
    (see :func:`_candidate_move`) and that move is **not** legal for the side
    that owns it. Threats with no identifiable move are kept — we remove only
    what we can prove illegal. Returns the same object unchanged when nothing
    is dropped (or the FEN can't be parsed).
    """
    try:
        board = chess.Board(report.fen)
    except ValueError:
        return report

    new_threats: dict[str, list[Threat]] = {}
    changed = False
    for side, threats in report.threats.items():
        color = _SIDE_COLOR.get(side)
        kept: list[Threat] = []
        for threat in threats:
            move = _candidate_move(threat) if color is not None else None
            if move is not None and not _is_legal_for(board, move, color):  # type: ignore[arg-type]
                changed = True
                continue
            kept.append(threat)
        new_threats[side] = kept

    if not changed:
        return report
    return dataclasses.replace(report, threats=new_threats)
