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
when the engine supplies a concrete move for them (the structured ``uci_move``
field). Move-bearing threats (check, capture) carry ``uci_move``; relational
facts with no move (fork, pin, skewer describing an existing board
relationship) carry none and are always kept. Tactics
(:class:`~chess_coach.models.TacticalMotif`) are left untouched — they carry no
single move to validate, and "in-PV" motifs describe the principal variation
rather than the current position.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable

import chess

from chess_coach.coaching_phrases import MenuMove, minor_is_developed
from chess_coach.models import PositionReport, Threat

_SIDE_COLOR = {"white": chess.WHITE, "black": chess.BLACK}


def _candidate_move(threat: Threat) -> str | None:
    """Return the UCI move a threat asserts, or None if it asserts no move.

    Read only from the structured ``uci_move`` field — never parsed from the
    engine's prose ``description``. Relational threats (pins, skewers, forks
    describing an existing relationship) carry no ``uci_move`` and yield None,
    so they are kept (there is nothing to prove illegal).
    """
    return threat.uci_move or None


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


# ---------------------------------------------------------------------------
# Output fidelity checker
# ---------------------------------------------------------------------------
#
# The threat filter above verifies the ENGINE's own facts before they reach
# the model. The checker below verifies the model's OUTPUT: it scans finished
# coaching text for concrete claims that contradict the board, the rules, or
# the engine-tagged move menu, and returns them as structured violations. It
# is deterministic (no engine call, no LLM), the safety net behind the prompt
# constraint, and an objective Layer-1 metric.
#
# Precision-first: it flags only high-confidence, pattern-matched
# contradictions. Recall is deliberately bounded — a claim it cannot parse
# with confidence is left alone rather than risk a false alarm that erodes
# trust. It is a floor on correctness, not a proof of it.

_PIECE_NAME_TO_TYPE = {
    "pawn": chess.PAWN,
    "knight": chess.KNIGHT,
    "bishop": chess.BISHOP,
    "rook": chess.ROOK,
    "queen": chess.QUEEN,
    "king": chess.KING,
}

# Well-formed SAN (piece move, capture, or castling). Mirrors the eval
# harness's move regex so the two share one notion of "looks like a move".
_SAN_RE = re.compile(r"\b([KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?|O-O(?:-O)?)\b")

# Coordinate move: "f6-e4", "f6 to e4", "f6–e4", "f6→e4". Unambiguously a move.
_COORD_RE = re.compile(r"\b([a-h][1-8])\s*(?:-|to|\u2013|\u2192)\s*([a-h][1-8])\b", re.IGNORECASE)

# "your/their <piece> on <square>" — a claim about WHOSE piece it is.
#
# Separate from the placement check because the two fail independently, and this
# one is invisible to it: at v27 ply 44 the coach warned about "an immediate threat
# to your own bishop on b4" when b4 held BLACK's bishop and the student was White.
# Placement passed — a bishop really is on b4 — so a false claim reached the
# student. The board settles ownership as cleanly as it settles occupancy.
#
# "my" and "our" are treated as the student's; "their/his/her/its" as the
# opponent's. "the" is excluded: it asserts no owner.
_OWNERSHIP_RE = re.compile(
    r"\b(your|our|my|their|his|her|its)\s+(?:own\s+)?(?:\w+\s+){0,2}?"
    r"(pawn|knight|bishop|rook|queen|king)\s+(?:on|at)\s+([a-h][1-8])\b",
    re.IGNORECASE,
)
_STUDENT_POSSESSIVES = frozenset({"your", "our", "my"})

# "piece on/at square" placement claim.
_PLACEMENT_RE = re.compile(
    r"\b(pawn|knight|bishop|rook|queen|king)\s+(?:on|at)\s+([a-h][1-8])\b",
    re.IGNORECASE,
)

# "<minor> on <square> [is] [still] (un)developed" and the reversed order.
_DEV_RE = re.compile(
    r"\b(knight|bishop)\s+on\s+([a-h][1-8])\s+(?:is\s+)?(?:still\s+)?(un)?developed\b",
    re.IGNORECASE,
)
_DEV_REV_RE = re.compile(
    r"\b(un)?developed\s+(knight|bishop)\s+on\s+([a-h][1-8])\b",
    re.IGNORECASE,
)

# "from <square>" — the source of a claimed move.
_FROM_RE = re.compile(r"\bfrom\s+([a-h][1-8])\b", re.IGNORECASE)

_INFLUENCE_VERBS = ("controlling", "targeting", "attacking", "defending")
_SQUARE_ASSESSMENT_RE = re.compile(r"(?:weak|strong)\s+square\s+([a-h][1-8])", re.IGNORECASE)

# Strong cues that, appearing shortly BEFORE a named move, mean the coach is
# warning against it rather than recommending it — which the prompt permits.
# Deliberately conservative (clear phrases only) to keep precision high; a
# warning phrased AFTER the move ("Nxe4 loses a piece") is not caught and is
# still counted (documented over-count).
_WARN_CUES = (
    "avoid",
    "don't play",
    "do not play",
    "never play",
    "instead of",
    "rather than",
    "beware",
    "watch out",
    "steer clear",
    "resist",
    "don't fall for",
    "tempted to play",
    "tempting to play",
)


def _warned_against(text: str, start: int) -> bool:
    """True if a warning cue appears in the ~40 chars before position ``start``.

    Used to suppress ``off_menu``/``unsound_move`` when the coach names a bad
    move only to warn against it (allowed by the prompt). Illegality is never
    suppressed — an illegal move is a factual error however it is framed.
    """
    window = text[max(0, start - 40) : start].lower()
    return any(cue in window for cue in _WARN_CUES)


