"""Tests for the output fidelity checker (verify.check_coaching_fidelity).

Precision-first checks of finished coaching text against the board, the rules,
and the engine-tagged move menu. The motivating live failure: after adding
piece placement the coach stopped inventing pieces but still suggested
``Nxe4`` in the Italian — a legal but unsound move that drops the knight.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from chess_coach.coaching_phrases import MenuMove
from chess_coach.models import (
    EvalBreakdown,
    KingSafety,
    PawnFeatures,
    PositionReport,
)
from chess_coach.verify import Violation, check_coaching_fidelity, check_text_fidelity

# Black to move. Black minors developed: Nc6, Nf6, Bc5. b8/g8 empty. e4 is a
# White pawn defended by Nc3 and the d3 pawn — so Nxe4 drops the knight.
ITALIAN_FEN = "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQK2R b KQkq - 0 5"


def _report(fen: str = ITALIAN_FEN) -> PositionReport:
    empty = PawnFeatures([], [], [])
    return PositionReport(
        fen=fen,
        eval_cp=0,
        eval_breakdown=EvalBreakdown(material=0, mobility=0, king_safety=0, pawn_structure=0),
        hanging_pieces={"white": [], "black": []},
        threats={"white": [], "black": []},
        pawn_structure={"white": empty, "black": empty},
        king_safety={"white": KingSafety(0, ""), "black": KingSafety(0, "")},
        top_lines=[],
        tactics=[],
        threat_map=[],
        threat_map_summary=None,
        critical_moment=False,
        critical_reason=None,
    )


# The Italian menu: Nd5 sound (best), Nxe4 a blunder (drops the knight).
ITALIAN_MENU = [
    MenuMove(san="Nd5", uci="f6d5", eval_cp=20, drop_cp=0, tag="best", theme="piece development"),
    MenuMove(san="O-O", uci="e8g8", eval_cp=10, drop_cp=10, tag="sound", theme="king safety, castling"),
    MenuMove(san="Nxe4", uci="f6e4", eval_cp=-160, drop_cp=180, tag="blunder", theme="material win"),
]


def _kinds(violations: list[Violation]) -> list[str]:
    return [v.kind for v in violations]


def test_regression_unsound_move_is_flagged() -> None:
    # The live failure: coach names Nxe4, an engine-tagged blunder.
    text = "You could grab the pawn with Nxe4, but be careful."
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU)
    assert "unsound_move" in _kinds(v)


def test_regression_sound_move_is_not_flagged() -> None:
    # Naming the sound best move produces no violation.
    text = "Play Nd5 to centralize your knight on a strong square."
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU)
    assert v == []


def test_correct_advice_has_no_false_positive() -> None:
    text = (
        "Your knight on f6 is well placed and your bishop on c5 is active. "
        "A good plan is to castle to get your king safe."
    )
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU)
    assert v == []


def test_placement_lie_is_flagged() -> None:
    # b8 is empty in the Italian — "your knight on b8" is a placement lie.
    text = "Your knight on b8 should come into the game."
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU)
    assert _kinds(v) == ["placement"]


def test_placement_wrong_piece_is_flagged() -> None:
    # c5 holds a bishop, not a knight.
    text = "The knight on c5 eyes the center."
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU)
    assert _kinds(v) == ["placement"]
    assert "bishop" in v[0].detail


def test_false_undeveloped_claim_is_flagged() -> None:
    # Nf6 is developed; calling it undeveloped contradicts the board.
    text = "Your knight on f6 is undeveloped and needs to move."
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU)
    assert "development" in _kinds(v)


def test_developed_claim_true_is_not_flagged() -> None:
    text = "Your developed knight on f6 controls key squares."
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU)
    assert v == []


def test_empty_source_move_is_flagged() -> None:
    # The classic hallucination: "move your knight from b8" — b8 is empty.
    text = "You should move your knight from b8 into the center."
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU)
    assert _kinds(v) == ["empty_source"]


def test_empty_source_deduped_across_phrasings() -> None:
    # "from b8 to a6" matches both the coordinate-move and bare-from checks;
    # a single empty square must be one violation, not two.
    text = "Move your knight from b8 to a6."
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU)
    assert _kinds(v) == ["empty_source"]


def test_illegal_named_move_is_flagged() -> None:
    # Rd4 — no black rook can reach d4 here; clearly a move (piece letter).
    text = "The move Rd4 looks tempting."
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU)
    assert "illegal_move" in _kinds(v)


def test_bare_square_reference_not_flagged_as_move() -> None:
    # "the e4 square" is a reference, not a move — must not be an illegal_move.
    text = "The e4 pawn is a target and the d5 square is strong."
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU)
    assert "illegal_move" not in _kinds(v)


def test_empty_menu_disables_unsound_but_keeps_legality() -> None:
    text = "You could grab the pawn with Nxe4."
    v = check_coaching_fidelity(text, _report(), [])
    # No menu -> no soundness/adherence judgment, but the move is legal so
    # nothing flags (off_menu needs a menu to compare against).
    assert v == []


# A realistic menu that does NOT list Nxe4 (a knight-drop the engine ranks
# below the top candidates) — the real-world case where the coach naming
# Nxe4 is an off-menu recommendation, not a listed-but-bad one.
ITALIAN_MENU_NO_NXE4 = [
    MenuMove(san="Nd5", uci="f6d5", eval_cp=20, drop_cp=0, tag="best", theme="piece development"),
    MenuMove(san="O-O", uci="e8g8", eval_cp=10, drop_cp=10, tag="sound", theme="king safety, castling"),
]


def test_off_menu_move_is_flagged() -> None:
    # Nxe4 is legal but not in the sound menu -> off_menu (the coach was told
    # to recommend only listed moves). This is the real Nxe4 case.
    text = "You could grab the pawn with Nxe4."
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU_NO_NXE4)
    assert _kinds(v) == ["off_menu"]


def test_off_menu_not_flagged_for_listed_sound_move() -> None:
    text = "Play Nd5 to centralize; O-O is also fine."
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU_NO_NXE4)
    assert v == []


def test_off_menu_needs_a_menu() -> None:
    # Without a menu we cannot judge adherence, so no off_menu is emitted.
    text = "You could grab the pawn with Nxe4."
    assert check_coaching_fidelity(text, _report(), []) == []


def test_warned_against_move_is_not_flagged() -> None:
    # Naming a bad move to warn against it is allowed by the prompt.
    for text in (
        "Avoid Nxe4 — it drops the knight.",
        "Don't play Nxe4 here.",
        "Play Nd5 instead of Nxe4.",
        "You might be tempted to play Nxe4, but it loses a piece.",
    ):
        v = check_coaching_fidelity(text, _report(), ITALIAN_MENU_NO_NXE4)
        assert "off_menu" not in _kinds(v), text


def test_recommended_bad_move_still_flagged_without_warning() -> None:
    # No warning cue -> naming the off-menu move is a violation.
    v = check_coaching_fidelity("A strong try is Nxe4.", _report(), ITALIAN_MENU_NO_NXE4)
    assert _kinds(v) == ["off_menu"]


def test_illegal_move_flagged_even_when_warned() -> None:
    # Illegality is a factual error regardless of framing, so it still fires.
    v = check_coaching_fidelity("Avoid Rd4, it loses.", _report(), ITALIAN_MENU_NO_NXE4)
    assert "illegal_move" in _kinds(v)


def test_bad_fen_returns_empty() -> None:
    bad = _report(fen="not a fen")
    assert check_coaching_fidelity("Play Nxe4 from b8.", bad, ITALIAN_MENU) == []


@given(st.text(max_size=200))
def test_property_checker_is_total(text: str) -> None:
    # Property 3: never raises over arbitrary text.
    result = check_coaching_fidelity(text, _report(), ITALIAN_MENU)
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# BUG-015: piece-type on captures, pawn-structure & geometry claims.
# ---------------------------------------------------------------------------

# Black to move; the black d4 pawn can capture the white knight on e3 (dxe3).
CAPTURE_FEN = "4k3/8/8/8/3p4/4N3/8/4K3 b - - 0 1"
# White pawns on c4 and d4 (adjacent files) -> c4 is NOT isolated.
ADJACENT_PAWNS_FEN = "4k3/8/8/8/2PP4/8/8/4K3 w - - 0 1"
# A lone white c4 pawn -> genuinely isolated.
LONE_PAWN_FEN = "4k3/8/8/8/2P5/8/8/4K3 w - - 0 1"
# White king on c1 (queenside back rank — not central).
KING_C1_FEN = "4k3/8/8/8/8/8/8/2K5 w - - 0 1"


def test_capture_wrong_piece_type_is_flagged() -> None:
    # dxe3 captures a KNIGHT; calling it a pawn is a piece-type error.
    text = "Nice — you capture the pawn with dxe3."
    v = check_coaching_fidelity(text, _report(CAPTURE_FEN), [])
    assert _kinds(v) == ["piece_type"]
    assert "knight" in v[0].detail and "pawn" in v[0].detail


def test_capture_correct_piece_type_not_flagged() -> None:
    text = "Good, you take the knight with dxe3."
    v = check_coaching_fidelity(text, _report(CAPTURE_FEN), [])
    assert "piece_type" not in _kinds(v)


def test_capture_win_idiom_not_flagged() -> None:
    # "wins a pawn" is a material idiom, not a claim about the captured piece;
    # the "win" verb is deliberately excluded to avoid this false positive.
    text = "dxe3 and you win a pawn."
    v = check_coaching_fidelity(text, _report(CAPTURE_FEN), [])
    assert "piece_type" not in _kinds(v)


def test_capture_wrong_piece_type_behind_adjective_is_flagged() -> None:
    # Judge-found gap (v24 ply 36): an adjective between the article and the
    # piece noun hid the claim entirely, so the checker stayed silent on a real
    # error. "undefended" is a word our own composer uses constantly, so this
    # gap hid exactly the mistakes most likely to occur.
    # bxc4 takes the KNIGHT on c4; a bishop also sits on b4, which is what the
    # coach named.
    fen = "r1b1k1r1/pppp1p1p/8/6P1/1bnP4/1P6/P1P1K2P/RN5R w q - 0 19"
    text = "bxc4 is strong, capturing the undefended bishop on b4."
    v = check_coaching_fidelity(text, _report(fen), [])
    assert "piece_type" in _kinds(v)
    detail = next(x.detail for x in v if x.kind == "piece_type")
    assert "knight" in detail and "bishop" in detail


def test_takes_control_of_a_diagonal_not_flagged() -> None:
    # The two-word bound keeps the widened pattern precision-first: three or
    # more words between the verb and the piece noun means the phrase is about
    # something other than the captured piece.
    text = "dxe3 takes control of the bishop's diagonal."
    v = check_coaching_fidelity(text, _report(CAPTURE_FEN), [])
    assert "piece_type" not in _kinds(v)


# White to move. A BLACK bishop sits on e6, pinned by Re1 to Ke7; White has no
# bishop at all, so "Be6" cannot be a White move. Rxh7 captures a PAWN.
PIN_REFERENCE_FEN = "4r3/p1p1kpRp/1pp1b3/8/1r6/2N5/5K2/4R3 w - - 0 31"


def test_piece_reference_not_read_as_a_move() -> None:
    # "Be6" here names the bishop standing on e6. Our own composer writes exactly
    # this ("Re1 pins Be6 to Ke7") and the coach echoes it, so reading it as a
    # bishop move produced a phantom illegal_move.
    text = "The pin on Be6 and f7 means you can attack without fear of recapture."
    v = check_coaching_fidelity(text, _report(PIN_REFERENCE_FEN), [])
    assert "illegal_move" not in _kinds(v)


def test_opponent_capture_claim_not_judged_against_our_move() -> None:
    # Rxh7 takes a pawn; the knight claim is about what the OPPONENT can capture,
    # a different capture entirely, so the pawn victim must not be applied to it.
    text = "Your opponent can capture your knight on c3. The better move is Rxh7."
    v = check_coaching_fidelity(text, _report(PIN_REFERENCE_FEN), [])
    assert "piece_type" not in _kinds(v)


def test_our_own_capture_claim_still_checked() -> None:
    # The opponent-attribution escape must not disable the check for the coach's
    # own claims: Rxh7 takes a pawn, so calling it a bishop is still an error.
    text = "The better move is Rxh7, capturing their bishop."
    v = check_coaching_fidelity(text, _report(PIN_REFERENCE_FEN), [])
    assert "piece_type" in _kinds(v)


def test_pawn_falsely_called_isolated_is_flagged() -> None:
    text = "The isolated pawn on c4 is a long-term weakness."
    v = check_coaching_fidelity(text, _report(ADJACENT_PAWNS_FEN), [])
    assert _kinds(v) == ["pawn_structure"]


def test_truly_isolated_pawn_not_flagged() -> None:
    text = "The isolated pawn on c4 needs defending."
    v = check_coaching_fidelity(text, _report(LONE_PAWN_FEN), [])
    assert "pawn_structure" not in _kinds(v)


def test_noncentral_square_called_central_is_flagged() -> None:
    for text in ("Your king on c1 is nicely central.", "The central king on c1 feels exposed."):
        v = check_coaching_fidelity(text, _report(KING_C1_FEN), [])
        assert _kinds(v) == ["geometry"], text


def test_central_square_claim_not_flagged() -> None:
    # d4 is a central square, so calling a piece there central is fine.
    text = "Your knight on d4 is a strong central outpost."
    v = check_coaching_fidelity(text, _report(), [])
    assert "geometry" not in _kinds(v)


def test_center_plan_talk_not_flagged_as_geometry() -> None:
    # No piece+square anchor -> plan-talk about the center must not flag.
    text = "Fight for central control and castle to safety."
    v = check_coaching_fidelity(text, _report(), ITALIAN_MENU)
    assert "geometry" not in _kinds(v)


# White to move; "fxg5" is illegal for White (no White f-pawn reaches g5).
_WHITE_TO_MOVE = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def test_opponent_reply_move_not_flagged_illegal() -> None:
    # The coach names the OPPONENT's punishing reply (the refutation), which is
    # not a legal STUDENT move — it must not be counted as an illegal move.
    for text in (
        "After your move, Black plays fxg5, winning material.",
        "Then the opponent plays fxg5 and you're worse.",
        "Black can respond with fxg5.",
    ):
        v = check_text_fidelity(text, _WHITE_TO_MOVE)
        assert "illegal_move" not in [x.kind for x in v], text


def test_illegal_move_still_flagged_without_opponent_attribution() -> None:
    # No opponent attribution -> a move the coach tells the student to play.
    v = check_text_fidelity("You should play fxg5 here.", _WHITE_TO_MOVE)
    assert "illegal_move" in [x.kind for x in v]


@given(st.text(max_size=200))
def test_property_checker_is_deterministic(text: str) -> None:
    assert check_coaching_fidelity(text, _report(), ITALIAN_MENU) == check_coaching_fidelity(
        text, _report(), ITALIAN_MENU
    )


def test_opponent_attribution_spans_the_whole_sentence() -> None:
    # Regression from the report card: the attribution cue was only looked for in
    # the 45 characters before the move, so this correct coaching was flagged as
    # naming an illegal move — "opponent" sits about 53 characters before "exd4",
    # and exd4 really is a legal Black capture in this position.
    import chess

    from chess_coach.verify import _SAN_RE, _attributed_to_opponent

    fen = "r1b1k1r1/pppp1p1p/8/4p1P1/1b1B4/1P2P3/P1P1B1nP/RN1K3R w q - 0 16"
    board = chess.Board(fen)
    text = "After your move Bc4, your opponent immediately captures your bishop on d4 with exd4, winning a piece."
    hit = next(m for m in _SAN_RE.finditer(text) if m.group(1) == "exd4")
    assert _attributed_to_opponent(text, hit.start(), board)


def test_attribution_does_not_leak_across_sentences() -> None:
    # The other side of the same change: a cue in a PREVIOUS sentence must not
    # excuse a move recommended in this one, or the check stops catching anything.
    import chess

    from chess_coach.verify import _SAN_RE, _attributed_to_opponent

    board = chess.Board("r1b1k1r1/pppp1p1p/8/4p1P1/1b1B4/1P2P3/P1P1B1nP/RN1K3R w q - 0 16")
    text = "Your opponent has ideas on the queenside. You should play exd4 yourself."
    hit = next(m for m in _SAN_RE.finditer(text) if m.group(1) == "exd4")
    assert not _attributed_to_opponent(text, hit.start(), board)


def test_adherence_kinds_do_not_gate_the_send_path() -> None:
    # off_menu and unsound_move measure adherence to OUR "only name sound moves"
    # rule, not truth about the board, and the warn-context guard protecting them
    # is documented as imprecise: a warning phrased AFTER the move ("Nxe4 loses a
    # piece") is not detected and still counts. That pattern is likeliest in
    # exactly the mistake-explanation turns we least want replaced by a template,
    # so they stay reported and un-gated.
    from chess_coach.verify import GATING_VIOLATION_KINDS, gating_violations

    assert "off_menu" not in GATING_VIOLATION_KINDS
    assert "unsound_move" not in GATING_VIOLATION_KINDS
    # And the board-contradiction kinds do gate.
    for kind in ("placement", "piece_type", "illegal_move", "empty_source"):
        assert kind in GATING_VIOLATION_KINDS

    mixed = [
        Violation("off_menu", "Nxe4", "not on the menu"),
        Violation("placement", "king on f2", "f2 is empty"),
    ]
    assert [v.kind for v in gating_violations(mixed)] == ["placement"]


# ---------------------------------------------------------------------------
# Ownership: whose piece is it? Invisible to the placement check.
# ---------------------------------------------------------------------------

# v27 ply 44. White to move (so the student is White); the bishop on b4 is BLACK's.
# The coach wrote "an immediate threat to your own bishop on b4" and every existing
# check passed it, because a bishop really is on b4 and really is a bishop.
OWNERSHIP_FEN = "r1b5/ppppkp1p/8/8/1bPP3P/5K2/P1r5/RN4R1 w - - 2 23"


def test_opponent_piece_called_the_students_own_is_flagged() -> None:
    text = "Your move c5 overlooked an immediate threat to your own bishop on b4."
    v = check_coaching_fidelity(text, _report(OWNERSHIP_FEN), [])
    assert "ownership" in _kinds(v)
    detail = next(x.detail for x in v if x.kind == "ownership")
    assert "opponent's" in detail


def test_correct_owner_is_not_flagged() -> None:
    text = "a3 attacks their undefended bishop on b4."
    v = check_coaching_fidelity(text, _report(OWNERSHIP_FEN), [])
    assert "ownership" not in _kinds(v)


def test_students_own_piece_correctly_claimed_is_not_flagged() -> None:
    # The c4 pawn IS White's, and White is to move.
    text = "Your pawn on c4 is doing useful work in the centre."
    v = check_coaching_fidelity(text, _report(OWNERSHIP_FEN), [])
    assert "ownership" not in _kinds(v)


def test_unowned_reference_is_not_flagged() -> None:
    # "the" asserts no owner, so there is nothing to contradict.
    text = "The bishop on b4 is undefended."
    v = check_coaching_fidelity(text, _report(OWNERSHIP_FEN), [])
    assert "ownership" not in _kinds(v)


def test_ownership_defers_to_placement_on_an_empty_square() -> None:
    # One mistake must not be counted twice: if the square is empty or holds another
    # piece type, that is a placement error and placement reports it.
    text = "Your queen on b4 is in danger."
    v = check_coaching_fidelity(text, _report(OWNERSHIP_FEN), [])
    assert "placement" in _kinds(v)
    assert "ownership" not in _kinds(v)


def test_ownership_gates_the_send_path() -> None:
    from chess_coach.verify import GATING_VIOLATION_KINDS

    assert "ownership" in GATING_VIOLATION_KINDS


# ---------------------------------------------------------------------------
# Relation claims: does that piece actually defend that square?
# ---------------------------------------------------------------------------
#
# The third class of falsehood found in three review rounds, after the wrong
# captured piece and the wrong owner. One check for the family rather than a fourth
# special case: all three assert a relation between a piece and a square, and the
# board settles all three.

# v28 ply 26. White to move; a white pawn sits on g2 and the king is on d1.
RELATION_FEN = "r1b1k1r1/pppp1p1p/4p3/6P1/1bB4n/1P2P3/PBP3PP/RN1K3R w q - 1 14"
# v28 ply 1002. White Kf2, pawn d5, black king f7.
ENDGAME_RELATION_FEN = "8/5k2/8/3P4/8/8/5K2/8 w - - 0 1"


def test_king_cannot_defend_a_square_it_does_not_touch() -> None:
    # Real v28 text. A king on e2 covers f2, never g2 — false by geometry alone,
    # which is what makes it safe to check: no blocker, turn or move-choice
    # assumption can make it true.
    text = (
        "The best choice was Ke2, improving king safety by repositioning it. "
        "The king is currently exposed, and moving it to e2 helps protect your pawn on g2."
    )
    v = check_coaching_fidelity(text, _report(RELATION_FEN), [])
    assert "relation" in _kinds(v)
    detail = next(x.detail for x in v if x.kind == "relation")
    assert "can never defend g2" in detail


def test_relation_resolves_a_defender_named_in_an_earlier_sentence() -> None:
    # Real v28 text: the piece is named in one sentence and the claim made in the
    # next ("Your move Ke3 is sound… It supports your passed pawn on d5").
    text = "Your move Ke3 is sound and helps control the center. It supports your passed pawn on d5."
    v = check_coaching_fidelity(text, _report(ENDGAME_RELATION_FEN), [])
    assert "relation" in _kinds(v)


def test_true_defence_claims_are_not_flagged() -> None:
    # All four true claims from the same transcript must stay clean, or the check
    # would replace good coaching with a template.
    for text, fen in (
        ("The best move was Ke2, which adds a defender to your pawn on e3.", RELATION_FEN),
        ("The better move is Ke3, which defends your pawn on d4.", "8/4k3/8/8/3P4/8/5K2/8 w - - 0 40"),
        (
            "The better move was Kf4, advancing your king to support the passed pawn on e4.",
            "8/4k3/8/8/4P3/8/5K2/8 w - - 0 40",
        ),
    ):
        v = check_coaching_fidelity(text, _report(fen), [])
        assert "relation" not in _kinds(v), text


def test_relation_stays_silent_without_a_named_defender() -> None:
    # "supports future central control" names no piece and no target square; a claim
    # we cannot pair with a defender is left alone rather than guessed at.
    text = "Your move e3 supports future central control and prepares for development."
    v = check_coaching_fidelity(text, _report(RELATION_FEN), [])
    assert "relation" not in _kinds(v)


def test_relation_defers_to_placement_on_an_empty_target() -> None:
    # An empty target square is a placement error, and placement reports it.
    text = "Ke2 protects your pawn on a5."
    v = check_coaching_fidelity(text, _report(RELATION_FEN), [])
    assert "relation" not in _kinds(v)


def test_relation_gates_the_send_path() -> None:
    from chess_coach.verify import GATING_VIOLATION_KINDS

    assert "relation" in GATING_VIOLATION_KINDS


# ---------------------------------------------------------------------------
# Terminal moves: did the text say the game is over?
# ---------------------------------------------------------------------------

# v29 ply 1003. White to move; Ra8 is checkmate (black king on g8, pawns f7/g7/h7).
MATE_FEN = "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1"


def test_mate_described_as_a_check_is_flagged() -> None:
    # The real v29 text, verbatim. Every other check passed it: the move is legal, the
    # squares are real, the file is genuinely open. It was the last thing the student
    # read, and it told them the game continued.
    text = (
        "Great job with Ra8# — it gives check and takes full advantage of the open a-file. "
        "Next time you see a check that forces a reply, ask yourself: does this move buy "
        "me time to develop or improve another piece?"
    )
    v = check_coaching_fidelity(text, _report(MATE_FEN), [])
    assert "terminal_label" in _kinds(v)
    detail = next(x.detail for x in v if x.kind == "terminal_label")
    assert "checkmate" in detail


def test_mate_named_in_the_prose_is_not_flagged() -> None:
    text = "Ra8 is checkmate — the rook cuts the king off on the back rank and the game is over."
    v = check_coaching_fidelity(text, _report(MATE_FEN), [])
    assert "terminal_label" not in _kinds(v)


def test_notation_alone_does_not_count_as_saying_it() -> None:
    # The `#` is stripped with the move token on purpose: beginners are instructed
    # away from notation, so the sentence has to carry the meaning.
    text = "Great job with Ra8# — it takes full advantage of the open a-file."
    v = check_coaching_fidelity(text, _report(MATE_FEN), [])
    assert "terminal_label" in _kinds(v)


def test_mate_described_without_notation_is_still_flagged() -> None:
    # The real v27 ply-1003 text, which the first version of this check MISSED: it
    # never writes the move down, so there was no token to parse. Prose that avoids
    # notation is exactly what the beginner level asks for, so the check is given the
    # move actually played.
    text = (
        "Great move! You delivered a check with your rook on the open a-file, putting the "
        "king in immediate danger. Next time you see a check that forces an answer, ask "
        "yourself: does it buy me time to develop or improve another piece?"
    )
    from chess_coach.verify import check_text_fidelity

    v = check_text_fidelity(text, MATE_FEN, played_uci="a1a8")
    assert "terminal_label" in [x.kind for x in v]
    # Without the played move there is nothing to resolve, and it stays silent.
    assert "terminal_label" not in [x.kind for x in check_text_fidelity(text, MATE_FEN)]


def test_ordinary_check_is_not_flagged_as_terminal() -> None:
    # Ra8+ style claims on a NON-mating move must stay clean, or every check in the
    # game would be reported as an unlabelled mate.
    fen = "4k3/8/8/8/8/8/8/R3K3 w - - 0 1"
    text = "Ra8 gives check and forces the king to move."
    v = check_coaching_fidelity(text, _report(fen), [])
    assert "terminal_label" not in _kinds(v)


def test_terminal_label_gates_the_send_path() -> None:
    from chess_coach.verify import GATING_VIOLATION_KINDS

    assert "terminal_label" in GATING_VIOLATION_KINDS


# ---------------------------------------------------------------------------
# Intent: the coach is never told WHY the student moved, so it invents it.
# ---------------------------------------------------------------------------

# v29 ply 38. White to move, h4 is a PAWN move, and White has no bishops at all.
INTENT_FEN = "r1b1k3/pppp1p1p/8/6r1/1bPP4/8/P1P1K2P/RN5R w q - 0 20"
# v29 ply 26. Same shape of sentence, but the move really was Bd4 and White has
# bishops on b2 and c4 — this one must stay clean.
INTENT_OK_FEN = "r1b1k1r1/pppp1p1p/4p3/6P1/1bB4n/1P2P3/PBP3PP/RN1K3R w q - 1 14"


def test_intent_naming_a_piece_the_student_lacks_is_flagged() -> None:
    # The real v29 text. Two independent contradictions in one clause: h4 moves a
    # pawn, and there is no bishop to develop.
    text = (
        "Your move, h4, aimed to develop your king's bishop, but the better choice was a3, "
        "which attacks the opponent's undefended bishop on b4."
    )
    from chess_coach.verify import check_text_fidelity

    v = check_text_fidelity(text, INTENT_FEN, played_uci="h2h4")
    kinds = [x.kind for x in v]
    assert "intent" in kinds
    detail = next(x.detail for x in v if x.kind == "intent")
    assert "no bishop" in detail


def test_intent_about_a_different_piece_than_the_one_moved_is_flagged() -> None:
    # Board HAS bishops, so only the move contradicts the claim.
    from chess_coach.verify import check_text_fidelity

    text = "Your move, h3, aimed to develop your bishop."
    v = check_text_fidelity(text, INTENT_OK_FEN, played_uci="h2h3")
    assert "intent" in [x.kind for x in v]
    detail = next(x.detail for x in v if x.kind == "intent")
    assert "moves a pawn, not a bishop" in detail


def test_true_intent_claim_is_not_flagged() -> None:
    # Real v29 ply-26 text: the move WAS Bd4 and White has two bishops.
    from chess_coach.verify import check_text_fidelity

    text = "Your move aimed to develop the bishop, but the stronger choice is Ke2."
    v = check_text_fidelity(text, INTENT_OK_FEN, played_uci="c4d4")
    assert "intent" not in [x.kind for x in v]


def test_vague_intent_is_left_alone() -> None:
    # "aimed to challenge Black's position" names no piece and cannot be checked, so
    # it is not guessed at. Unfalsifiable intent is a teaching problem, not a
    # fidelity one, and belongs in the prompt rather than the gate.
    from chess_coach.verify import check_text_fidelity

    text = "Your move, c5, aimed to challenge Black's position but overlooked a key opportunity."
    v = check_text_fidelity(text, INTENT_FEN, played_uci="c4c5")
    assert "intent" not in [x.kind for x in v]


def test_intent_does_not_bleed_into_the_next_clause() -> None:
    # A false positive this check produced on its first run, caught by sweeping all
    # four stored transcripts: it read "attempt to develop, but Re4 is stronger — it
    # hits the rook on d4" as an intent to develop a ROOK. The rook is the opponent's
    # and the intent clause names no piece at all. The window may not cross a comma.
    from chess_coach.verify import check_text_fidelity

    fen = "4r3/p1p1kpRp/1pp1b3/8/1P1r4/2N2K2/8/4R3 w - - 4 30"
    text = (
        "Your move, Kf2, was a good attempt to develop, but Re4 is stronger — it hits the "
        "rook on d4 and the bishop on e6, giving you a powerful attack."
    )
    v = check_text_fidelity(text, fen, played_uci="f3f2")
    assert "intent" not in [x.kind for x in v]


def test_intent_gates_the_send_path() -> None:
    from chess_coach.verify import GATING_VIOLATION_KINDS

    assert "intent" in GATING_VIOLATION_KINDS


# ---------------------------------------------------------------------------
# Opponent replies: an exemption we created on purpose, then forgot.
# ---------------------------------------------------------------------------
#
# Claims about the opponent's reply were skipped by every check: the illegal-move
# check waives them (they are not legal STUDENT moves) and the capture check waived
# them too. Together that left them entirely unchecked, and the v30 gate fired on two.

# v30 ply 46. White to move; the student plays c6. The engine's line 1 begins 24.a3
# and only THEN Bb7+, which checks along b7-f3 — and c6 is exactly what blocks that
# diagonal. So Bb7+ is a real move in a line that starts differently, and impossible
# after the move actually played.
OPP_ILLEGAL_FEN = "r1b5/p1ppkp1p/1p6/2P5/1b1P3P/5K2/P1r5/RN4R1 w - - 0 24"
# v30 ply 14. White to move; after Ke2 the opponent's Nxc4 takes a BISHOP.
OPP_VICTIM_FEN = "r1bqk2r/pppp1ppp/4p3/4n1N1/1bB2P2/1P2P3/P1P3PP/RNBQK2R w KQkq - 1 8"


def test_opponent_reply_claiming_a_check_that_is_not_one_is_flagged() -> None:
    # The real v30 ply-46 message. Bb7 IS legal after c6 — the falsehood is the "+".
    # The engine's line reaches Bb7+ only after 24.a3; the student's c6 is exactly what
    # blocks the b7-f3 diagonal it would check along.
    #
    # This also pins a regex finding: _SAN_RE drops a trailing +/#, because its closing
    # \b cannot sit between two non-word characters, so "Bb7+," matches as "Bb7". The
    # check marker has to be read from the raw text.
    from chess_coach.verify import check_text_fidelity

    text = "This was a serious mistake. After your move c6, the opponent plays Bb7+, attacking your king."
    v = check_text_fidelity(text, OPP_ILLEGAL_FEN, played_uci="c5c6")
    assert "opponent_reply" in [x.kind for x in v]
    detail = next(x.detail for x in v if x.kind == "opponent_reply")
    assert "does not give check" in detail


def test_genuinely_illegal_opponent_reply_is_flagged() -> None:
    # The other half: a move the opponent cannot make at all.
    from chess_coach.verify import check_text_fidelity

    text = "After your move c6, the opponent plays Qh4, hitting your king."
    v = check_text_fidelity(text, OPP_ILLEGAL_FEN, played_uci="c5c6")
    assert "opponent_reply" in [x.kind for x in v]
    detail = next(x.detail for x in v if x.kind == "opponent_reply")
    assert "cannot play Qh4" in detail


def test_opponent_capture_victim_is_checked() -> None:
    # The real v30 ply-14 message, which contradicts itself: Nxc4 "winning a pawn",
    # and two sentences later "your bishop on c4".
    from chess_coach.verify import check_text_fidelity

    text = (
        "This was a serious mistake. After your move Ke2, the opponent plays Nxc4, winning a pawn "
        "and gaining a strong central presence. The better move is Nd2, which adds a defender to "
        "your bishop on c4."
    )
    v = check_text_fidelity(text, OPP_VICTIM_FEN, played_uci="e1e2")
    assert "opponent_reply" in [x.kind for x in v]
    detail = next(x.detail for x in v if x.kind == "opponent_reply")
    assert "captures a bishop, not a pawn" in detail


def test_correct_opponent_reply_is_not_flagged() -> None:
    # Nxc4 IS available after Ke2 and it does take a bishop; said correctly, clean.
    from chess_coach.verify import check_text_fidelity

    text = "After your move Ke2, the opponent plays Nxc4, capturing your bishop."
    v = check_text_fidelity(text, OPP_VICTIM_FEN, played_uci="e1e2")
    assert "opponent_reply" not in [x.kind for x in v]


def test_opponent_reply_needs_the_played_move() -> None:
    # Without the student's move there is no position to judge against, and guessing
    # one is how the original exemption came about.
    from chess_coach.verify import check_text_fidelity

    text = "After your move c6, the opponent plays Bb7+, attacking your king."
    v = check_text_fidelity(text, OPP_ILLEGAL_FEN)
    assert "opponent_reply" not in [x.kind for x in v]


def test_student_move_is_not_judged_as_an_opponent_reply() -> None:
    # A move the coach recommends to the STUDENT must not be validated against the
    # post-move board, where it is the wrong side's turn.
    from chess_coach.verify import check_text_fidelity

    text = "The better move is Nd2, which adds a defender to your bishop on c4."
    v = check_text_fidelity(text, OPP_VICTIM_FEN, played_uci="e1e2")
    assert "opponent_reply" not in [x.kind for x in v]


def test_opponent_reply_gates_the_send_path() -> None:
    from chess_coach.verify import GATING_VIOLATION_KINDS

    assert "opponent_reply" in GATING_VIOLATION_KINDS


# ---------------------------------------------------------------------------
# Invented attack geometry (v35 ply 60)
# ---------------------------------------------------------------------------
#
# The sixth class of fabrication found by six review rounds, after the wrong captured
# piece, the wrong owner, false defence geometry, mate called a check, invented intent
# and the impossible opponent reply. This one slipped through two guards at once: the
# move was a bare pawn push, so the opponent-reply check skipped it as an ordinary
# square reference, and nothing verified what a reply ATTACKS — only its legality and
# what it captures.
#
# The real position and the real message. Black's a-pawn is on a7, a5 is empty, and a
# pawn arriving on a5 could only ever attack b4 — which holds Black's own rook. The
# coach told the student their rook on e1 was being won.
PLY60_FEN = "4r3/p1p1kpRp/1pp1b3/8/1r6/2N5/5K2/4R3 w - - 0 31"
PLY60_TEXT = (
    "After your move Kf3, the opponent plays a5, attacking your rook on e1 and winning it. "
    "This lets them gain material and improve their position."
)


def test_invented_attack_geometry_is_flagged() -> None:
    from chess_coach.verify import check_text_fidelity, gating_violations

    v = check_text_fidelity(PLY60_TEXT, PLY60_FEN, played_uci="f2f3")
    detail = next((x.detail for x in v if x.kind == "opponent_reply"), "")
    assert "does not attack e1" in detail
    # It must GATE. A confident falsehood about a threat is the case the gate exists
    # for: the student cannot detect it and will act on it.
    assert "opponent_reply" in [x.kind for x in gating_violations(v)]


def test_a_true_attack_claim_is_not_flagged() -> None:
    # The other half, and the one that matters for precision: a reply that really does
    # attack the named piece must pass. Rxh7 lands on h7 and genuinely attacks the
    # pawn on h6 is not available here, so use the rook's own file: after Kf3, Black's
    # rook on b4 really does attack b-file squares. Rb2+ attacks nothing named, so
    # assert on a claim that is true by construction instead.
    from chess_coach.verify import check_text_fidelity

    text = "After your move Kf3, the opponent plays Rb2, attacking your king on f2."
    v = check_text_fidelity(text, PLY60_FEN, played_uci="f2f3")
    # f2 is empty after Kf3, so any complaint here is about placement, not geometry.
    assert not [x for x in v if x.kind == "opponent_reply" and "does not attack" in x.detail]


def test_a_bare_square_reference_is_not_read_as_a_move() -> None:
    # The precision guard on the change that made this check reachable. Bare squares
    # are usually references, not moves — "your pawn on a5" must not be parsed as the
    # opponent playing a5 and then checked for legality or consequence. Only an
    # explicit play verb promotes a bare token to a move.
    from chess_coach.verify import check_text_fidelity

    text = "Your rook on e1 is fine. Their pawn on a7 is undefended, and a5 is a weak square."
    v = check_text_fidelity(text, PLY60_FEN, played_uci="f2f3")
    assert not [x for x in v if x.kind == "opponent_reply"]


def test_attack_claim_about_the_moves_own_square_is_not_flagged() -> None:
    # A piece does not "attack" the square it stands on, but a coach saying the reply
    # lands on a square where a piece sits is describing a capture, not a false
    # geometry claim. Excluded explicitly so the capture wording cannot double-report.
    from chess_coach.verify import check_text_fidelity

    text = "After your move Kf3, the opponent plays Rxg7, attacking your rook on g7."
    v = check_text_fidelity(text, PLY60_FEN, played_uci="f2f3")
    assert not [x for x in v if x.kind == "opponent_reply" and "does not attack" in x.detail]


def test_attack_geometry_check_is_quiet_on_every_stored_transcript() -> None:
    """Precision floor, measured rather than asserted.

    Across the stored report-card runs this fires on exactly one ply — v35's ply 60,
    and the identical error in v33 and v34 — and nowhere else in ~172 coached turns.
    A gating check that replaces real coaching with template text has to earn its
    place on precision, so this is pinned as a property of the checker rather than
    left as a note in a commit message.
    """
    import glob
    import json

    import chess
    import pytest

    from chess_coach.verify import check_text_fidelity

    flagged: list[tuple[str, int]] = []
    coached = 0
    for path in sorted(glob.glob("output/coach_review_v3*/transcript.json")):
        for turn in json.loads(open(path, encoding="utf-8").read())["turns"]:
            text = turn["coach_feedback"]
            if not text.strip():
                continue
            coached += 1
            try:
                uci = chess.Board(turn["fen_before"]).parse_san(turn["student_move_san"]).uci()
            except (ValueError, AssertionError):
                continue
            for viol in check_text_fidelity(text, turn["fen_before"], played_uci=uci):
                if viol.kind == "opponent_reply" and "does not attack" in viol.detail:
                    flagged.append((path, turn["ply"]))

    if not coached:
        pytest.skip("no stored transcripts in this checkout")
    # Every hit must be ply 60 — the one verified defect. A new ply appearing here is
    # either a real new fabrication or a false positive, and both want a human.
    assert all(ply == 60 for _path, ply in flagged), f"unexpected plies flagged: {flagged}"
