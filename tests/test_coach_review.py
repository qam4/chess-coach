"""Tests for the coach report-card pure core (eval/coach_review.py)."""

from __future__ import annotations

import pytest

from chess_coach.eval.coach_review import (
    PHASE_ENDGAME,
    PHASE_MIDDLEGAME,
    PHASE_OPENING,
    ReviewTurn,
    aggregate_review,
    build_coach_review_prompt,
)


def _turn(
    ply: int,
    phase: str,
    *,
    played: str = "Nf3",
    best: str = "Nf3",
    classification: str = "good",
    drop: int = 0,
    feedback: str = "Good developing move.",
    latency: float = 10.0,
    fidelity: dict[str, int] | None = None,
) -> ReviewTurn:
    return ReviewTurn(
        ply=ply,
        phase=phase,
        fen_before="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        student_move_san=played,
        best_move_san=best,
        classification=classification,
        eval_drop_cp=drop,
        coach_feedback=feedback,
        latency_s=latency,
        fidelity_kinds=fidelity or {},
    )


def test_aggregate_counts_and_latency() -> None:
    turns = [
        _turn(0, PHASE_OPENING, latency=5.0),
        _turn(2, PHASE_OPENING, classification="inaccuracy", drop=40, latency=15.0, fidelity={"off_menu": 1}),
        _turn(4, PHASE_MIDDLEGAME, classification="blunder", drop=300, latency=25.0, feedback="  "),
        _turn(6, PHASE_ENDGAME, latency=55.0, fidelity={"off_menu": 1, "placement": 2}),
    ]
    stats = aggregate_review(turns)
    assert stats.n_turns == 4
    assert stats.phase_counts == {PHASE_OPENING: 2, PHASE_MIDDLEGAME: 1, PHASE_ENDGAME: 1}
    assert stats.classification_counts == {"good": 2, "inaccuracy": 1, "blunder": 1}
    assert stats.fidelity_totals == {"off_menu": 2, "placement": 2}
    assert stats.empty_feedback == 1  # the "  " feedback
    assert stats.latency_mean_s == 25.0  # (5+15+25+55)/4
    assert stats.latency_max_s == 55.0
    assert stats.latency_mean_s <= stats.latency_p90_s <= stats.latency_max_s


def test_aggregate_reports_rates_and_phase_breakdown() -> None:
    from dataclasses import replace

    turns = [
        replace(
            _turn(0, PHASE_OPENING, played="Bc4", best="Bc4", feedback="Bc4 eyes the f7 pawn."),
            prompt="Best move: Bc4, which pressures f7.",
        ),
        replace(
            _turn(
                2, PHASE_ENDGAME, played="Kg3", best="Kg3", feedback="Focus on king safety.", fidelity={"off_menu": 1}
            ),
            prompt="Best move: Kg3.",
        ),
    ]
    stats = aggregate_review(turns)
    assert stats.composed_fact_rate == 0.5  # only the first names a square we supplied
    assert stats.unsourced_square_rate == 0.0
    assert stats.fidelity_by_phase == {PHASE_ENDGAME: {"off_menu": 1}}


def test_stats_round_trip_keeps_every_metric() -> None:
    # Regression: rebuilding ReviewStats field-by-field at a call site dropped
    # the newer metrics, so a frontier reviewer was told specificity was 0% and
    # made "diagnose the rollback" its top recommendation — chasing a phantom.
    from chess_coach.eval.coach_review import ReviewStats

    turns = [
        _turn(0, PHASE_OPENING, played="Bc4", best="Bc4", feedback="Development: your knight on b1 is home."),
        _turn(2, PHASE_ENDGAME, feedback="Focus on king safety.", fidelity={"off_menu": 1}),
    ]
    original = aggregate_review(turns)
    restored = ReviewStats.from_dict(original.to_dict())
    assert restored.composed_fact_rate == original.composed_fact_rate
    assert restored.unsourced_square_rate == original.unsourced_square_rate
    assert restored.fidelity_by_phase == original.fidelity_by_phase
    assert restored.prompt_uci_leaks == original.prompt_uci_leaks
    assert restored.to_dict() == original.to_dict()


def test_prompt_uci_leak_is_counted() -> None:
    # The second guard for silent SAN fallbacks: surface leakage in the stats we
    # actually read every run (a log warning is not a guard).
    clean = _turn(0, PHASE_OPENING)
    clean = ReviewTurn(**{**clean.__dict__, "prompt": "Best move: Nf3 — Top lines: Nf3 e5"})
    leaky = _turn(2, PHASE_OPENING)
    leaky = ReviewTurn(**{**leaky.__dict__, "prompt": "Top lines: f6g4 f2f4"})
    stats = aggregate_review([clean, leaky])
    assert stats.prompt_uci_leaks == 1