# Verbs that mark a move as the OPPONENT's reply rather than a move the coach
# is telling the student to play.
_REPLY_VERBS = (
    "plays",
    "play",
    "can",
    "could",
    "will",
    "replies",
    "reply",
    "responds",
    "respond",
    "threatens",
    "threaten",
    "takes",
    "captures",
    "answers",
    "meets",
)


def _is_piece_reference(token: str, board: chess.Board) -> bool:
    """True if ``token`` names a piece standing on a square rather than a move.

    ``Be6`` is ambiguous notation: it is SAN for "bishop to e6", and it is also
    how a piece on a square is commonly written — including by OUR OWN composer,
    which emits "Re1 pins Be6 to Ke7". The coach echoes that and was flagged for
    an illegal move it never named.

    The board settles it. Plain SAN to an occupied square is impossible (a real
    move onto a piece is a capture, written with ``x``), so when a piece of the
    named type already stands on the named square the token can only be a
    reference. Precision-first: this gives up flagging a genuinely illegal
    ``Be6``, which is speculative, to stop a false positive we know we generate.
    """
    bare = token.rstrip("+#")
    if len(bare) < 3 or bare[0] not in "KQRBN" or "x" in bare:
        return False
    piece_type = {"K": chess.KING, "Q": chess.QUEEN, "R": chess.ROOK, "B": chess.BISHOP, "N": chess.KNIGHT}[bare[0]]
    try:
        square = chess.parse_square(bare[-2:])
    except ValueError:
        return False
    occupant = board.piece_at(square)
    return occupant is not None and occupant.piece_type == piece_type


def _attributed_to_opponent(text: str, start: int, board: chess.Board) -> bool:
    """True if the move at ``start`` is framed as the OPPONENT's reply.

    The fidelity checker validates named moves against the position as given —
    where it is the STUDENT to move — so a move the coach attributes to the
    opponent ("after your move, Black plays fxg5") is not a legal student move
    and would be a false ``illegal_move``. When such an attribution cue appears
    just before the move we skip it entirely: the coach is naming the engine's
    refutation reply (grounded), not recommending a move the student should
    play. Precision-first: recall is bounded (a fabricated opponent move is not
    caught here — the judge remains the backstop), but we stop punishing correct
    "the opponent plays X" coaching.
    """
    before = text[:start]
    # Standard notation first: "..." immediately before a move means it is the
    # reply, not a move to play ("threats like ...Nxg2"). Missing this produced a
    # false `illegal_move` on coaching that was factually correct — Nxg2 really
    # was a legal black knight capture there, and still legal after the
    # recommended king move. This is checked BEFORE the sentence scoping below,
    # because the ellipsis is itself made of full stops and would otherwise be
    # mistaken for a sentence boundary.
    if before.rstrip().endswith("..."):
        return True

    # Scope the cue search to the CURRENT SENTENCE rather than a fixed number of
    # characters. A 45-character window missed "your opponent immediately
    # captures your bishop on d4 with exd4" — the cue sits ~53 characters back —
    # and flagged a false `illegal_move` on correct coaching. Attribution applies
    # to the clause it appears in, so a sentence is the right unit; the cap stops
    # a run-on sentence from carrying a cue arbitrarily far.
    floor = max(0, start - 240)
    sentence_start = max(before.rfind(ch, floor) for ch in ".!?\n")
    window = before[max(sentence_start + 1, floor) :].lower()
    if "opponent" in window or "after your move" in window or "in reply" in window:
        return True
    opp = "black" if board.turn == chess.WHITE else "white"
    return any(f"{opp} {verb}" in window for verb in _REPLY_VERBS)


@dataclasses.dataclass(frozen=True)
class Violation:
    """One detected contradiction in coaching text.

    ``kind`` is one of ``illegal_move`` / ``unsound_move`` / ``off_menu`` /
    ``placement`` / ``ownership`` / ``development`` / ``empty_source`` /
    ``piece_type`` / ``pawn_structure`` / ``geometry``; ``text`` is the offending
    fragment; ``detail`` explains why it is wrong.
    """

    kind: str
    text: str
    detail: str


def _menu_by_uci(menu: list[MenuMove]) -> dict[str, MenuMove]:
    return {m.uci: m for m in menu}


def _find_legal(board: chess.Board, frm: str, to: str) -> chess.Move | None:
    """Return the legal move from ``frm`` to ``to`` (queening by default), else None."""
    try:
        src = chess.parse_square(frm)
        dst = chess.parse_square(to)
    except ValueError:
        return None
    for move in board.legal_moves:
        if move.from_square == src and move.to_square == dst:
            return move
    return None


def _classify_named_move(
    move: chess.Move,
    frag: str,
    by_uci: dict[str, MenuMove],
    warned: bool = False,
) -> Violation | None:
    """Judge a legal named move against the engine menu (the allowed set).

    The coach is instructed to recommend ONLY ``best``/``sound`` menu moves, so:
    - a listed move tagged ``dubious``/``blunder`` is an ``unsound_move``;
    - a legal move NOT in the menu is ``off_menu`` (we cannot prove it
      objectively unsound — that would need every legal move scored — but the
      coach was told not to recommend an unlisted move, so naming one violates
      the constraint);
    - a listed ``best``/``sound`` move is allowed (no violation).

    ``off_menu`` is only meaningful when a menu exists; the caller passes an
    empty ``by_uci`` when there is no menu and no move is flagged off-menu.
    When ``warned`` is True the coach is warning against the move (not
    recommending it), which the prompt allows — no violation.
    """
    if warned:
        return None
    hit = by_uci.get(move.uci())
    if hit is not None:
        if hit.tag in ("dubious", "blunder"):
            return Violation("unsound_move", frag, f"{hit.san} is tagged {hit.tag} ({hit.eval_cp:+d}cp)")
        return None  # best/sound — allowed
    if by_uci:  # menu present, but this move was not listed as best/sound
        return Violation("off_menu", frag, "not in the engine's best/sound candidate menu")
    return None


