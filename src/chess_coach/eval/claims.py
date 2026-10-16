"""B-021: the board claims a coaching draft makes, written down by a reader, checked by python-chess.

Every count of false statements in the ledger came from `verify.py`, which decides what a sentence
claims by matching its words. That checker cannot grade its own replacement, so this is the
measure that does. A reader — the frontier judge, or the agent — reads each draft and writes every
board claim it makes in the fixed form `build_claims_prompt` describes. This module parses that
JSON reply and asks python-chess whether each claim holds. It never reads the draft's prose: the
owner's rule is that the Python we write does not parse model output with regexes, phrase lists or
keyword matches, and parsing a JSON reply we asked a model for is not parsing prose.

A draft is FALSE if any claim the reader wrote down is false on the board. A claim the board cannot
be asked (an illegal line, an unknown kind, a square with nothing on it where a piece is needed) is
None: the reader's error, not the coach's, so it never makes a draft false.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import chess

from .judge import VerdictParseError, _extract_json_object

#: Draft verdicts.
FALSE = "false"
CLEAN = "clean"
UNRESOLVED = "unresolved"  # no false claim, but at least one the board could not be asked
MISSING = "missing"  # the reader returned nothing for this draft

_PIECES = {
    "pawn": chess.PAWN,
    "knight": chess.KNIGHT,
    "bishop": chess.BISHOP,
    "rook": chess.ROOK,
    "queen": chess.QUEEN,
    "king": chess.KING,
}
_COLOURS = {"white": chess.WHITE, "black": chess.BLACK}


class ClaimsParseError(VerdictParseError):
    """The reader's reply is not the JSON object the prompt asked for."""


# --------------------------------------------------------------- the board half


def _square(claim: dict[str, Any], key: str) -> chess.Square:
    return chess.parse_square(str(claim[key]).strip().lower())


def _legal_move(board: chess.Board, claim: dict[str, Any]) -> chess.Move | None:
    """The claimed move if it is legal here, None if it is not. Unparseable SAN raises."""
    try:
        return board.parse_san(str(claim["move"]).strip())
    except chess.IllegalMoveError:
        return None


def _piece(board: chess.Board, claim: dict[str, Any]) -> bool:
    found = board.piece_at(_square(claim, "square"))
    if found is None or found.piece_type != _PIECES[str(claim["piece"]).lower()]:
        return False
    colour = claim.get("color")
    return colour is None or found.color == _COLOURS[str(colour).lower()]


def _empty(board: chess.Board, claim: dict[str, Any]) -> bool:
    return board.piece_at(_square(claim, "square")) is None


def _legal(board: chess.Board, claim: dict[str, Any]) -> bool:
    return _legal_move(board, claim) is not None


def _capture(board: chess.Board, claim: dict[str, Any]) -> bool:
    move = _legal_move(board, claim)
    if move is None or not board.is_capture(move):
        return False
    wanted = claim.get("piece")
    if not wanted:
        return True
    taken = chess.PAWN if board.is_en_passant(move) else board.piece_type_at(move.to_square)
    return taken == _PIECES[str(wanted).lower()]


def _check(board: chess.Board, claim: dict[str, Any]) -> bool:
    move = _legal_move(board, claim)
    return move is not None and board.gives_check(move)


def _mate(board: chess.Board, claim: dict[str, Any]) -> bool:
    move = _legal_move(board, claim)
    if move is None:
        return False
    after = board.copy(stack=False)
    after.push(move)
    return after.is_checkmate()


def _attacks(board: chess.Board, claim: dict[str, Any]) -> bool:
    origin = _square(claim, "square")
    target = _square(claim, "target")
    if board.piece_at(origin) is None:
        return False
    return target in board.attacks(origin)


def _attacked(board: chess.Board, claim: dict[str, Any]) -> bool:
    return bool(board.attackers(_COLOURS[str(claim["by"]).lower()], _square(claim, "square")))


def _defended(board: chess.Board, claim: dict[str, Any]) -> bool | None:
    square = _square(claim, "square")
    found = board.piece_at(square)
    if found is None:
        return None
    return bool(board.attackers(found.color, square))


_SLIDERS = frozenset({chess.BISHOP, chess.ROOK, chess.QUEEN})


def _pinned(board: chess.Board, claim: dict[str, Any]) -> bool | None:
    """Pinned to its king, or to another piece of its side standing behind it on the line.

    The second half matters: coaches say "pin" for Qc5 against Nc6 with a bishop on c8, and the
    first version, asking only for a pin to the king, called that false. Whether the piece behind
    is worth more is a judgement of value, and that is the engine's question, not this one.
    """
    square = _square(claim, "square")
    found = board.piece_at(square)
    if found is None:
        return None
    if board.is_pinned(found.color, square):
        return True
    for attacker in board.attackers(not found.color, square):
        if board.piece_type_at(attacker) not in _SLIDERS:
            continue
        beyond = [
            x
            for x in chess.SquareSet(chess.ray(attacker, square))
            if square in chess.SquareSet(chess.between(attacker, x)) and board.piece_at(x) is not None
        ]
        if beyond:
            behind = board.piece_at(min(beyond, key=lambda x: chess.square_distance(square, x)))
            if behind is not None and behind.color == found.color:
                return True
    return False


