"""No eval magnitude or move grade reaches a coach surface.

Companion to ``test_no_prose_leak.py``, and the same shape of guard for a different
family. That one proves the engine's *prose* is never rendered; this one proves its
*numbers* are not either, nor the verdicts computed from them.

Why it exists as a standing test rather than a one-off assertion: the numbers were
removed because they were measured to be indefensible, not because they read badly.
Blunder's reported cp are not conventional centipawns (``PIECE_VALUE_BONUS`` pawn =
124 midgame, 206 endgame, phase-blended, printed verbatim), and against Stockfish 18
at depth 22 the magnitude carries a signed +122cp error on the turns the coach
actually speaks, with a 50-60cp residual under every conversion tried — wider than
the 50/100 bands the coach was sorting moves into. Ledger rows 56-62.

That argument will still hold after the next prompt refactor, and a number is a
single f-string away from coming back. Two of this project's recorded drops turned
out to be partial (``critical_reason`` live on one path, ``best_move_idea`` live in a
dead template), which is exactly what a cross-surface test catches and a code review
does not.

Scope note: the *debug* trace and the eval harness's judge prompt legitimately carry
raw engine numbers — one is a developer surface, the other hands a frontier judge the
engine's own output. Neither is a coach surface, so neither is checked here.
"""

from __future__ import annotations

import re

import pytest

from chess_coach.coaching_phrases import build_move_menu, describe_eval, describe_move_menu
from chess_coach.coaching_templates import (
    generate_move_coaching,
    generate_position_coaching,
    generate_position_coaching_structured,
)
from chess_coach.models import (
    ComparisonReport,
    EvalBreakdown,
    HangingPiece,
    KingSafety,
    PawnFeatures,
    PositionReport,
    PVLine,
    TacticalMotif,
    Threat,
    ThreatMapEntry,
)
from chess_coach.prompts import (
    build_rich_coaching_prompt,
    build_rich_move_evaluation_prompt,
    build_socratic_prompt,
    compose_safe_move_feedback,
)

FEN = "rnb1kbnr/pppp1ppp/4p3/6q1/4P3/2N5/PPPP1PPP/R1BQKB1R w KQkq - 2 3"

#: Distinctive eval magnitudes. Chosen so a leak is unambiguous: none of these
#: numbers can plausibly arise from a square name, a move number, or a word limit.
_EVAL_CP = 763
_USER_EVAL_CP = -541
_BEST_EVAL_CP = 622
_DROP_CP = 1163
_TERM_CP = 887

#: Any of these in a coach surface means a magnitude or a grade got through.
#: ``\bcp\b`` and the unit words catch a rendered figure; the grade words catch the
#: engine's verdict being relayed or the coach being told to pronounce one.
_BANNED_SUBSTRINGS = (
    "centipawn",
    "evaluation drop",
    "eval drop",
    "classification:",
    "annotation:",
    "overall evaluation",
    "pawns of advantage",
)
_BANNED_PATTERNS = (
    re.compile(r"\bcp\b", re.IGNORECASE),
    re.compile(r"[-+]?\d+\s*cp\b", re.IGNORECASE),
    re.compile(r"\d\.\d\s*pawns?\b", re.IGNORECASE),
)
_MAGNITUDE_NUMBERS = (_EVAL_CP, _USER_EVAL_CP, _BEST_EVAL_CP, _DROP_CP, _TERM_CP)


def _ks(score: int) -> KingSafety:
    return KingSafety(
        score=score,
        description="",
        king_square="g1",
        castling_status="displaced",
        missing_shield_files=["f", "g"],
        open_file_near_king=True,
        pawn_storm=False,
    )