def _check_named_moves(
    text: str,
    board: chess.Board,
    by_uci: dict[str, MenuMove],
) -> list[Violation]:
    """Flag named moves that are illegal or that the coach may not recommend.

    Beyond illegality, this measures **constraint adherence**: the coach is
    told to name only ``best``/``sound`` menu moves, so a named move that is
    listed-but-dubious/blunder (``unsound_move``) or absent from the menu
    (``off_menu``) is a violation. This does NOT claim an off-menu move is
    objectively unsound — judging that would require scoring every legal move
    — only that recommending an unlisted move breaks the rule we set.
    """
    out: list[Violation] = []

    # Coordinate form is unambiguously a move.
    for m in _COORD_RE.finditer(text):
        if _attributed_to_opponent(text, m.start(), board):
            continue  # the opponent's reply, not a student move — validated against the wrong side
        frm, to = m.group(1).lower(), m.group(2).lower()
        try:
            src = chess.parse_square(frm)
        except ValueError:
            continue
        if board.piece_at(src) is None:
            out.append(Violation("empty_source", m.group(0), f"{frm} is empty — no piece to move there"))
            continue
        move = _find_legal(board, frm, to)
        if move is None:
            out.append(Violation("illegal_move", m.group(0), f"{frm}-{to} is not legal here"))
            continue
        violation = _classify_named_move(move, m.group(0), by_uci, _warned_against(text, m.start()))
        if violation is not None:
            out.append(violation)

    # SAN form — only judge tokens that are unmistakably a move (a bare pawn
    # token like "e5" may be a square reference, so it is left alone).
    for m in _SAN_RE.finditer(text):
        if _attributed_to_opponent(text, m.start(), board):
            continue  # the opponent's reply, not a student move — validated against the wrong side
        token = m.group(1)
        if _is_piece_reference(token, board):
            continue  # "Be6" naming the bishop that already stands there, not a move
        clearly_a_move = token[0] in "KQRBNO" or "x" in token
        try:
            move = board.parse_san(token)
        except chess.IllegalMoveError:
            if clearly_a_move:
                out.append(Violation("illegal_move", token, "not legal in this position"))
            continue
        except (chess.InvalidMoveError, chess.AmbiguousMoveError, ValueError):
            continue
        if not clearly_a_move:
            continue
        violation = _classify_named_move(move, token, by_uci, _warned_against(text, m.start()))
        if violation is not None:
            out.append(violation)

    return out


# Wording that tells the student the game has ENDED. Searched in the prose with the
# move tokens stripped out: at v29 ply 1003 the coach wrote "Ra8#" and then "it gives
# check", so the notation carried the mate and the sentence contradicted it. A
# beginner is explicitly instructed away from notation, so the `#` cannot be treated
# as having informed them.
_MATE_WORDING_RE = re.compile(r"\b(?:checkmate|checkmates|mate|mated|mating)\b", re.IGNORECASE)
_DRAW_WORDING_RE = re.compile(r"\b(?:stalemate|stalemated|draw|drawn)\b", re.IGNORECASE)

# What an OPPONENT capture is said to win, read only from the text immediately after
# the move token. "win" is allowed here although the general capture check excludes it:
# adjacency to a specific capture is what separates "Nxc4, winning a pawn" from the
# material idiom "you win a pawn in the long run".
_OPPONENT_VICTIM_RE = re.compile(
    r"\b(?:winning|wins|win|captur\w*|tak\w*|grab\w*)\s+(?:the\s+|a\s+|an\s+|your\s+)?"
    r"(?:\w+\s+){0,2}?(pawn|knight|bishop|rook|queen)\b",
    re.IGNORECASE,
)

# "aimed to develop your king's bishop" — a claim about the student's INTENTION that
# names a piece. The piece noun must not be followed by an apostrophe, or "your king's
# bishop" would match "king" and check the wrong piece.
# The gap may not cross a comma or semicolon. Without that it bled into the next
# clause and read "attempt to develop, but Re4 is stronger — it hits the rook" as an
# intent to develop a ROOK, when the rook belongs to the opponent and the intent clause
# names no piece at all. Same failure the relation check had: pairing across clauses.
_INTENT_CLAIM_RE = re.compile(
    r"\b(?:aim\w*|attempt\w*|tried|trying|intend\w*|meant|hoped|wanted)\b[^.!?,;]{0,60}?"
    r"\b(?:your|the)\s+(?:\w+['\u2019]?s?\s+){0,2}?(pawn|knight|bishop|rook|queen|king)(?!['\u2019])\b",
    re.IGNORECASE,
)

_DEFENCE_VERBS = r"protect\w*|defend\w*|support\w*|guard\w*"

# "<defence verb> ... <piece> on <square>" — the CLAIM. The defender is resolved
# separately, by looking back for the nearest named piece-and-square, because the
# two are routinely in different sentences: "the best choice was Ke2, improving king
# safety. … moving it to e2 helps protect your pawn on g2."
_DEFENCE_TARGET_RE = re.compile(
    rf"\b(?:{_DEFENCE_VERBS})\b[^.!?]{{0,60}}?\b(?:pawn|knight|bishop|rook|queen|king)\s+(?:on|at)\s+([a-h][1-8])\b",
    re.IGNORECASE,
)

# A piece named with its square: "Ke2", "Nd2". Searched BACKWARDS from the claim so
# the nearest one wins — pairing a distant SAN with an unrelated target is the one
# way this check could produce a false positive.
_PIECE_AT_SQUARE_RE = re.compile(r"\b([KQRBN])([a-h][1-8])\b")

