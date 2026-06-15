"""Tests for pedagogy position-feature extraction and ECO context (Task 2).

Covers ``extract_features`` mapping representative ``PositionReport``s to
the expected ``Position_Feature`` sets, the closed-vocabulary invariant,
the two derived detections (``open_file``, ``exposed_king``), and the
``eco_context`` opening lookup wrapper.
"""

from __future__ import annotations

from chess_coach.models import (
    EvalBreakdown,
    HangingPiece,
    KingSafety,
    PawnFeatures,
    PositionReport,
    TacticalMotif,
    Threat,
)
from chess_coach.pedagogy.features import (
    EXPOSED_KING,
    EXPOSED_KING_THRESHOLD,
    FEATURE_VOCAB,
    HANGING_PIECE_OPPONENT,
    ISOLATED_PAWN,
    OPEN_FILE,
    PASSED_PAWN,
    PHASE_ENDGAME,
    PHASE_OPENING,
    TACTIC_BACK_RANK,
    TACTIC_FORK,
    TACTIC_PIN,
    THREAT_PRESENT,
    UNDEFENDED_PIECE,
    eco_context,
    extract_features,
)

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
# 1. e4 e5 2. Nf3 Nc6 3. Bc4 — Italian Game, ECO C50 (black to move).
ITALIAN_FEN = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"
# K+R vs K with intact pawn shelters: an endgame with several open files.
BACK_RANK_FEN = "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1"


def _report(
    fen: str = START_FEN,
    *,
    eval_cp: int = 0,
    hanging_white: list[HangingPiece] | None = None,
    hanging_black: list[HangingPiece] | None = None,
    threats_white: list[Threat] | None = None,
    threats_black: list[Threat] | None = None,
    pawns_white: PawnFeatures | None = None,
    pawns_black: PawnFeatures | None = None,
    king_white: KingSafety | None = None,
    king_black: KingSafety | None = None,
    tactics: list[TacticalMotif] | None = None,
) -> PositionReport:
    """Build a minimal ``PositionReport`` for feature extraction.

    Mirrors the ``_report`` helper style in ``tests/test_eval_judge.py``,
    widened so each test can set just the fields it cares about.
    """
    empty_pawns = PawnFeatures([], [], [])
    return PositionReport(
        fen=fen,
        eval_cp=eval_cp,
        eval_breakdown=EvalBreakdown(material=0, mobility=20, king_safety=0, pawn_structure=0),
        hanging_pieces={"white": hanging_white or [], "black": hanging_black or []},
        threats={"white": threats_white or [], "black": threats_black or []},
        pawn_structure={
            "white": pawns_white or empty_pawns,
            "black": pawns_black or empty_pawns,
        },
        king_safety={
            "white": king_white or KingSafety(0, ""),
            "black": king_black or KingSafety(0, ""),
        },
        top_lines=[],
        tactics=tactics or [],
        threat_map=[],
        threat_map_summary=None,
        critical_moment=False,
        critical_reason=None,
    )


def _threat() -> Threat:
    return Threat(type="capture", source_square="d1", target_squares=["d8"], description="")


# --------------------------------------------------------------- phase


def test_start_position_is_opening_only() -> None:
    # Full material, move 1, pawn on every file -> just the opening phase.
    assert extract_features(_report(START_FEN)) == frozenset({PHASE_OPENING})


def test_low_material_is_endgame() -> None:
    feats = extract_features(_report(BACK_RANK_FEN))
    assert PHASE_ENDGAME in feats
    assert PHASE_OPENING not in feats


# --------------------------------------------------------------- material safety


def test_undefended_piece_is_side_to_move() -> None:
    # White to move with a hanging white piece -> undefended_piece; a
    # hanging black piece is the opponent's problem.
    report = _report(
        START_FEN,
        hanging_white=[HangingPiece("e4", "pawn", "white")],
        hanging_black=[HangingPiece("e5", "pawn", "black")],
    )
    feats = extract_features(report)
    assert UNDEFENDED_PIECE in feats
    assert HANGING_PIECE_OPPONENT in feats


def test_hanging_piece_perspective_flips_with_side_to_move() -> None:
    # Black to move: a hanging white piece is now the opponent's.
    black_to_move = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1"
    report = _report(black_to_move, hanging_white=[HangingPiece("e4", "pawn", "white")])
    feats = extract_features(report)
    assert HANGING_PIECE_OPPONENT in feats
    assert UNDEFENDED_PIECE not in feats


# --------------------------------------------------------------- threats / tactics


def test_threat_present_when_any_side_threatens() -> None:
    assert THREAT_PRESENT in extract_features(_report(START_FEN, threats_black=[_threat()]))