def _report() -> PositionReport:
    empty: dict[str, list[Threat]] = {"white": [], "black": []}
    return PositionReport(
        fen=FEN,
        eval_cp=_EVAL_CP,
        eval_breakdown=EvalBreakdown(
            material=_TERM_CP,
            mobility=_TERM_CP,
            king_safety=_TERM_CP,
            pawn_structure=_TERM_CP,
        ),
        hanging_pieces={"white": [], "black": [HangingPiece("g5", "queen", "black")]},
        threats=dict(empty),
        pawn_structure={
            "white": PawnFeatures(["a"], [], ["e"]),
            "black": PawnFeatures([], ["d"], []),
        },
        king_safety={"white": _ks(-_TERM_CP), "black": _ks(_TERM_CP)},
        top_lines=[
            PVLine(depth=12, eval_cp=_BEST_EVAL_CP, moves=["c3d5"], theme="development"),
            PVLine(depth=12, eval_cp=_USER_EVAL_CP, moves=["d2d4"], theme="central control"),
        ],
        tactics=[TacticalMotif("pin", ["b4", "c3"], ["Bb4", "Nc3"], False, "")],
        threat_map=[
            ThreatMapEntry(
                square="g5",
                piece="queen",
                white_attackers=1,
                black_attackers=0,
                white_defenders=0,
                black_defenders=0,
                net_attacked=True,
            )
        ],
        threat_map_summary=None,
        critical_moment=True,
        critical_reason=f"eval spread between best and 3rd-best line is {_DROP_CP}cp",
    )


def _comparison(drop: int = _DROP_CP) -> ComparisonReport:
    return ComparisonReport(
        fen=FEN,
        user_move="d2d4",
        user_eval_cp=_USER_EVAL_CP,
        best_move="c3d5",
        best_eval_cp=_BEST_EVAL_CP,
        eval_drop_cp=drop,
        classification="blunder",
        nag="??",
        best_move_idea="development — improving piece placement",
        refutation_line=None,
        missed_tactics=[],
        top_lines=[PVLine(depth=12, eval_cp=_BEST_EVAL_CP, moves=["c3d5"], theme="development")],
        critical_moment=True,
        critical_reason=f"eval spread between best and 3rd-best line is {_DROP_CP}cp",
    )


def _coach_surfaces() -> dict[str, str]:
    """Every rendered surface that a prompt or a student can see."""
    report = _report()
    surfaces = {
        "rich_coaching_prompt": build_rich_coaching_prompt(report),
        "socratic_prompt": build_socratic_prompt(report),
        "template_position": generate_position_coaching(report),
        "template_position_structured": "\n".join(s.text for s in generate_position_coaching_structured(report)),
        "move_menu": describe_move_menu(build_move_menu(report)) or "",
        "describe_eval": describe_eval(report),
    }
    # One entry per severity tier: the tiers select different instruction blocks and
    # different fallback openers, so a leak can hide in any one of them.
    for name, drop in (("best", 0), ("equal", 10), ("sound", 40), ("inaccuracy", 80), ("serious", _DROP_CP)):
        report_t = _comparison(drop)
        if name == "best":
            report_t = _comparison(0)
            report_t = ComparisonReport(**{**report_t.__dict__, "user_move": report_t.best_move})
        surfaces[f"move_eval_prompt[{name}]"] = build_rich_move_evaluation_prompt(report_t)
        surfaces[f"template_move[{name}]"] = generate_move_coaching(report_t)
        surfaces[f"composed_fallback[{name}]"] = compose_safe_move_feedback(report_t)
    return surfaces


@pytest.mark.parametrize("name", sorted(_coach_surfaces()))
def test_no_magnitude_or_grade_reaches_a_coach_surface(name: str) -> None:
    output = _coach_surfaces()[name]
    lowered = output.lower()
    for banned in _BANNED_SUBSTRINGS:
        assert banned not in lowered, f"{name}: leaked {banned!r}\n---\n{output}"
    for pattern in _BANNED_PATTERNS:
        found = pattern.search(output)
        assert found is None, f"{name}: leaked magnitude {found.group(0)!r}\n---\n{output}"
    for number in _MAGNITUDE_NUMBERS:
        assert str(number) not in output, f"{name}: leaked the raw figure {number}\n---\n{output}"
        assert f"{number / 100:.1f}" not in output, f"{name}: leaked {number} converted to pawns\n---\n{output}"


def test_surfaces_are_non_trivial() -> None:
    """Guard against a vacuous pass, e.g. every surface returning ''."""
    surfaces = _coach_surfaces()
    for name in (
        "rich_coaching_prompt",
        "move_eval_prompt[serious]",
        "template_position",
        "template_move[serious]",
        "composed_fallback[serious]",
        "move_menu",
        "describe_eval",
    ):
        assert len(surfaces[name]) > 20, f"{name} unexpectedly empty/short: {surfaces[name]!r}"