#: How far back to look for the defender. Two sentences' worth; beyond that the
#: pairing is guesswork and the check stays silent instead.
_DEFENDER_LOOKBACK = 220

_SAN_LETTER_TO_TYPE = {"K": chess.KING, "Q": chess.QUEEN, "R": chess.ROOK, "B": chess.BISHOP, "N": chess.KNIGHT}


def _can_ever_attack(piece_type: int, frm: int, to: int) -> bool:
    """Could a ``piece_type`` on ``frm`` attack ``to`` on an OTHERWISE EMPTY board?

    Deliberately the most generous possible reading — blockers are ignored, so a
    rook's whole file counts. That makes a negative answer conclusive: if the piece
    cannot reach the square with the board swept clean, no arrangement of pieces
    makes the claim true. Precision-first by construction.
    """
    probe = chess.BaseBoard.empty()
    probe.set_piece_at(frm, chess.Piece(piece_type, chess.WHITE))
    return to in probe.attacks(frm)


def _check_terminal_label(text: str, board: chess.Board, played_uci: str = "") -> list[Violation]:
    """Flag a game-ending move the text does not say ends the game.

    The reviewer's decisive item, and the last thing a student reads: at v29 ply 1003
    the coach was shown `Ra8#`, called it "a check", and asked whether it "buys me
    time to develop or improve another piece". The game was over. Nothing caught it —
    the move is legal, the squares are real, and every other check passed.

    Deterministic: play each legally named move and ask the board. A move that ends
    the game and prose that never says so is a falsehood the student cannot detect,
    so it gates the send path like the other board-contradiction kinds.

    The move tokens are stripped before looking for mate wording, deliberately. The
    `#` suffix is not treated as having told the student anything: the beginner
    instructions tell the coach to avoid notation, so the sentence has to carry it.

    ``played_uci`` is checked in ADDITION to any move named in the text. A first
    version looked only at named moves and so missed the worst instance we had: v27
    ply 1003 described the mate without ever writing it down — "you delivered a check
    with your rook on the open a-file… does it buy me time to develop?" — and escaped
    for want of a parseable token. Prose that avoids notation is exactly what the
    beginner level asks for, so the check cannot depend on notation being present.
    """
    out: list[Violation] = []
    prose = _SAN_RE.sub(" ", text)
    mates: list[str] = []
    draws: list[str] = []
    seen: set[str] = set()
    candidates = [m.group(1) for m in _SAN_RE.finditer(text)]
    if played_uci:
        try:
            played = chess.Move.from_uci(played_uci)
        except ValueError:
            played = chess.Move.null()
        if played in board.legal_moves:
            candidates.append(board.san(played))
    for token in candidates:
        if token in seen:
            continue
        seen.add(token)
        try:
            move = board.parse_san(token)
        except (chess.InvalidMoveError, chess.IllegalMoveError, chess.AmbiguousMoveError, ValueError):
            continue
        after = board.copy(stack=False)
        after.push(move)
        if after.is_checkmate():
            mates.append(token)
        elif after.is_stalemate():
            draws.append(token)
    if mates and not _MATE_WORDING_RE.search(prose):
        out.append(
            Violation(
                "terminal_label",
                mates[0],
                f"{mates[0]} is checkmate and the game is over — the text never says so",
            )
        )
    if draws and not _DRAW_WORDING_RE.search(prose):
        out.append(
            Violation(
                "terminal_label",
                draws[0],
                f"{draws[0]} is stalemate and the game is drawn — the text never says so",
            )
        )
    return out


def _check_opponent_reply(text: str, board: chess.Board, played_uci: str) -> list[Violation]:
    """Validate moves the coach attributes to the OPPONENT, against the right board.

    Closes an exemption we created on purpose and then forgot. Claims about the
    opponent's reply were skipped everywhere: :func:`_attributed_to_opponent` waives
    the illegal-move check for them (correctly — they are not legal STUDENT moves),
    and the capture-victim check waives them too, because the victim type was inferred
    from the move the coach named for our own side. Sound in isolation, and together
    they left every claim about the opponent's reply unchecked.

    They are checkable, and against a board we can build ourselves: push the student's
    move and the opponent is to play. Two things then verify directly —

    * **legality.** v30 ply 46: "After your move c6, the opponent plays Bb7+". Bb7+ is
      a real move in the engine's line that begins 24.a3 — and the student's c6 is
      exactly what blocks the b7-f3 diagonal it checks along, so after c6 it cannot be
      played at all. The coach copied a move from a line starting with a different
      first move and presented it as the punishment for the move that prevents it.
    * **what it captures.** v30 ply 14: "the opponent plays Nxc4, winning a pawn" —
      c4 holds a bishop, and the same message says so two sentences later.

    Requires ``played_uci``: without the student's move there is no position to judge
    against, and guessing one is how the exemption came about in the first place.
    """
    if not played_uci:
        return []
    try:
        played = chess.Move.from_uci(played_uci)
    except ValueError:
        return []
    if played not in board.legal_moves:
        return []
    after = board.copy(stack=False)
    after.push(played)

    out: list[Violation] = []
    seen: set[str] = set()
    for m in _SAN_RE.finditer(text):
        token = m.group(1)
        if token in seen or not _attributed_to_opponent(text, m.start(), board):
            continue
        if _is_piece_reference(token, after):
            continue  # "Be6" naming a piece that stands there, not a move
        clearly_a_move = token[0] in "KQRBNO" or "x" in token
        if not clearly_a_move:
            continue
        seen.add(token)
        # _SAN_RE drops a trailing +/# — the closing \b cannot sit between two
        # non-word characters, so "Bb7+," matches as "Bb7". The check marker has to be
        # read from the raw text, and it is the whole falsehood in the ply-46 case:
        # Bb7 IS legal after c6, it simply is not check.
        suffix = text[m.end() : m.end() + 1]
        claims_check = suffix in ("+", "#")
        try:
            reply = after.parse_san(token)
        except chess.IllegalMoveError:
            out.append(
                Violation(
                    "opponent_reply",
                    token + suffix if claims_check else token,
                    f"the opponent cannot play {token} after your move",
                )
            )
            continue
        except (chess.InvalidMoveError, chess.AmbiguousMoveError, ValueError):
            continue
        if claims_check and not after.gives_check(reply):
            out.append(
                Violation(
                    "opponent_reply",
                    token + suffix,
                    f"{token} does not give check after your move",
                )
            )
            continue
        # The move is real; is what it takes described correctly?
        if "x" not in token:
            continue
        victim = "pawn" if after.is_en_passant(reply) else None
        if victim is None:
            piece = after.piece_at(reply.to_square)
            victim = chess.piece_name(piece.piece_type) if piece else None
        if victim is None:
            continue
        # "winning a <piece>" is accepted here as a claim about THIS capture, unlike in
        # the general capture check where "win" is excluded as a material idiom ("wins a
        # pawn" can mean a net edge). The narrowing that makes it safe is adjacency: the
        # phrase has to sit right after this move token, not anywhere in the message.
        window = text[m.end() : m.end() + 40]
        for claim in _OPPONENT_VICTIM_RE.finditer(window):
            claimed = claim.group(1).lower()
            if claimed != victim:
                out.append(
                    Violation(
                        "opponent_reply",
                        f"{token} … {claim.group(0)}",
                        f"{token} captures a {victim}, not a {claimed}",
                    )
                )
                break
    return out