def _pawn(board: chess.Board, claim: dict[str, Any]) -> tuple[chess.Square, chess.Piece] | None:
    square = _square(claim, "square")
    found = board.piece_at(square)
    if found is None or found.piece_type != chess.PAWN:
        return None
    return square, found


def _passed(board: chess.Board, claim: dict[str, Any]) -> bool | None:
    pawn = _pawn(board, claim)
    if pawn is None:
        return None
    square, found = pawn
    file, rank = chess.square_file(square), chess.square_rank(square)
    for other in board.pieces(chess.PAWN, not found.color):
        if abs(chess.square_file(other) - file) > 1:
            continue
        other_rank = chess.square_rank(other)
        if (found.color == chess.WHITE and other_rank > rank) or (found.color == chess.BLACK and other_rank < rank):
            return False
    return True


def _isolated(board: chess.Board, claim: dict[str, Any]) -> bool | None:
    pawn = _pawn(board, claim)
    if pawn is None:
        return None
    square, found = pawn
    file = chess.square_file(square)
    return not any(abs(chess.square_file(other) - file) == 1 for other in board.pieces(chess.PAWN, found.color))


#: Each kind: the fields it needs, what it asserts (both shown to the reader), and its board test.
KINDS: dict[str, tuple[str, Callable[[chess.Board, dict[str, Any]], bool | None]]] = {
    "piece": ("square, piece, color — that piece of that colour stands on the square", _piece),
    "empty": ("square — nothing stands on the square", _empty),
    "legal": ("move — the side to move can play the move", _legal),
    "capture": ("move, and optionally piece — the move captures (a piece of that type)", _capture),
    "check": ("move — the move gives check", _check),
    "mate": ("move — the move is checkmate", _mate),
    "attacks": ("square, target — the piece standing on square attacks the target square", _attacks),
    "attacked": ("square, by — some piece of colour `by` attacks the square", _attacked),
    "defended": ("square — some piece of the same colour as the one on the square defends it", _defended),
    "pinned": ("square — the piece on the square is pinned, to its king or to a piece of its side behind it", _pinned),
    "passed": ("square — the pawn on the square is a passed pawn", _passed),
    "isolated": ("square — the pawn on the square has no friendly pawn on a neighbouring file", _isolated),
}


def evaluate(fen_before: str, claim: dict[str, Any]) -> bool | None:
    """Does ``claim`` hold on the board? None when the board cannot be asked.

    The position is ``fen_before`` with the claim's ``after`` moves played in order, so a claim can
    be about the position before the student's move, after it, or after a reply the text names.
    """
    try:
        board = chess.Board(fen_before)
        for san in claim.get("after") or []:
            board.push_san(str(san).strip())
        entry = KINDS.get(str(claim.get("kind")))
        if entry is None:
            return None
        holds = entry[1](board, claim)
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    if holds is None:
        return None
    return holds != bool(claim.get("negated", False))


def draft_verdict(results: list[bool | None]) -> str:
    if any(r is False for r in results):
        return FALSE
    if any(r is None for r in results):
        return UNRESOLVED
    return CLEAN


# --------------------------------------------------------------- the drafts


@dataclass(frozen=True)
class Draft:
    id: str  # "<seed>:<ply>:<index of the distinct draft within the turn>"
    ply: int
    fen_before: str
    student_move_san: str
    text: str


def drafts_of(transcript: dict[str, Any], *, seed: int) -> list[Draft]:
    """Every distinct draft in a report-card transcript, in order.

    A retry that repeated the blocked draft word for word is one draft to read, not two: at
    temperature 0 that was 8 of the 9 retries at v62.
    """
    out: list[Draft] = []
    for turn in transcript["turns"]:
        seen: list[str] = []
        for text in turn.get("drafts") or []:
            if text in seen:
                continue
            seen.append(text)
            out.append(
                Draft(
                    id=f"{seed}:{turn['ply']}:{len(seen) - 1}",
                    ply=int(turn["ply"]),
                    fen_before=str(turn["fen_before"]),
                    student_move_san=str(turn["student_move_san"]),
                    text=text,
                )
            )
    return out


# --------------------------------------------------------------- the reader's half


