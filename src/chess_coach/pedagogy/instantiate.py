"""Instantiate curated guidance with the board fact that made it fire.

The architecture review named this the one genuine architectural flaw: the
pedagogy YAML does double duty it cannot do — it is both the content source
("what principle applies here") and the teaching scaffold ("how to connect it to
this position"). A YAML entry can only supply *abstract* prose, so the prompt
handed the model an abstraction and the model anchored to it and echoed it. You
cannot prompt your way out of that, because the abstract text IS the signal.

The fix, in the same composed-not-derived spirit that worked for the best-move
"why": an entry is selected precisely *because* one of its
``Position_Feature``s was found on the board, so we can state the fact that
fired it. ``development`` stops being "develop your pieces" and becomes
"development — *here*: your knight on b1 and bishop on c1 have not moved".

Deliberately NOT done via a new YAML field per entry: that would mean editing
every entry plus a slot-filling mechanism, when the fact is already derivable
from the report the selector matched against. Facts are composed from the
engine's structured fields and the board (never invented); a feature with no
composable fact simply yields nothing and the entry renders as before.
"""

from __future__ import annotations

import chess

from chess_coach.models import PositionReport
from chess_coach.pedagogy.features import (
    EXPOSED_KING,
    FAVORABLE_CAPTURE,
    HANGING_PIECE_OPPONENT,
    ISOLATED_PAWN,
    MATERIAL_LEAD,
    OPEN_FILE,
    PASSED_PAWN,
    PAWN_MAJORITY,
    TACTIC_PREFIX,
    THREAT_PRESENT,
    UNDEFENDED_PIECE,
    extract_features,
)


def _side_names(fen: str) -> tuple[str, str]:
    """``(side_to_move, opponent)`` as the engine's dict keys."""
    parts = fen.split()
    return ("black", "white") if len(parts) > 1 and parts[1] == "b" else ("white", "black")


def _describe_target(board: chess.Board | None, square: str, threat_is_ours: bool) -> str:
    """Name what stands on ``square``, so a threat reads unambiguously.

    "the opponent threatens e3" was read by the model as the opponent MOVING to
    e3; "the opponent threatens your pawn on e3" cannot be. Whose piece it is
    follows from who owns the threat, not from the phrasing of the fact: a threat
    of ours points at their piece, and theirs at ours.

    Falls back to naming the square when it is empty — a threat can be aimed at a
    square nobody occupies (an infiltration or mating square), and inventing a
    piece there would be worse than being vague.
    """
    piece = None
    if board is not None:
        try:
            piece = board.piece_at(chess.parse_square(square))
        except ValueError:
            piece = None
    if piece is None:
        return f"the {square} square"
    owner = "their" if threat_is_ours else "your"
    return f"{owner} {chess.piece_name(piece.piece_type)} on {square}"