def _check_intent_attribution(text: str, board: chess.Board, played_uci: str = "") -> list[Violation]:
    """Flag an "aimed to ... your <piece>" claim the move or the board contradicts.

    The student's intention is the one slot we can never fill: the coach is told what
    the move DOES, never why it was played, so anything it says about intent is
    invented. Measured across four runs it invents 5-7 of these per game, and most are
    unfalsifiable ("aimed to challenge Black's position") — but the ones that name a
    PIECE are checkable, and that is where it goes wrong.

    The case that made this the reviewer's second item, v29 ply 38: "Your move, h4,
    aimed to develop your king's bishop" — h4 moves a pawn, and White had no bishops
    at all. Two independent contradictions in one clause.

    Only fires on a named piece type, so the vague forms are left alone rather than
    guessed at. Verified against the same transcripts: ply 26's "aimed to develop the
    bishop" stays clean, because the move really was Bd4.
    """
    out: list[Violation] = []
    student = board.turn
    moved_type: int | None = None
    if played_uci:
        try:
            move = chess.Move.from_uci(played_uci)
        except ValueError:
            move = chess.Move.null()
        if move in board.legal_moves:
            piece = board.piece_at(move.from_square)
            moved_type = piece.piece_type if piece else None

    seen: set[str] = set()
    for m in _INTENT_CLAIM_RE.finditer(text):
        name = m.group(1).lower()
        if name in seen:
            continue
        claimed = _PIECE_NAME_TO_TYPE[name]
        fragment = " ".join(m.group(0).split())
        if not board.pieces(claimed, student):
            seen.add(name)
            out.append(Violation("intent", fragment, f"you have no {name} on the board"))
        elif moved_type is not None and moved_type != claimed:
            seen.add(name)
            actual = chess.piece_name(moved_type)
            out.append(Violation("intent", fragment, f"the move played moves a {actual}, not a {name}"))
    return out


def _check_defence_relation(text: str, board: chess.Board) -> list[Violation]:
    """Flag "moving to X protects your piece on Y" when X can never cover Y.

    The third class of falsehood found in three review rounds, after the wrong
    captured piece and the wrong owner. All three assert a RELATION between a piece
    and a square that the board settles; this one covers the defence family in one
    check rather than adding a fourth special case.

    The v28 cases: "moving it to e2 helps protect your pawn on g2" — a king on e2
    covers f2, never g2 — and "Ke3 … supports your passed pawn on d5", where e3 does
    not touch d5. A frontier review called them "false by geometry alone, needing no
    board", which is exactly what makes them safe to check: the test is whether the
    piece could reach the square on an empty board, so blockers, whose turn it is,
    and which move is actually played cannot produce a false positive.

    Only fires when the target square really holds a piece (otherwise it is a
    placement error, already reported) and the claimed defender square differs from
    the target.
    """
    out: list[Violation] = []
    seen: set[tuple[str, str]] = set()
    for m in _DEFENCE_TARGET_RE.finditer(text):
        to_name = m.group(1).lower()
        window = text[max(0, m.start() - _DEFENDER_LOOKBACK) : m.start()]
        defenders = list(_PIECE_AT_SQUARE_RE.finditer(window))
        if not defenders:
            continue  # no named defender to check the claim against
        nearest = defenders[-1]
        letter, frm_name = nearest.group(1).upper(), nearest.group(2).lower()
        if frm_name == to_name:
            continue
        try:
            frm = chess.parse_square(frm_name)
            to = chess.parse_square(to_name)
        except ValueError:
            continue
        if board.piece_at(to) is None:
            continue  # placement's business
        key = (frm_name, to_name)
        if key in seen:
            continue
        piece_type = _SAN_LETTER_TO_TYPE[letter]
        if _can_ever_attack(piece_type, frm, to):
            continue
        seen.add(key)
        name = chess.piece_name(piece_type)
        out.append(
            Violation(
                "relation",
                f"{letter}{frm_name} … {m.group(0).strip()}",
                f"a {name} on {frm_name} can never defend {to_name}",
            )
        )
    return out


