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


@dataclasses.dataclass(frozen=True)
class Violation:
    """One detected contradiction in coaching text.

    ``kind`` is one of ``illegal_move`` / ``unsound_move`` / ``off_menu`` /
    ``placement`` / ``development`` / ``empty_source``; ``text`` is the
    offending fragment; ``detail`` explains why it is wrong.
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


def _classify_named_move(move: chess.Move, frag: str, by_uci: dict[str, MenuMove]) -> Violation | None:
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
    """
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
        violation = _classify_named_move(move, m.group(0), by_uci)
        if violation is not None:
            out.append(violation)

    # SAN form — only judge tokens that are unmistakably a move (a bare pawn
    # token like "e5" may be a square reference, so it is left alone).
    for m in _SAN_RE.finditer(text):
        token = m.group(1)
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
        violation = _classify_named_move(move, token, by_uci)
        if violation is not None:
            out.append(violation)

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


def _run_fidelity_checks(text: str, board: chess.Board, menu: list[MenuMove]) -> list[Violation]:
    """Run every fidelity pass over a parsed board and dedupe the result.

    Shared by :func:`check_coaching_fidelity` (report-based) and
    :func:`check_text_fidelity` (fen-based) so the checks have one
    implementation.
    """
    by_uci = _menu_by_uci(menu)
    violations: list[Violation] = []
    violations.extend(_check_named_moves(text, board, by_uci))
    violations.extend(_check_placement(text, board))
    violations.extend(_check_development(text, board))
    violations.extend(_check_empty_source(text, board))

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
    return _run_fidelity_checks(text, board, menu or [])
