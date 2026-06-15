"""Position-feature extraction for the pedagogy layer (Task 2).

``Position_Feature``s are the checkable characteristics of a position
that key ``Guidance_Entry`` selection. They are read off the engine's
``PositionReport`` (Req 2.1) plus two cheap, derived detections the
engine does not hand us directly (``open_file`` and ``exposed_king``),
and the opening context is looked up via :mod:`chess_coach.openings`.

The vocabulary is a **closed, code-defined set** (``FEATURE_VOCAB``):
adding a new feature is a deliberate code change (a new checkable
extraction), unlike adding a guidance entry, which is data-only
(Req 1.1). ``data/pedagogy/schema.md`` documents the names for authors,
and the annotation guard validates every entry's feature references
against this set (Req 6.2). Every name :func:`extract_features` can
emit is a member of ``FEATURE_VOCAB`` — the two are kept in sync by
deriving the emitted names from the named constants below.
"""

from __future__ import annotations

import chess

from chess_coach.models import PositionReport
from chess_coach.openings import lookup_fen

# --------------------------------------------------------------- vocabulary
#
# Named constants for every feature so the emitter and the vocabulary
# can never drift: ``FEATURE_VOCAB`` is built from exactly these names.

# Game phase (mutually exclusive — exactly one is emitted per position).
PHASE_OPENING = "phase:opening"
PHASE_MIDDLEGAME = "phase:middlegame"
PHASE_ENDGAME = "phase:endgame"

# Material safety, read off ``hanging_pieces``.
UNDEFENDED_PIECE = "undefended_piece"  # side to move has a hanging piece
HANGING_PIECE_OPPONENT = "hanging_piece_opponent"  # opponent has one

# An active threat exists in the position (``threats`` non-empty).
THREAT_PRESENT = "threat_present"

# Pawn-structure features, read off ``pawn_structure`` for side to move.
PASSED_PAWN = "passed_pawn"
ISOLATED_PAWN = "isolated_pawn"

# Derived detections (not directly in ``PositionReport``).
EXPOSED_KING = "exposed_king"  # king_safety score below threshold
OPEN_FILE = "open_file"  # a file with no pawns of either color

# Tactical motifs are emitted as ``tactic:<normalized type>``. The set is
# closed: the engine's known motif types plus the back-rank motif used in
# the curated resource. A motif whose normalized name is not here is not
# emitted, so the FEATURE_VOCAB invariant always holds.
TACTIC_PREFIX = "tactic:"
TACTIC_FORK = "tactic:fork"
TACTIC_PIN = "tactic:pin"
TACTIC_SKEWER = "tactic:skewer"
TACTIC_DISCOVERED_ATTACK = "tactic:discovered_attack"
TACTIC_DOUBLE_CHECK = "tactic:double_check"
TACTIC_BACK_RANK = "tactic:back_rank"

TACTIC_FEATURES: frozenset[str] = frozenset(
    {
        TACTIC_FORK,
        TACTIC_PIN,
        TACTIC_SKEWER,
        TACTIC_DISCOVERED_ATTACK,
        TACTIC_DOUBLE_CHECK,
        TACTIC_BACK_RANK,
    }
)

# The closed, exported feature vocabulary (Req 6.2). Everything
# :func:`extract_features` can emit is a member of this set.
FEATURE_VOCAB: frozenset[str] = (
    frozenset(
        {
            PHASE_OPENING,
            PHASE_MIDDLEGAME,
            PHASE_ENDGAME,
            UNDEFENDED_PIECE,
            HANGING_PIECE_OPPONENT,
            THREAT_PRESENT,
            PASSED_PAWN,
            ISOLATED_PAWN,
            EXPOSED_KING,
            OPEN_FILE,
        }
    )
    | TACTIC_FEATURES
)

# --------------------------------------------------------------- thresholds
#
# Tuning knobs kept as named module constants (not magic numbers) so the
# derived detections are documented and adjustable in one place.

# King-safety score (from ``KingSafety.score``) at or below which the
# side-to-move king counts as exposed. The score convention is "lower is
# worse" — the template layer already treats ``< -10`` as "concerning"
# (see ``coaching_templates._king_safety_text``); ``exposed_king`` uses a
# stronger bar so it keys guidance only for a genuinely unsafe king.
EXPOSED_KING_THRESHOLD = -50

# Phase heuristic. A position is the endgame once the combined count of
# major and minor pieces (queens, rooks, bishops, knights, both sides)
# drops to this many or fewer; otherwise it is the opening while the
# full-move number is still low, and the middlegame after that.
ENDGAME_MAJOR_MINOR_MAX = 6
OPENING_MAX_FULLMOVE = 10


def _side_to_move(fen: str) -> tuple[str, str]:
    """Return ``(side_to_move, opponent)`` as ``"white"`` / ``"black"``.

    The active color is the second FEN field. Defaults to white when the
    field is missing or unrecognized.
    """
    parts = fen.split()
    active = parts[1] if len(parts) > 1 else "w"
    if active == "b":
        return "black", "white"
    return "white", "black"