def _check_ownership(text: str, board: chess.Board) -> list[Violation]:
    """Flag "your/their <piece> on <square>" claims that name the wrong side.

    The student is the side to move, which is what the coaching prompt is built
    around. Only fires when a piece of the CLAIMED TYPE is actually on the square:
    if the square is empty or holds something else, that is a placement error and
    the placement check already reports it — flagging both would double-count one
    mistake.
    """
    out: list[Violation] = []
    student = board.turn
    for m in _OWNERSHIP_RE.finditer(text):
        possessive, name, square = m.group(1).lower(), m.group(2).lower(), m.group(3)
        if _attributed_to_opponent(text, m.start(), board):
            continue  # inside a clause about the opponent's move — the frame of reference flips
        try:
            sq = chess.parse_square(square)
        except ValueError:
            continue
        piece = board.piece_at(sq)
        if piece is None or piece.piece_type != _PIECE_NAME_TO_TYPE[name]:
            continue  # placement's business, not ours
        claimed_student = possessive in _STUDENT_POSSESSIVES
        if (piece.color == student) is claimed_student:
            continue
        owner = "yours" if piece.color == student else "your opponent's"
        out.append(Violation("ownership", m.group(0), f"the {name} on {square} is {owner}"))
    return out


def _check_placement(text: str, board: chess.Board) -> list[Violation]:
    """Flag 'piece on square' claims the board denies (piece kind or emptiness)."""
    out: list[Violation] = []
    lower = text.lower()
    assessment_spans = [(a.start(), a.end()) for a in _SQUARE_ASSESSMENT_RE.finditer(lower)]
    for m in _PLACEMENT_RE.finditer(lower):
        name, square = m.group(1), m.group(2)
        if any(s <= m.start() <= e or s <= m.end() <= e for s, e in assessment_spans):
            continue
        preceding = lower[max(0, m.start() - 30) : m.start()]
        if any(verb in preceding for verb in _INFLUENCE_VERBS):
            continue
        try:
            sq = chess.parse_square(square)
        except ValueError:
            continue
        actual = board.piece_at(sq)
        expected = _PIECE_NAME_TO_TYPE[name]
        if actual is None:
            out.append(Violation("placement", m.group(0), f"{square} is empty"))
        elif actual.piece_type != expected:
            out.append(Violation("placement", m.group(0), f"{square} holds a {chess.piece_name(actual.piece_type)}"))
    return out


def _check_development(text: str, board: chess.Board) -> list[Violation]:
    """Flag developed/undeveloped claims the board's placement denies."""
    out: list[Violation] = []
    seen: set[tuple[str, str, bool]] = set()

    def _emit(name: str, square: str, claim_undeveloped: bool, frag: str) -> None:
        dev = minor_is_developed(board, square)
        if dev is None:
            return  # not a minor on that square — placement check owns that
        key = (name.lower(), square.lower(), claim_undeveloped)
        if key in seen:
            return
        seen.add(key)
        if claim_undeveloped and dev is True:
            out.append(Violation("development", frag, f"{name} on {square} has left its starting square"))
        elif not claim_undeveloped and dev is False:
            out.append(Violation("development", frag, f"{name} on {square} is still on its starting square"))

    for m in _DEV_RE.finditer(text):
        _emit(m.group(1), m.group(2), m.group(3) is not None, m.group(0))
    for m in _DEV_REV_RE.finditer(text):
        _emit(m.group(2), m.group(3), m.group(1) is not None, m.group(0))
    return out


def _check_empty_source(text: str, board: chess.Board) -> list[Violation]:
    """Flag 'from <square>' movement claims where the square is empty.

    Only fires when the fragment reads as a move source (a movement verb or a
    piece name shortly before 'from'), to avoid flagging prose like
    'pressure from e-file'. Coordinate 'from X to Y' emptiness is handled by
    the move check, so this covers the bare 'from <square>' phrasing.
    """
    out: list[Violation] = []
    lower = text.lower()
    move_cues = ("move", "moves", "moving", "retreat", "develop", "bring", "play", "reroute", "jump", "hop")
    for m in _FROM_RE.finditer(lower):
        square = m.group(1)
        preceding = lower[max(0, m.start() - 40) : m.start()]
        cue = any(v in preceding for v in move_cues) or any(p in preceding for p in _PIECE_NAME_TO_TYPE)
        if not cue:
            continue
        try:
            sq = chess.parse_square(square)
        except ValueError:
            continue
        if board.piece_at(sq) is None:
            out.append(Violation("empty_source", m.group(0), f"{square} is empty — no piece to move there"))
    return out


# ---------------------------------------------------------------------------
# BUG-015 extensions: piece-type on captures, pawn-structure & geometry claims.
# Each is anchored to an explicit square or a legal capture move so the checker
# never guesses which piece/square a loose phrase refers to (precision-first).
# ---------------------------------------------------------------------------

_PIECE_NOUN = r"(pawn|knight|bishop|rook|queen)"

# "captures/takes/grabs [the] <piece>" — a claim about WHICH piece was taken.
# "win(s)" is deliberately excluded: "wins a pawn" is idiomatic for a material
# edge, not necessarily capturing a pawn, and would false-positive.
#
# Up to two words may sit between the article and the piece noun, so adjectives do
# not hide the claim. Without this, "capturing the undefended bishop on b4" did not
# match at all and a real error went unflagged — and "undefended" is a word OUR OWN
# composer uses constantly ("attacking their undefended rook on f4"), which the
# coach echoes, so the gap was hiding precisely the errors most likely to occur.
# Bounded at two words to stay precision-first: "takes control of the bishop's
# diagonal" still does not match.
_CAPTURE_CLAIM_RE = re.compile(
    rf"\b(?:captur\w*|tak\w*|grab\w*)\s+(?:the\s+|a\s+|an\s+|your\s+|his\s+|her\s+|their\s+|my\s+)?"
    rf"(?:\w+\s+){{0,2}}{_PIECE_NOUN}\b",
    re.IGNORECASE,
)