def test_aggregate_empty_is_safe() -> None:
    stats = aggregate_review([])
    assert stats.n_turns == 0
    assert stats.latency_mean_s == 0.0 and stats.latency_max_s == 0.0
    assert stats.phase_counts == {}


def test_architecture_review_prompt_carries_internals_and_ask() -> None:
    from chess_coach.eval.coach_review import build_architecture_review_prompt

    turns = [_turn(0, PHASE_MIDDLEGAME, classification="blunder", drop=600, feedback="Bad move.")]
    prompt = build_architecture_review_prompt(
        architecture="ENGINE -> composers -> one LLM call.",
        constraints="Local models only.",
        lever_log="lever 7 | ordering | REVERTED",
        sample_prompt="SYSTEM: you are a coach ... COACHING INSTRUCTIONS ...",
        sample_turns=turns,
        stats=aggregate_review(turns),
    )
    # Internals the output-only report card never shows the reviewer.
    assert "SYSTEM ARCHITECTURE" in prompt
    assert "ENGINE -> composers -> one LLM call." in prompt
    assert "HARD CONSTRAINTS" in prompt and "Local models only." in prompt
    assert "THE EXACT PROMPT SENT TO THE LOCAL MODEL" in prompt
    assert "COACHING INSTRUCTIONS" in prompt
    assert "REVERTED" in prompt  # lever log, so it won't re-propose failures
    # The design-review ask, not a prose critique.
    assert "FUNDAMENTAL SOUNDNESS" in prompt
    assert "HIGHEST-LEVERAGE DESIGN CHANGES" in prompt
    assert "WHAT TO STOP DOING" in prompt


def test_review_prompt_contains_standard_stats_and_transcript() -> None:
    turns = [
        _turn(0, PHASE_OPENING, played="e4", best="e4", feedback="Great central move."),
        _turn(3, PHASE_MIDDLEGAME, played="Qh5", best="Nc3", classification="mistake", drop=120, feedback="Too early."),
    ]
    stats = aggregate_review(turns)
    prompt = build_coach_review_prompt(turns, stats)
    # Standard + task
    assert "BRIDGE" in prompt
    assert "SCORE: X/10" in prompt
    assert "PHASE FIT" in prompt
    # Stats surfaced
    assert "Generation latency" in prompt
    # Transcript: the best-move-equals-played case is called out; the other names the engine best.
    assert "this IS the engine's top move" in prompt  # e4 == best
    assert "engine best: Nc3" in prompt
    assert "Great central move." in prompt
    assert "Too early." in prompt


def test_rubric_v2_asks_per_category_with_gates() -> None:
    # The single 0-10 defined only its endpoints, so the judge re-anchored the middle
    # every run, and one number over a composite standard averages away a gain in any
    # one part. Rubric v2 scores categories against externally derived anchors and
    # gates on the two failures that make coaching worse than silence.
    turns = [_turn(0, PHASE_OPENING, played="e4", best="e4", feedback="Great central move.")]
    prompt = build_coach_review_prompt(turns, aggregate_review(turns), rubric="v2")
    for category in ("FIDELITY", "DIAGNOSIS", "TRANSFER HANDLE", "STREAM BEHAVIOUR"):
        assert category in prompt
    # Anchors, not just names — the anchors are the fix for the re-anchoring noise.
    assert "caps the overall at 2/10" in prompt
    assert "GATES" in prompt
    # Still asks for a parseable headline so the progression table keeps working.
    assert "SCORE: X/10" in prompt
    # And asks the two questions the old ask never did.
    assert "WHAT HOLDS THE LOWEST TWO CATEGORIES BACK" in prompt
    assert "WHAT TO REMOVE" in prompt


def test_rubric_v1_is_unchanged_and_the_default() -> None:
    # The v1 series has to stay comparable: 15 runs of history are scored under it.
    turns = [_turn(0, PHASE_OPENING, played="e4", best="e4", feedback="Great central move.")]
    stats = aggregate_review(turns)
    assert build_coach_review_prompt(turns, stats) == build_coach_review_prompt(turns, stats, rubric="v1")
    assert "GATES" not in build_coach_review_prompt(turns, stats, rubric="v1")


def test_unknown_rubric_is_rejected() -> None:
    # A silent fallback would record the wrong instrument against a run — the same
    # class of bug as --judge-model and --judge-command disagreeing.
    turns = [_turn(0, PHASE_OPENING, played="e4", best="e4", feedback="ok")]
    with pytest.raises(ValueError, match="unknown rubric"):
        build_coach_review_prompt(turns, aggregate_review(turns), rubric="v3")