def _parse_board(fen: str) -> chess.Board | None:
    """Parse ``fen`` into a board, or None when the FEN is unusable.

    Board-derived features (phase, ``open_file``) are simply skipped for
    an unparseable FEN; the selector guards malformed positions wholesale
    before extraction (Req 2.8).
    """
    try:
        return chess.Board(fen)
    except ValueError:
        return None


def _phase_feature(board: chess.Board) -> str:
    """Classify the game phase from material on the board and move number.

    Endgame is checked first (it is keyed off remaining material, which is
    the more reliable signal late in the game); otherwise an early
    full-move number is the opening, and everything else the middlegame.
    """
    major_minor = (
        len(board.pieces(chess.QUEEN, chess.WHITE))
        + len(board.pieces(chess.QUEEN, chess.BLACK))
        + len(board.pieces(chess.ROOK, chess.WHITE))
        + len(board.pieces(chess.ROOK, chess.BLACK))
        + len(board.pieces(chess.BISHOP, chess.WHITE))
        + len(board.pieces(chess.BISHOP, chess.BLACK))
        + len(board.pieces(chess.KNIGHT, chess.WHITE))
        + len(board.pieces(chess.KNIGHT, chess.BLACK))
    )
    if major_minor <= ENDGAME_MAJOR_MINOR_MAX:
        return PHASE_ENDGAME
    if board.fullmove_number <= OPENING_MAX_FULLMOVE:
        return PHASE_OPENING
    return PHASE_MIDDLEGAME


def _has_open_file(board: chess.Board) -> bool:
    """True when at least one file carries no pawn of either color.

    An open file is a classic positional asset (rooks belong on open
    files); it is derived from the board because the engine report does
    not surface it directly.
    """
    for file_index in range(8):
        file_mask = chess.BB_FILES[file_index]
        if not (board.pieces_mask(chess.PAWN, chess.WHITE) & file_mask) and not (
            board.pieces_mask(chess.PAWN, chess.BLACK) & file_mask
        ):
            return True
    return False


def _normalize_tactic(motif_type: str) -> str:
    """Map a raw ``TacticalMotif.type`` to its ``tactic:`` feature name.

    Lower-cases and collapses spaces/hyphens to underscores so engine
    spellings line up with the closed vocabulary (e.g. ``"Discovered
    Attack"`` -> ``"tactic:discovered_attack"``).
    """
    norm = motif_type.strip().lower().replace("-", "_").replace(" ", "_")
    return f"{TACTIC_PREFIX}{norm}"


def extract_features(report: PositionReport) -> frozenset[str]:
    """Extract the set of ``Position_Feature``s present in ``report``.

    Reads features directly off the engine ``PositionReport`` (phase,
    hanging pieces, threats, tactics, pawn structure, king safety) and
    adds the two derived detections (``open_file``, ``exposed_king``).
    Every returned name is guaranteed to be a member of
    :data:`FEATURE_VOCAB` (Req 2.1, 6.2).
    """
    side, opponent = _side_to_move(report.fen)
    features: set[str] = set()

    # Phase + open_file are board-derived; skip them if the FEN won't parse.
    board = _parse_board(report.fen)
    if board is not None:
        features.add(_phase_feature(board))
        if _has_open_file(board):
            features.add(OPEN_FILE)

    # Material safety from hanging_pieces (Req: undefended / opponent).
    if report.hanging_pieces.get(side):
        features.add(UNDEFENDED_PIECE)
    if report.hanging_pieces.get(opponent):
        features.add(HANGING_PIECE_OPPONENT)

    # An active threat for either side counts as a threat being present.
    if any(report.threats.get(s) for s in ("white", "black")):
        features.add(THREAT_PRESENT)

    # Tactical motifs -> tactic:<type>, kept inside the closed vocabulary.
    for motif in report.tactics:
        name = _normalize_tactic(motif.type)
        if name in TACTIC_FEATURES:
            features.add(name)

    # Pawn-structure features for the side to move.
    pawns = report.pawn_structure.get(side)
    if pawns is not None:
        if pawns.passed:
            features.add(PASSED_PAWN)
        if pawns.isolated:
            features.add(ISOLATED_PAWN)

    # Exposed king (threshold-based) for the side to move.
    king = report.king_safety.get(side)
    if king is not None and king.score <= EXPOSED_KING_THRESHOLD:
        features.add(EXPOSED_KING)

    return frozenset(features)


def eco_context(fen: str) -> str | None:
    """Return the ECO code for ``fen``'s opening context, or None.

    Thin wrapper over :func:`chess_coach.openings.lookup_fen` (reused
    unchanged, Req 2.2): the selector keys ``Plan`` entries off this code.
    """
    info = lookup_fen(fen)
    return info.eco if info is not None else None