# "isolated ... pawn ... on <sq>" and the reversed "pawn on <sq> ... isolated".
_ISOLATED_RE = re.compile(r"\bisolated\b[^.!?]{0,40}?\bpawn\b[^.!?]{0,25}?\bon\s+([a-h][1-8])\b", re.IGNORECASE)
_ISOLATED_REV_RE = re.compile(r"\bpawn\s+on\s+([a-h][1-8])\b[^.!?]{0,40}?\bisolated\b", re.IGNORECASE)

# "central[ized] <piece> on <sq>" and "<piece> on <sq> is ... central[ized]".
# Anchored to a piece + explicit square so plan-talk ("central control",
# "fight for the center") is never flagged.
_PIECES = r"pawn|knight|bishop|rook|queen|king"
_CENTRAL_RE = re.compile(
    rf"\bcentral(?:ized|ised)?\b\s+(?:\w+\s+){{0,2}}?(?:{_PIECES})\s+on\s+([a-h][1-8])\b", re.IGNORECASE
)
_CENTRAL_REV_RE = re.compile(
    rf"\b(?:{_PIECES})\s+on\s+([a-h][1-8])\b[^.!?]{{0,20}}?\bis\b[^.!?]{{0,15}}?\bcentral(?:ized|ised)?\b",
    re.IGNORECASE,
)
_CENTER_FILES = set("cdef")
_CENTER_RANKS = set("3456")


def _captured_piece_types(text: str, board: chess.Board) -> set[str]:
    """Piece-type names captured by the legal capture moves named in ``text``."""
    types: set[str] = set()
    for m in _SAN_RE.finditer(text):
        token = m.group(1)
        if "x" not in token:
            continue
        try:
            move = board.parse_san(token)
        except (chess.InvalidMoveError, chess.IllegalMoveError, chess.AmbiguousMoveError, ValueError):
            continue
        if not board.is_capture(move):
            continue
        if board.is_en_passant(move):
            types.add("pawn")
        else:
            victim = board.piece_at(move.to_square)
            if victim is not None:
                types.add(chess.piece_name(victim.piece_type))
    return types


def _check_capture_piece_type(text: str, board: chess.Board) -> list[Violation]:
    """Flag a capture described as taking the wrong piece type.

    Only fires when the legal capture moves named in the text agree on a
    single victim type, so the claim is unambiguous; a capture phrase naming a
    different piece is then a piece-type error. Bails on zero or multiple
    distinct victim types to stay precision-first.
    """
    victims = _captured_piece_types(text, board)
    if len(victims) != 1:
        return []
    (actual,) = tuple(victims)
    out: list[Violation] = []
    seen: set[str] = set()
    for m in _CAPTURE_CLAIM_RE.finditer(text):
        # The victim type was derived from the SAN the coach named, which is the
        # STUDENT's (or best) move. A phrase about the OPPONENT capturing is a
        # different capture entirely, so the derived type does not apply to it.
        # Without this, "the better move is Rxh7" (a pawn) made "your opponent can
        # capture your knight on c3" a piece-type error.
        if _attributed_to_opponent(text, m.start(), board):
            continue
        claimed = m.group(1).lower()
        if claimed == actual or claimed in seen:
            continue
        seen.add(claimed)
        out.append(Violation("piece_type", m.group(0), f"the captured piece is a {actual}, not a {claimed}"))
    return out


def _pawn_is_isolated(board: chess.Board, square: str) -> bool | None:
    """True/False if a pawn on ``square`` is isolated, None if no pawn there.

    Isolated = no friendly pawn on either adjacent file. Computed directly from
    the board so it is independent of the engine's pawn-structure fields.
    """
    try:
        sq = chess.parse_square(square)
    except ValueError:
        return None
    piece = board.piece_at(sq)
    if piece is None or piece.piece_type != chess.PAWN:
        return None
    file_idx = chess.square_file(sq)
    for adj in (file_idx - 1, file_idx + 1):
        if 0 <= adj <= 7:
            for rank in range(8):
                p = board.piece_at(chess.square(adj, rank))
                if p is not None and p.piece_type == chess.PAWN and p.color == piece.color:
                    return False
    return True


def _check_pawn_structure(text: str, board: chess.Board) -> list[Violation]:
    """Flag an 'isolated pawn on <sq>' claim the board denies."""
    out: list[Violation] = []
    seen: set[str] = set()
    for rx in (_ISOLATED_RE, _ISOLATED_REV_RE):
        for m in rx.finditer(text):
            square = m.group(1).lower()
            if _pawn_is_isolated(board, square) is not False or square in seen:
                continue
            seen.add(square)
            out.append(
                Violation(
                    "pawn_structure",
                    m.group(0),
                    f"the pawn on {square} is not isolated (a friendly pawn stands on an adjacent file)",
                )
            )
    return out


def _check_geometry(text: str, board: chess.Board) -> list[Violation]:
    """Flag a piece on <sq> called 'central' when <sq> is not a central square."""
    out: list[Violation] = []
    seen: set[str] = set()
    for rx in (_CENTRAL_RE, _CENTRAL_REV_RE):
        for m in rx.finditer(text):
            square = m.group(1).lower()
            if (square[0] in _CENTER_FILES and square[1] in _CENTER_RANKS) or square in seen:
                continue
            seen.add(square)
            out.append(Violation("geometry", m.group(0), f"{square} is not a central square"))
    return out