_ASK = """You are reading a chess coach's feedback to a student. For each draft below, write down every
claim it makes about the board, in the fixed form described here. A program then checks each claim
on the board. Your job is ONLY to write down what the text claims. Do not check whether it is true,
and do not leave a claim out because you think it is false or obvious.

A claim is a JSON object:
  {"sentence": "<the sentence it comes from, copied exactly>",
   "after": [<moves in SAN, played in order from the position BEFORE the student's move>],
   "kind": "<one of the kinds below>",
   <the fields that kind needs>,
   "negated": <true if the text says this does NOT hold, otherwise false>}

"after" sets the position the claim is about:
  []                                  before the student's move ("was already attacked before this move")
  ["<student's move>"]                after it; most claims are about this position
  ["<student's move>", "<reply>"]     after a reply the text names

Kinds. Squares like "c3"; colours "white" or "black"; pieces pawn, knight, bishop, rook, queen,
king; moves in SAN, legal for the side to move in the claim's position.
{kinds}

How to write them:
- One claim per fact. "The opponent replies Qc2, capturing your bishop on c1" is two claims: legal
  Qc2 after ["<student's move>"], and capture Qc2 with piece bishop after ["<student's move>"].
  "... Qc2, attacking your bishop on c1" is legal Qc2, then attacks square c2 target c1 after
  ["<student's move>", "Qc2"].
- "Your move left the pawn on c3 undefended" is a defended claim on c3, negated, after the move.
- "you"/"your" is the student's colour; "they"/"their"/"the opponent" is the other colour. A piece
  named with its square ("your pawn on c3") is also a piece claim.
- A claim can be implied. Calling a move "a check" that "buys time to develop" says the game goes
  on, so it is also a mate claim on that move, negated.
- Advice, questions, lessons and general principles are not claims. A sentence that does state a
  fact about this board that none of the kinds can express goes in "unchecked", copied exactly.

Reply with ONE JSON object and nothing else, with one entry for every draft, in order:
  {"drafts": [{"id": "<id>", "claims": [<claim>, ...], "unchecked": ["<sentence>", ...]}, ...]}
"""


def build_claims_prompt(drafts: list[Draft]) -> str:
    kinds = "\n".join(f"- {name}: {what}" for name, (what, _test) in KINDS.items())
    blocks = []
    for d in drafts:
        board = chess.Board(d.fen_before)
        side = "White" if board.turn == chess.WHITE else "Black"
        after = board.copy(stack=False)
        try:
            after.push_san(d.student_move_san)
            fen_after = after.fen()
        except ValueError:
            fen_after = "(the student's move does not parse in this position)"
        blocks.append(
            f"### Draft {d.id}\n"
            f"Student plays {side}. Student's move: {d.student_move_san}\n"
            f"Position before the move (FEN): {d.fen_before}\n"
            f"Position after the move (FEN): {fen_after}\n"
            f"Board before the move (White's pieces in capitals, White at the bottom):\n{board}\n"
            f"Text:\n<<<\n{d.text}\n>>>\n"
        )
    return _ASK.replace("{kinds}", kinds) + "\n" + "\n".join(blocks)


@dataclass
class ReadDraft:
    claims: list[dict[str, Any]] = field(default_factory=list)
    unchecked: list[str] = field(default_factory=list)


def parse_claims_reply(reply: str) -> dict[str, ReadDraft]:
    """The reader's reply, by draft id. Raises ClaimsParseError when it is not the asked-for shape."""
    try:
        data = json.loads(_extract_json_object(reply), strict=False)
    except (VerdictParseError, json.JSONDecodeError) as e:
        raise ClaimsParseError(f"claims reply is not a JSON object: {e}") from e
    entries = data.get("drafts") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ClaimsParseError("claims reply has no 'drafts' list")
    out: dict[str, ReadDraft] = {}
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("id") is None:
            continue
        found = entry.get("claims") or []
        loose = entry.get("unchecked") or []
        out[str(entry["id"])] = ReadDraft(
            claims=[c for c in found if isinstance(c, dict)] if isinstance(found, list) else [],
            unchecked=[str(s) for s in loose] if isinstance(loose, list) else [],
        )
    return out


def score_reading(drafts: list[Draft], reading: dict[str, ReadDraft]) -> dict[str, dict[str, Any]]:
    """Each draft's claims with whether they hold, and the draft's verdict, by draft id."""
    out: dict[str, dict[str, Any]] = {}
    for d in drafts:
        base = {"ply": d.ply, "fen_before": d.fen_before, "student_move_san": d.student_move_san, "text": d.text}
        read = reading.get(d.id)
        if read is None:
            out[d.id] = {**base, "claims": [], "unchecked": [], "verdict": MISSING}
            continue
        claims = [{**c, "holds": evaluate(d.fen_before, c)} for c in read.claims]
        out[d.id] = {
            **base,
            "claims": claims,
            "unchecked": list(read.unchecked),
            "verdict": draft_verdict([c["holds"] for c in claims]),
        }
    return out


def disagreements(a: dict[str, str], b: dict[str, str]) -> tuple[int, list[str]]:
    """How many drafts both readers read, and the ids one calls false and the other does not."""
    both = sorted(i for i in a if i in b and a[i] != MISSING and b[i] != MISSING)
    return len(both), [i for i in both if (a[i] == FALSE) != (b[i] == FALSE)]