def test_square_detection_sees_squares_inside_san_tokens() -> None:
    # Regression: `\b[a-h][1-8]\b` found NO square in "Ra8#", "Rxc8#", "Nf3" or
    # "cxd5" — the leading piece/file letter kills the word boundary. That broke
    # both metrics silently: coaching that named a square only in SAN was scored
    # as naming none, and `is_specific`'s discount set (built from the move SANs)
    # was empty for every piece move, so it discounted nothing and over-credited.
    from chess_coach.eval.coach_review import _SQUARE_RE

    assert _SQUARE_RE.findall("The best move is Ra8#, delivering mate") == ["a8"]
    assert _SQUARE_RE.findall("Rxc8# exploits the back rank") == ["c8"]
    assert _SQUARE_RE.findall("Nf3 develops toward the center") == ["f3"]
    assert _SQUARE_RE.findall("cxd5 wins a pawn") == ["d5"]
    assert _SQUARE_RE.findall("your rook on a1 can move to a8") == ["a1", "a8"]
    assert _SQUARE_RE.findall("e8=Q promotes") == ["e8"]
    # Disambiguated SAN, where a file or rank precedes the destination square.
    # A tighter lookbehind attempt rejected these, which cost 1.1% of all legal
    # moves — and these forms really do occur in the coach's output ("Nfg4",
    # "Rae1+", "Rgg1").
    assert _SQUARE_RE.findall("the opponent plays Nfg4") == ["g4"]
    assert _SQUARE_RE.findall("Rae1+ is a strong choice") == ["e1"]
    assert _SQUARE_RE.findall("R1e2 holds the rank") == ["e2"]
    # Not a square reference: a file name, and the second half of a coordinate
    # pair (so a UCI token still reads as one square, not two).
    assert _SQUARE_RE.findall("the a-file is open") == []
    assert _SQUARE_RE.findall("f6g4") == ["f6"]


def test_square_detection_covers_every_legal_san() -> None:
    # The property the regex has to hold, checked against the move generator
    # rather than against hand-picked strings. Two earlier versions passed
    # eyeball tests and still missed 76.1% and 1.1% of legal moves respectively.
    import chess

    from chess_coach.eval.coach_review import _SQUARE_RE

    board = chess.Board()
    for uci in ("e4", "e5", "Nf3", "Nc6", "Bb5", "Nf6", "d4", "exd4", "e5", "Nd5"):
        board.push_san(uci)
    for move in board.legal_moves:
        san = board.san(move)
        if san.startswith("O-O"):  # castling names no square, by design
            continue
        assert chess.square_name(move.to_square) in _SQUARE_RE.findall(san), san


def test_squares_named_only_by_the_moves_are_discounted() -> None:
    # The point of the discount: repeating the move you were handed says nothing
    # about the position. This could not have passed before the regex fix, because
    # "Ra8#" contributed nothing to either side of the comparison.
    from chess_coach.eval.coach_review import _extra_squares

    echo = _turn(0, PHASE_ENDGAME, played="Rb8", best="Ra8", feedback="Ra8 is better than Rb8.")
    assert _extra_squares(echo) == set()
    beyond = _turn(0, PHASE_ENDGAME, played="Rb8", best="Ra8", feedback="Ra8 mates; your king on g1 is safe.")
    assert _extra_squares(beyond) == {"g1"}


def test_composed_fact_and_unsourced_square_split_specificity() -> None:
    from dataclasses import replace

    from chess_coach.eval.coach_review import names_unsourced_square, voices_composed_fact

    prompt = "Best move: Be2. What the best move achieves: defending your knight on d4."
    # Voicing a square we supplied: the architecture working as intended.
    voiced = _turn(0, PHASE_OPENING, played="Bc4", best="Be2", feedback="Be2 defends your knight on d4.")
    voiced = replace(voiced, prompt=prompt)
    assert voices_composed_fact(voiced)
    assert not names_unsourced_square(voiced)

    # A square we never mentioned: where fabrication would show up.
    invented = _turn(0, PHASE_OPENING, played="Bc4", best="Be2", feedback="Be2 covers the h7 square.")
    invented = replace(invented, prompt=prompt)
    assert names_unsourced_square(invented)
    assert not voices_composed_fact(invented)

    # Echoing only the moves counts as neither.
    echo = _turn(0, PHASE_OPENING, played="Bc4", best="Be2", feedback="Be2 is better than Bc4.")
    echo = replace(echo, prompt=prompt)
    assert not voices_composed_fact(echo)
    assert not names_unsourced_square(echo)

    # No captured prompt means the question cannot be answered, so neither fires.
    assert not voices_composed_fact(_turn(0, PHASE_OPENING, feedback="Be2 defends the knight on d4."))