def _run_fidelity_checks(
    text: str,
    board: chess.Board,
    menu: list[MenuMove],
    played_uci: str = "",
) -> list[Violation]:
    """Run every fidelity pass over a parsed board and dedupe the result.

    Shared by :func:`check_coaching_fidelity` (report-based) and
    :func:`check_text_fidelity` (fen-based) so the checks have one
    implementation.
    """
    by_uci = _menu_by_uci(menu)
    violations: list[Violation] = []
    violations.extend(_check_named_moves(text, board, by_uci))
    violations.extend(_check_placement(text, board))
    violations.extend(_check_ownership(text, board))
    violations.extend(_check_defence_relation(text, board))
    violations.extend(_check_terminal_label(text, board, played_uci))
    violations.extend(_check_intent_attribution(text, board, played_uci))
    violations.extend(_check_opponent_reply(text, board, played_uci))
    violations.extend(_check_development(text, board))
    violations.extend(_check_empty_source(text, board))
    violations.extend(_check_capture_piece_type(text, board))
    violations.extend(_check_pawn_structure(text, board))
    violations.extend(_check_geometry(text, board))

    # Collapse the same fact reported by two phrasings (e.g. "from b8 to a6"
    # matching both the coordinate-move and the bare-"from" empty-source
    # checks) so a single empty square is one violation, not two.
    deduped: list[Violation] = []
    seen: set[tuple[str, str]] = set()
    for v in violations:
        key = (v.kind, v.detail)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(v)
    return deduped


#: Violation kinds that justify BLOCKING a response from reaching the student,
#: as opposed to merely counting it on a scoreboard.
#:
#: These are statements the board contradicts outright — a piece said to be
#: somewhere it is not, the wrong piece named as captured, a move that is not
#: legal. A 1200 cannot detect any of them, so a confident falsehood does not
#: merely fail to teach: it installs a false pattern. An external audit of what
#: makes coaching good put this above every teaching quality, as a gate rather
#: than a weighted term (docs/coaching-standard-audit.md).
#:
#: ``off_menu`` and ``unsound_move`` are deliberately EXCLUDED. They measure
#: adherence to our own "only name sound moves" rule rather than truth about the
#: board, and the warn-context guard that protects them is documented as
#: imprecise: a warning phrased AFTER the move ("Nxe4 loses a piece") is not
#: detected and still counts. That pattern is most likely in exactly the
#: mistake-explanation turns we least want to replace with a template. They stay
#: reported, and un-gated.
GATING_VIOLATION_KINDS = frozenset(
    {
        "placement",
        "ownership",
        "relation",
        "terminal_label",
        "intent",
        "opponent_reply",
        "piece_type",
        "empty_source",
        "illegal_move",
        "pawn_structure",
        "geometry",
        "development",
    }
)


def gating_violations(violations: list[Violation]) -> list[Violation]:
    """The subset of ``violations`` that should stop a response being sent."""
    return [v for v in violations if v.kind in GATING_VIOLATION_KINDS]


def generate_verified(
    generate: Callable[[], str],
    fen: str,
    fallback: Callable[[], str],
    *,
    retries: int = 1,
    played_uci: str = "",
    on_violation: Callable[[int, int, list[Violation]], None] | None = None,
    on_fallback: Callable[[list[Violation]], None] | None = None,
) -> str:
    """Generate text that does not contradict the board, else use ``fallback``.

    Kept here, next to the checks themselves, because BOTH the shipping coach and
    the report-card harness must do this identically. They had already drifted
    once — the harness mirrors ``Coach._select_guidance`` by hand, with a comment
    explaining that otherwise the report card grades a configuration that does not
    ship — and a divergence here would be worse: the harness would measure a coach
    with no output verification while the product had it, or the reverse.

    A retry is worthwhile because the model is sampled, so the same prompt is a
    genuinely different draw. After ``retries`` further attempts all contradict the
    board, ``fallback`` is used: composed text is degraded rather than wrong, which
    is the right way round when the reader cannot check the claim.

    Raises ``ValueError`` on an empty generation, so an existing caller's
    empty-response handling still fires.
    """
    attempts = max(0, retries) + 1
    last = ""
    last_bad: list[Violation] = []
    for attempt in range(1, attempts + 1):
        text = generate()
        if not text.strip():
            raise ValueError("Empty LLM response")
        last = text
        bad = gating_violations(check_text_fidelity(text, fen, played_uci=played_uci))
        if not bad:
            return text
        last_bad = bad
        if on_violation is not None:
            on_violation(attempt, attempts, bad)
    # Hand the violations to the fallback hook: a caller that only learns WHICH ply
    # fell back cannot say which check fired, and that question came up the first
    # time two unexplained fallbacks appeared in a run.
    if on_fallback is not None:
        on_fallback(last_bad)
    return fallback() or last


def check_coaching_fidelity(
    coaching_text: str,
    report: PositionReport,
    menu: list[MenuMove],
) -> list[Violation]:
    """Scan coaching text for claims contradicting the board / rules / menu.

    Pure and total: never raises; returns ``[]`` when nothing is detectably
    wrong (or the FEN cannot be parsed). ``menu`` is the engine-tagged
    candidate menu (from :func:`coaching_phrases.build_move_menu`); an empty
    menu simply disables the ``unsound_move`` check while the legality and
    placement checks still run.
    """
    try:
        board = chess.Board(report.fen)
    except ValueError:
        return []
    return _run_fidelity_checks(coaching_text, board, menu)


def check_text_fidelity(
    text: str,
    fen: str,
    menu: list[MenuMove] | None = None,
    played_uci: str = "",
) -> list[Violation]:
    """FEN-based fidelity check, for callers without a full ``PositionReport``.

    Same checks as :func:`check_coaching_fidelity`; the eval harness's
    objective layer uses this so there is a single implementation of the
    board/rules checks. An omitted menu disables the ``unsound_move`` check.
    """
    try:
        board = chess.Board(fen)
    except ValueError:
        return []
    return _run_fidelity_checks(text, board, menu or [], played_uci)
