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
    window = text[max(0, start - 45) : start].lower()
    if "opponent" in window or "after your move" in window or "in reply" in window:
        return True
    opp = "black" if board.turn == chess.WHITE else "white"
    return any(f"{opp} {verb}" in window for verb in _REPLY_VERBS)


@dataclasses.dataclass(frozen=True)
class Violation:
    """One detected contradiction in coaching text.

    ``kind`` is one of ``illegal_move`` / ``unsound_move`` / ``off_menu`` /
    ``placement`` / ``development`` / ``empty_source`` / ``piece_type`` /
    ``pawn_structure`` / ``geometry``; ``text`` is the offending fragment;
    ``detail`` explains why it is wrong.
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
_CAPTURE_CLAIM_RE = re.compile(
    rf"\b(?:captur\w*|tak\w*|grab\w*)\s+(?:the\s+|a\s+|an\s+|your\s+|his\s+|her\s+|their\s+|my\s+)?{_PIECE_NOUN}\b",
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