def test_engine_classification_is_not_relayed_to_the_prompt() -> None:
    """The engine's own verdict must not appear, on any tier.

    Its cut points sit on unnormalized units — it calls a 37cp drop an "inaccuracy",
    which is roughly 18-30 conventional cp, i.e. nothing — and their provenance is
    unknown. The coach's own tier does the framing instead, from bands we own.
    """
    for drop in (0, 10, 40, 80, _DROP_CP):
        prompt = build_rich_move_evaluation_prompt(_comparison(drop))
        lowered = prompt.lower()
        # The relayed FORM, not the bare word: the tier instructions legitimately
        # contain "blunder" in the clause telling the coach not to pronounce one.
        assert "classification: blunder" not in lowered, f"engine verdict relayed at drop={drop}"
        assert "annotation:" not in lowered, f"NAG relayed at drop={drop}"
        assert "??" not in prompt, f"NAG glyph reached the prompt at drop={drop}"


def test_equal_tier_withholds_the_engine_move_itself() -> None:
    """On the no-comparison tiers the alternative is absent, not merely unlabelled.

    Recorded as done in ledger row 28 and it was not: only the achievement line and
    the engine's idea label were withheld, while ``Best move: d4`` stayed in the
    template. The tier instruction then read "Do NOT offer an alternative — there
    isn't one" three lines below a named alternative, which is a negative constraint
    over data we supplied — the one shape this model reliably ignores.

    What this test still owns after B-012 is the TIER: `equal` says the move was as good as
    anything else, which is a different claim from "there was something better and it is
    behind the hint". The withhold itself is now universal and is asserted by
    `test_the_prompt_never_names_the_engines_move_on_a_comparison_tier`.
    """
    equal = _comparison(10)
    prompt = build_rich_move_evaluation_prompt(equal)
    assert "as good as anything else here" in prompt
    assert "Best move:" not in prompt
    assert "Nd5" not in prompt, "the withheld alternative was named anyway"
    # Above the band the framing changes to a comparison — but still no move token. 80cp is
    # past the dubious band with the halved thresholds, so this is the `serious` tier; the
    # cue instruction is what both comparison tiers share.
    above = build_rich_move_evaluation_prompt(_comparison(80))
    assert "as good as anything else here" not in above
    assert "Lead with what went wrong" in above
    assert "Do NOT name a move" in above
    assert "Best move:" not in above
    assert "Nd5" not in above


def test_the_prompt_never_names_the_engines_move_on_a_comparison_tier(repeatable_lesson_comparison) -> None:  # type: ignore[no-untyped-def]
    """B-012: the coaching names the CUE; the move goes behind the hint.

    VISION, settled 2026-09-22: "The coaching names the cue and not the move. A named
    move appears only behind the hint." Measured across 145 stored transcripts, the coach
    names the engine's best move on 2261 spoken turns, and on 1407 of them the move is
    still legal when the student moves again — so it is prospective advice however it is
    phrased.

    This asserts on the PROMPT rather than on the prose, because an instruction not to
    mention something we supplied has never worked on this model while withholding it
    has. It enumerates every offending line, because the sibling test above records a
    withhold that was reported complete while two other renderings still carried the
    move.
    """
    from chess_coach.coaching_phrases import SOUND_MAX_DROP_CP

    # TWO fixtures on purpose. `_comparison` exercises the `Best move:` line and the
    # top-lines section but produces no composed achievement, so on its own it would let a
    # withhold look complete while "The best move (Bc3)" and "Bc3 was stronger here" still
    # carried the token — which is precisely how row 28 came to be retracted by row 64.
    cases: list[tuple[str, object, tuple[str, ...]]] = [
        ("synthetic", _comparison, ("Nd5", "c3d5")),
        ("repeatable-lesson", repeatable_lesson_comparison, ("Bc3", "d4c3")),
    ]
    # Collected across every case rather than asserted per case, so the failure lists all
    # the renderings at once instead of stopping at the first and hiding the rest.
    leaks: list[str] = []
    for name, factory, tokens in cases:
        for drop in (SOUND_MAX_DROP_CP + 1, 80, _DROP_CP):
            prompt = build_rich_move_evaluation_prompt(factory(drop))  # type: ignore[operator]
            leaks += [
                f"{name} drop={drop}cp: {ln.strip()}" for ln in prompt.splitlines() if any(tok in ln for tok in tokens)
            ]
    assert not leaks, "the engine's move reaches the prompt in these places:\n" + "\n".join(
        f"    {leak}" for leak in sorted(set(leaks))
    )


