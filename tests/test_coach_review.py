"""Tests for the coach report-card pure core (eval/coach_review.py)."""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from chess_coach.eval.coach_review import (
    PHASE_ENDGAME,
    PHASE_MIDDLEGAME,
    PHASE_OPENING,
    ReviewStats,
    ReviewTurn,
    aggregate_review,
    build_architecture_review_prompt,
    build_coach_review_prompt,
)

REPO = Path(__file__).resolve().parent.parent


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


def test_aggregate_reports_the_phase_breakdown() -> None:
    turns = [
        _turn(0, PHASE_OPENING, played="Bc4", best="Bc4", feedback="Bc4 eyes the f7 pawn."),
        _turn(2, PHASE_ENDGAME, played="Kg3", best="Kg3", feedback="Focus on king safety.", fidelity={"off_menu": 1}),
    ]
    stats = aggregate_review(turns)
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


def test_aggregate_reports_prompt_magnitude_leaks() -> None:
    # Reads OUR prompt, not the coach's words, so it stays (B-021).
    turns = [
        _turn(1, PHASE_MIDDLEGAME, feedback="There was a stronger move here."),
        _turn(2, PHASE_MIDDLEGAME, feedback="Nd5 hits the bishop."),
    ]
    # One prompt still carrying a magnitude; the other clean.
    turns[0] = dataclasses.replace(turns[0], prompt="Best move: Nd5\nEvaluation drop: 90 centipawns")
    turns[1] = dataclasses.replace(turns[1], prompt="Best move: Nd5")
    stats = aggregate_review(turns)
    assert stats.prompt_magnitude_leaks == 1
    # Survives a serialization round-trip: the from_dict path silently dropped newer fields
    # once already, and a reviewer was then shown 0 for a real number.
    assert ReviewStats.from_dict(stats.to_dict()).prompt_magnitude_leaks == 1


# ---------------------------------------------------------------------------
# B-005: the judge is not handed a repetition number, and is not told to trust one
# ---------------------------------------------------------------------------

#: Committed (`.gitignore` un-ignores report-card transcripts), so this reads the same input on
#: every machine. Seed 23 is the run whose review deferred to the number: "the deterministic 20%
#: concentration figure is the number to trust".
_V54_SEED23 = REPO / "output" / "coach_review_v54_seed23" / "transcript.json"


def _load_rejudge_script():  # type: ignore[no-untyped-def]
    path = REPO / "scripts" / "eval_coach_rejudge.py"
    spec = importlib.util.spec_from_file_location("eval_coach_rejudge", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["eval_coach_rejudge"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.skipif(not _V54_SEED23.exists(), reason="committed v54 seed-23 transcript absent")
def test_no_judge_surface_shows_a_lesson_repetition_figure() -> None:
    """The judge counts repetition itself, from the transcript (owner's ruling, 2026-10-12).

    The line this replaces read "Lesson concentration: 20% of turns close on one of only three
    recurring lessons ... this is measured, so you do not need to count it by hand". All three
    claims in it were false on this transcript: the 20% divided by all 40 turns although 20 were
    silent; the "lessons" were the three commonest content WORDS of the model's last sentence
    (`pawn`, `king`, `passed`); and an alphabetical tie-break dropped `undefended`, so none of the
    four "Next time you see an undefended piece" closings the review was complaining about
    (plies 17, 19, 27, 51) were counted. All five v54 reviews quoted it.

    Three surfaces render the stats block, and two of them read the STORED stats rather than
    recomputing, so every one is built here from the committed transcript: a fresh report card,
    a re-judge through the script's own loader, and an architecture review.
    """
    data = json.loads(_V54_SEED23.read_text(encoding="utf-8"))
    # The stored block predates the change and still carries the old field. That is the point:
    # the re-judge and architecture paths must not render it even when it is present.
    assert "lesson_concentration_rate" in data["stats"]

    rejudge_turns, rejudge_stats = _load_rejudge_script()._load(_V54_SEED23)
    arch_turns = [ReviewTurn(**dict(t)) for t in data["turns"]]
    surfaces = {
        "report card": build_coach_review_prompt(rejudge_turns, aggregate_review(rejudge_turns)),
        "re-judge": build_coach_review_prompt(rejudge_turns, rejudge_stats),
        "architecture review": build_architecture_review_prompt(
            architecture="-",
            constraints="-",
            lever_log="-",
            sample_prompt="-",
            sample_turns=arch_turns[:3],
            stats=ReviewStats.from_dict(data["stats"]),
        ),
    }
    for name, prompt in surfaces.items():
        low = prompt.lower()
        assert "lesson concentration" not in low, f"{name} still shows the lesson-concentration line"
        assert "recurring lessons" not in low, f"{name} still shows the lesson-concentration line"
        assert "count it by hand" not in low, f"{name} still tells the judge not to count"
        # Guard against fixing this by blanking the whole block: the other stats must survive.
        assert "Prompts still containing raw UCI" in prompt, f"{name} lost the rest of the stats block"


# ---------------------------------------------------------------------------
# B-021: the judge is not shown numbers our Python got by matching the coach's words
# ---------------------------------------------------------------------------

_V62_SEED23 = REPO / "output" / "coach_review_v62_seed23" / "transcript.json"

#: The lines removed (owner's approval, 2026-10-19), each computed by matching the coach's words;
#: the checker's violation count renders as two of them, total and by phase. On v62 seed 23 the
#: first read "none" while the judge's claim reading found 2 of the 20 replies false, one of them
#: "allowing Black to capture it with Kf8", which captures nothing.
_WORD_MATCHED_LINES = (
    "Deterministic fidelity violations:",
    "Fidelity by phase:",
    "Turns voicing a board fact we composed",
    "Turns naming a square we never supplied",
    "Recycled phrasing:",
    "Turns grading the move or pricing it",
)

#: Lines that read our own prompt or plain counts, and stay.
_KEPT_LINES = (
    "Coached moves:",
    "Phase coverage:",
    "Move quality (engine):",
    "Empty feedback turns:",
    "Prompts still containing raw UCI (should be 0):",
    "Prompts still containing an eval magnitude (should be 0):",
    "Generation latency (s):",
)


@pytest.mark.skipif(not _V62_SEED23.exists(), reason="committed v62 seed-23 transcript absent")
def test_no_judge_surface_shows_a_number_got_by_matching_the_coachs_words() -> None:
    """Every surface that renders the stats block, including the two that read STORED stats."""
    data = json.loads(_V62_SEED23.read_text(encoding="utf-8"))
    rejudge_turns, rejudge_stats = _load_rejudge_script()._load(_V62_SEED23)
    surfaces = {
        "report card": build_coach_review_prompt(rejudge_turns, aggregate_review(rejudge_turns)),
        "re-judge": build_coach_review_prompt(rejudge_turns, rejudge_stats),
        "architecture review": build_architecture_review_prompt(
            architecture="-",
            constraints="-",
            lever_log="-",
            sample_prompt="-",
            sample_turns=rejudge_turns[:3],
            stats=ReviewStats.from_dict(data["stats"]),
        ),
    }
    for name, prompt in surfaces.items():
        for line in _WORD_MATCHED_LINES:
            assert line not in prompt, f"{name} still shows {line!r}"
        for line in _KEPT_LINES:
            assert line in prompt, f"{name} lost {line!r}, which reads our prompt and stays"