def test_tactics_map_to_tactic_features() -> None:
    tactics = [
        TacticalMotif("fork", ["d5"], ["N"], True, "knight fork"),
        TacticalMotif("pin", ["c6"], ["B"], True, "pin"),
        TacticalMotif("back_rank", ["e8"], ["R"], True, "back rank"),
    ]
    feats = extract_features(_report(START_FEN, tactics=tactics))
    assert {TACTIC_FORK, TACTIC_PIN, TACTIC_BACK_RANK} <= feats


def test_unknown_tactic_type_is_not_emitted() -> None:
    # A motif type outside the closed vocabulary is dropped, never emitted
    # as an unknown feature.
    feats = extract_features(_report(START_FEN, tactics=[TacticalMotif("zwischenzug", [], [], True, "")]))
    assert not any(f.startswith("tactic:") for f in feats)


def test_tactic_type_is_normalized() -> None:
    feats = extract_features(_report(START_FEN, tactics=[TacticalMotif("Back-Rank", ["e8"], ["R"], True, "")]))
    assert TACTIC_BACK_RANK in feats


# --------------------------------------------------------------- pawn structure


def test_passed_and_isolated_pawns_for_side_to_move() -> None:
    report = _report(START_FEN, pawns_white=PawnFeatures(isolated=["d"], doubled=[], passed=["e"]))
    feats = extract_features(report)
    assert PASSED_PAWN in feats
    assert ISOLATED_PAWN in feats


def test_pawn_features_use_side_to_move_only() -> None:
    # Black's pawn features must not leak in when it is White to move.
    report = _report(START_FEN, pawns_black=PawnFeatures(isolated=["d"], doubled=[], passed=["e"]))
    feats = extract_features(report)
    assert PASSED_PAWN not in feats
    assert ISOLATED_PAWN not in feats


# --------------------------------------------------------------- exposed_king (2.2)


def test_exposed_king_below_threshold() -> None:
    report = _report(START_FEN, king_white=KingSafety(EXPOSED_KING_THRESHOLD - 10, "open"))
    assert EXPOSED_KING in extract_features(report)


def test_exposed_king_at_threshold_is_exposed() -> None:
    report = _report(START_FEN, king_white=KingSafety(EXPOSED_KING_THRESHOLD, "open"))
    assert EXPOSED_KING in extract_features(report)


def test_safe_king_above_threshold_not_exposed() -> None:
    report = _report(START_FEN, king_white=KingSafety(EXPOSED_KING_THRESHOLD + 10, "safe"))
    assert EXPOSED_KING not in extract_features(report)


def test_exposed_king_uses_side_to_move() -> None:
    # A dangerously exposed *black* king does not flag while White moves.
    report = _report(START_FEN, king_black=KingSafety(EXPOSED_KING_THRESHOLD - 100, "open"))
    assert EXPOSED_KING not in extract_features(report)


# --------------------------------------------------------------- open_file (2.2)


def test_open_file_detected_when_a_file_has_no_pawns() -> None:
    # In the back-rank FEN, pawns sit only on f/g/h -> a, b, c, d, e are
    # open files.
    assert OPEN_FILE in extract_features(_report(BACK_RANK_FEN))


def test_no_open_file_in_start_position() -> None:
    # The start position has a pawn on every file -> no open file.
    assert OPEN_FILE not in extract_features(_report(START_FEN))


# --------------------------------------------------------------- vocab invariant


def test_every_emitted_feature_is_in_vocab() -> None:
    reports = [
        _report(START_FEN),
        _report(BACK_RANK_FEN),
        _report(
            START_FEN,
            hanging_white=[HangingPiece("e4", "pawn", "white")],
            hanging_black=[HangingPiece("e5", "pawn", "black")],
            threats_white=[_threat()],
            pawns_white=PawnFeatures(isolated=["d"], doubled=["c"], passed=["e"]),
            king_white=KingSafety(EXPOSED_KING_THRESHOLD - 5, "open"),
            tactics=[
                TacticalMotif("fork", [], [], True, ""),
                TacticalMotif("pin", [], [], True, ""),
                TacticalMotif("skewer", [], [], True, ""),
                TacticalMotif("discovered_attack", [], [], True, ""),
                TacticalMotif("double_check", [], [], True, ""),
                TacticalMotif("back_rank", [], [], True, ""),
            ],
        ),
    ]
    for report in reports:
        assert extract_features(report) <= FEATURE_VOCAB


def test_seed_resource_features_are_covered_by_vocab() -> None:
    # The curated seed must only reference names this extractor can emit.
    from chess_coach.pedagogy.resource import default_resource_path, load_resource

    resource = load_resource(default_resource_path())
    used = frozenset().union(*(e.features for e in resource.entries))
    assert used <= FEATURE_VOCAB


# --------------------------------------------------------------- eco_context (2.3)


def test_eco_context_known_opening() -> None:
    assert eco_context(ITALIAN_FEN) == "C50"


def test_eco_context_non_opening_returns_none() -> None:
    assert eco_context(BACK_RANK_FEN) is None