def test_the_better_move_is_available_for_the_hint_on_comparison_tiers(repeatable_lesson_comparison) -> None:  # type: ignore[no-untyped-def]
    """B-012: the move has to land somewhere before it leaves the prose.

    The existing `hint_uci` in `server.py` is the best move to play NEXT, from the PV. The
    move the coaching used to name is retrospective — the better alternative to the move
    just played — and it had no slot. This is that slot, and it deliberately reuses the
    prompt's own tier predicate so the UI cannot offer an alternative on a turn the coach
    is treating as "your move was fine".
    """
    from chess_coach.coaching_phrases import SOUND_MAX_DROP_CP
    from chess_coach.prompts import hint_better_move_san

    # Comparison tiers: the better move is available, in SAN, for the hint.
    for drop in (SOUND_MAX_DROP_CP + 1, 80, _DROP_CP):
        assert hint_better_move_san(_comparison(drop)) == "Nd5", drop
        assert hint_better_move_san(repeatable_lesson_comparison(drop)) == "Bc3", drop

    # No-comparison tiers: nothing to hint, because no alternative is being claimed.
    assert hint_better_move_san(_comparison(10)) == ""

    # And when the student played the engine's move there is no alternative either.
    import dataclasses

    played_best = dataclasses.replace(_comparison(_DROP_CP), user_move="c3d5")
    assert hint_better_move_san(played_best) == ""


def test_no_student_facing_surface_names_the_engines_move(repeatable_lesson_comparison) -> None:  # type: ignore[no-untyped-def]
    """B-012 on the surfaces the student reads, not just the prompt.

    The prompt test above is necessary and not sufficient. When the fidelity gate fires the
    student gets `compose_safe_move_feedback`, and with the LLM off entirely they get
    `generate_move_coaching` — both of which said "Nd5 was stronger here." A withhold that
    covers the prompt and leaves these two is the same shape as ledger row 28, recorded as
    complete and retracted by row 64 when two other renderings turned out to carry the move.
    """
    from chess_coach.coaching_phrases import SOUND_MAX_DROP_CP
    from chess_coach.coaching_templates import generate_move_coaching
    from chess_coach.prompts import compose_safe_move_feedback

    cases = [("synthetic", _comparison, ("Nd5",)), ("repeatable-lesson", repeatable_lesson_comparison, ("Bc3",))]
    leaks: list[str] = []
    for name, factory, tokens in cases:
        for drop in (SOUND_MAX_DROP_CP + 1, 80, _DROP_CP):
            report = factory(drop)  # type: ignore[operator]
            for surface, text in (
                ("compose_safe_move_feedback", compose_safe_move_feedback(report)),
                ("generate_move_coaching", generate_move_coaching(report)),
            ):
                leaks += [
                    f"{name} drop={drop}cp {surface}: {ln.strip()}"
                    for ln in text.splitlines()
                    if any(tok in ln for tok in tokens)
                ]
    assert not leaks, "the engine's move reaches the student here:\n" + "\n".join(
        f"    {leak}" for leak in sorted(set(leaks))
    )


def test_no_instruction_tries_to_arbitrate_between_two_composed_facts(repeatable_lesson_comparison) -> None:  # type: ignore[no-untyped-def]
    """The reverted v59 lever, pinned so it is not rebuilt.

    Withholding the move made the model substitute a different composed fact for the cue
    (cue-voiced 95.9% -> 93.2%, twice the isolated-pawn guidance entry). An instruction
    binding the cue as the subject was the obvious answer and it measured as nothing:
    93.2% -> 93.2%, with `off_menu` 6 -> 10. Both facts are ours, so prompt text cannot
    arbitrate between them — the fix is in selection, which is B-013.
    """
    from chess_coach.coaching_phrases import SOUND_MAX_DROP_CP

    for drop in (SOUND_MAX_DROP_CP + 1, 80, _DROP_CP):
        prompt = build_rich_move_evaluation_prompt(repeatable_lesson_comparison(drop))
        assert "THE SUBJECT OF THIS TURN" not in prompt, drop
        assert "for the CLOSING takeaway only" not in prompt, drop