def test_stats_block_tells_the_reviewer_which_direction_is_good() -> None:
    # Regression: labelled neutrally, "names a square we did not supply: 0%" was
    # read by a frontier reviewer as the coach being blind to the position, and it
    # built its top recommendation on that misreading — when 0% is the intended
    # result. A metric handed over without its sign invites the wrong conclusion.
    from chess_coach.eval.coach_review import build_coach_review_prompt

    turns = [_turn(0, PHASE_OPENING, played="Bc4", best="Bc4", feedback="Bc4 eyes f7.")]
    prompt = build_coach_review_prompt(turns, aggregate_review(turns))
    assert "HIGHER IS BETTER" in prompt
    assert "LOWER IS BETTER" in prompt
    assert "not a weakness" in prompt


def test_recycled_phrasing_is_zero_for_fresh_wording() -> None:
    from chess_coach.eval.coach_review import recycled_phrase_rates

    turns = [
        _turn(0, PHASE_OPENING, feedback="Your knight on b1 has nowhere useful to go yet."),
        _turn(2, PHASE_OPENING, feedback="Trading the bishop pair away hands over long-term pressure."),
        _turn(4, PHASE_OPENING, feedback="A rook belongs behind the passed pawn, escorting it forward."),
    ]
    assert recycled_phrase_rates(turns) == [0.0, 0.0, 0.0]


def test_recycled_phrasing_catches_a_verbatim_repeat() -> None:
    from chess_coach.eval.coach_review import recycled_phrase_rates

    line = "Next time you see an undefended piece, ask yourself whether you can attack it."
    rates = recycled_phrase_rates([_turn(i, PHASE_OPENING, feedback=line) for i in range(3)])
    assert rates[0] == 0.0  # nothing to repeat yet
    assert rates[1] == 1.0  # every phrase seen before
    assert rates[2] == 1.0


def test_recycled_phrasing_is_partial_for_a_shared_template() -> None:
    # The real failure mode: a fresh first clause bolted onto the same closing
    # maxim. Neither 0 nor 1 — it should land in between.
    from chess_coach.eval.coach_review import recycled_phrase_rates

    hook = " Next time you see an undefended piece, ask yourself whether you can attack it first."
    turns = [
        _turn(0, PHASE_OPENING, feedback="Bc4 pressures f7 and opens the way to castle." + hook),
        _turn(2, PHASE_MIDDLEGAME, feedback="Rd1 lines the rook up against the queen on d8." + hook),
    ]
    rate = recycled_phrase_rates(turns)[1]
    assert 0.2 < rate < 0.9, rate


def test_lesson_concentration_is_high_when_the_advice_never_varies() -> None:
    # Same lesson, deliberately REWORDED each time — which is what the model
    # actually does, and why counting distinct closing sentences saw nothing.
    from chess_coach.eval.coach_review import closing_sentence

    turns = [
        _turn(0, PHASE_OPENING, feedback="Fine. Next time you spot an undefended knight, ask if you can hit it."),
        _turn(2, PHASE_OPENING, feedback="Careful. When a bishop is undefended, look for a way to attack it."),
        _turn(4, PHASE_MIDDLEGAME, feedback="Watch out. An undefended rook invites an attack — go after it."),
        _turn(6, PHASE_MIDDLEGAME, feedback="Good. Undefended pieces are targets, so attack the loose one."),
    ]
    assert len({closing_sentence(t) for t in turns}) == 4  # every ending is a different string
    assert aggregate_review(turns).lesson_concentration_rate == 1.0  # and every one is the same lesson


def test_lesson_concentration_falls_when_the_advice_varies() -> None:
    turns = [
        _turn(0, PHASE_OPENING, feedback="Develop both knights before the queen comes out."),
        _turn(2, PHASE_OPENING, feedback="Castle early; the centre is about to open."),
        _turn(4, PHASE_MIDDLEGAME, feedback="Rooks belong on files without pawns."),
        _turn(6, PHASE_MIDDLEGAME, feedback="Trade when you are ahead in material."),
        _turn(8, PHASE_ENDGAME, feedback="Escort the passer with your monarch."),
        _turn(10, PHASE_ENDGAME, feedback="Cut the enemy monarch off along the rank."),
    ]
    assert aggregate_review(turns).lesson_concentration_rate < 0.7


def test_repetition_metrics_survive_the_round_trip() -> None:
    from chess_coach.eval.coach_review import ReviewStats

    hook = "Next time you see an undefended piece, ask yourself whether you can attack it."
    turns = [_turn(i, PHASE_OPENING, feedback=f"Move {i}. {hook}") for i in range(3)]
    original = aggregate_review(turns)
    assert original.recycled_phrase_rate > 0
    restored = ReviewStats.from_dict(original.to_dict())
    # to_dict rounds to 4 decimal places, so the trip is lossy by design.
    assert restored.recycled_phrase_rate == round(original.recycled_phrase_rate, 4)
    assert restored.lesson_concentration_rate == round(original.lesson_concentration_rate, 4)
    assert restored.to_dict() == original.to_dict()