def feature_facts(report: PositionReport) -> dict[str, str]:
    """Map each present ``Position_Feature`` to a short, verified board fact.

    Only facts readable from the engine's structured fields or the board are
    produced — nothing is inferred — and the result is FILTERED to the features
    actually present in the position (via :func:`extract_features`). That filter
    is not cosmetic: an early version emitted "you are ahead in material"
    unconditionally, which is plainly false in the starting position. A
    fabricated "fact" is worse than an abstract principle.

    Features with no composable fact are absent from the mapping, so the caller
    renders those entries unchanged.
    """
    present = extract_features(report)
    side, opponent = _side_names(report.fen)
    try:
        board: chess.Board | None = chess.Board(report.fen)
    except ValueError:
        board = None
    facts: dict[str, str] = {}

    mine = report.hanging_pieces.get(side) or []
    if mine:
        hp = mine[0]
        facts[UNDEFENDED_PIECE] = f"your {hp.piece} on {hp.square} is undefended"
    theirs = report.hanging_pieces.get(opponent) or []
    if theirs:
        hp = theirs[0]
        facts[HANGING_PIECE_OPPONENT] = f"their {hp.piece} on {hp.square} is undefended"

    # WHOSE threat, and WHAT is threatened. Both halves were learned the hard way.
    #
    # First version: "there is a live threat against c8", no side. The model read
    # it as a danger TO the student every time — in a position where the student
    # had mate in one it wrote "your king is vulnerable if you don't act".
    #
    # Second version named the side but only the square: "the opponent threatens
    # e3". A bare square is ambiguous between "threatens to move to e3" and
    # "threatens the piece standing on e3", and the model chose the first, writing
    # "your opponent plays e3, winning material because your pawn on e3 is
    # undefended" — for a square OUR pawn occupies. So name the piece under
    # threat, which the board tells us.
    for owner, phrasing in ((side, "you threaten {}"), (opponent, "the opponent threatens {}")):
        for threat in report.threats.get(owner) or []:
            if not threat.target_squares:
                continue
            square = threat.target_squares[0]
            facts[THREAT_PRESENT] = phrasing.format(_describe_target(board, square, owner == side))
            break
        if THREAT_PRESENT in facts:
            break

    pawns = report.pawn_structure.get(side)
    if pawns is not None:
        if pawns.isolated:
            facts[ISOLATED_PAWN] = f"your {pawns.isolated[0]}-file pawn is isolated"
        if pawns.passed:
            facts[PASSED_PAWN] = f"you have a passed pawn on the {pawns.passed[0]}-file"

    king = report.king_safety.get(side)
    if king is not None:
        if king.missing_shield_files:
            files = ", ".join(king.missing_shield_files)
            facts[EXPOSED_KING] = f"your king lacks pawn cover on the {files} file(s)"
        elif king.king_square:
            facts[EXPOSED_KING] = f"your king on {king.king_square} is exposed"

    for motif in report.tactics:
        name = f"{TACTIC_PREFIX}{motif.type.strip().lower().replace('-', '_').replace(' ', '_')}"
        if name not in facts and motif.squares:
            facts[name] = f"a {motif.type.replace('_', ' ')} involving {', '.join(motif.squares[:2])}"

    if board is not None:
        for file_index in range(8):
            mask = chess.BB_FILES[file_index]
            if not (board.pieces_mask(chess.PAWN, chess.WHITE) & mask) and not (
                board.pieces_mask(chess.PAWN, chess.BLACK) & mask
            ):
                facts[OPEN_FILE] = f"the {chess.FILE_NAMES[file_index]}-file is open"
                break
        # NB: deliberately NOT keying the "pieces still at home" fact to
        # ``phase:opening``. Several entries share that feature (development AND
        # center control), so the fact landed on the wrong theme — "center
        # control ... HERE: your bishops have not moved" is a mismatch, and a
        # mis-attached fact is its own kind of wrongness. Only semantically
        # matched facts are emitted below.
        queenside = chess.BB_FILE_A | chess.BB_FILE_B | chess.BB_FILE_C
        kingside = chess.BB_FILE_F | chess.BB_FILE_G | chess.BB_FILE_H
        wings: tuple[tuple[str, int], ...] = (("queenside", queenside), ("kingside", kingside))
        for wing, wing_mask in wings:
            ours = chess.popcount(board.pieces_mask(chess.PAWN, board.turn) & wing_mask)
            theirs_n = chess.popcount(board.pieces_mask(chess.PAWN, not board.turn) & wing_mask)
            if ours > theirs_n:
                facts[PAWN_MAJORITY] = f"you have a {ours}-{theirs_n} pawn majority on the {wing}"
                break
        facts[MATERIAL_LEAD] = "you are ahead in material"
        facts[FAVORABLE_CAPTURE] = "a capture is available that wins material"
    # Only facts for features the position actually has (see the docstring).
    return {feature: fact for feature, fact in facts.items() if feature in present}
