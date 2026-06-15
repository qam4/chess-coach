"""Tests for the pedagogy-layer annotation guard (Task 6.4).

The guard's schema / referential-integrity / example-legality checks are
pure logic over structured data, so Hypothesis hammers them at hundreds
of iterations (Properties 11-13). The engine-soundness check (Req 6.4)
is engine-bound: it is covered by a mock-engine unit test (so it runs in
CI without a coaching build) plus an integration test that skips when the
real coaching engine is unavailable. ``scripts/pedagogy_check.py
--with-engine`` performs the real end-to-end check.

Each property is tagged with its design number and the requirements it
validates. Entries are built directly via the dataclasses so ids are
unique by construction.
"""

from __future__ import annotations

import chess
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from chess_coach.models import ComparisonReport
from chess_coach.pedagogy.features import FEATURE_VOCAB
from chess_coach.pedagogy.guard import (
    UNSOUND_CLASSIFICATIONS,
    GuardResult,
    guard_entries,
    validate_entry,
)
from chess_coach.pedagogy.resource import (
    ExamplePosition,
    GuidanceEntry,
    default_resource_path,
    load_resource,
)

# Closed pools that keep generation cheap and inside the defined sets.
_VALID_FEATURES = tuple(sorted(FEATURE_VOCAB))
_VALID_ECOS = ("A00", "B20", "C50", "D30", "E60")
_BAD_FEATURES = ("not_a_feature", "phase:lunch", "tactic:telepathy")
_BAD_ECOS = ("Z99", "C5", "c50", "123", "")
_LEVELS = ("beginner", "intermediate", "advanced")


def _entry(
    idx: int,
    *,
    etype: str = "principle",
    theme: str = "theme",
    focus: str = "focus",
    how_to_apply: str = "apply",
    citation: str = "citation",
    levels: frozenset[str] = frozenset({"beginner"}),
    features: frozenset[str] = frozenset({"phase:opening"}),
    eco_codes: frozenset[str] = frozenset(),
    example: ExamplePosition | None = None,
) -> GuidanceEntry:
    """A guard-valid GuidanceEntry with a unique id (``e{idx}``)."""
    return GuidanceEntry(
        id=f"e{idx}",
        type=etype,
        theme=theme,
        focus=focus,
        how_to_apply=how_to_apply,
        levels=levels,
        features=features,
        eco_codes=eco_codes,
        citation=citation,
        example=example,
    )


# ----------------------------------------------------------- Property 11


@st.composite
def _mixed_batch(draw: st.DrawFn) -> tuple[list[GuidanceEntry], dict[str, tuple[bool, str | None]]]:
    """A batch mixing guard-valid and guard-invalid entries.

    Returns the entries plus, per id, ``(admitted, reason_substring)`` —
    the expectation the guard must meet. Each invalid entry carries
    exactly one defect so the expected reason is unambiguous.
    """
    kinds = draw(
        st.lists(
            st.sampled_from(
                [
                    "valid",
                    "empty_theme",
                    "empty_focus",
                    "empty_how",
                    "empty_citation",
                    "bad_feature",
                    "bad_eco",
                ]
            ),
            min_size=1,
            max_size=8,
        )
    )
    entries: list[GuidanceEntry] = []
    expected: dict[str, tuple[bool, str | None]] = {}
    for idx, kind in enumerate(kinds):
        eid = f"e{idx}"
        if kind == "valid":
            entries.append(_entry(idx))
            expected[eid] = (True, None)
        elif kind == "empty_theme":
            entries.append(_entry(idx, theme="   "))
            expected[eid] = (False, "'theme'")
        elif kind == "empty_focus":
            entries.append(_entry(idx, focus=""))
            expected[eid] = (False, "'focus'")
        elif kind == "empty_how":
            entries.append(_entry(idx, how_to_apply=""))
            expected[eid] = (False, "'how_to_apply'")
        elif kind == "empty_citation":
            entries.append(_entry(idx, citation=""))
            expected[eid] = (False, "'citation'")
        elif kind == "bad_feature":
            bad = draw(st.sampled_from(_BAD_FEATURES))
            entries.append(_entry(idx, features=frozenset({"phase:opening", bad})))
            expected[eid] = (False, "Position_Features outside")
        else:  # bad_eco
            bad = draw(st.sampled_from(_BAD_ECOS))
            entries.append(_entry(idx, etype="plan", features=frozenset(), eco_codes=frozenset({bad})))
            expected[eid] = (False, "ECO")
    return entries, expected


# Feature: pedagogy-layer, Property 11: Guard gate, isolation, fields, and referential integrity
@settings(max_examples=200)
@given(case=_mixed_batch())
def test_property_11_gate_isolation_fields_refs(
    case: tuple[list[GuidanceEntry], dict[str, tuple[bool, str | None]]],
) -> None:
    """Each entry is admitted or rejected independently: a missing/empty
    required field or an out-of-set feature/ECO is rejected with its id
    and a reason, while valid entries are still admitted; only admitted
    entries are returned for the Selector.

    Validates: Requirements 6.1, 6.2, 6.5, 6.6
    """
    entries, expected = case
    admitted, results = guard_entries(entries, engine=None)

    by_id = {r.entry_id: r for r in results}
    # Every entry produces exactly one result, keyed by its own id.
    assert set(by_id) == {e.id for e in entries}
    assert len(results) == len(entries)

    for eid, (want_admitted, reason_substr) in expected.items():
        result = by_id[eid]
        assert result.admitted is want_admitted, f"{eid}: {result.reasons}"
        if want_admitted:
            assert result.reasons == ()
        else:
            joined = " ".join(result.reasons)
            assert result.reasons, f"{eid}: expected a rejection reason"
            assert reason_substr is not None
            assert reason_substr in joined, f"{eid}: {reason_substr!r} not in {joined!r}"

    # Isolation (Req 6.6) + gate (Req 6.1): the admitted subset is exactly
    # the valid entries — a rejected entry never reaches the Selector, and
    # one bad entry never withholds a good one.
    admitted_ids = {e.id for e in admitted}
    valid_ids = {eid for eid, (ok, _) in expected.items() if ok}
    assert admitted_ids == valid_ids


# ----------------------------------------------------------- Property 12


@st.composite
def _board(draw: st.DrawFn) -> chess.Board:
    """A reachable position after 0-6 random legal plies."""
    board = chess.Board()
    for _ in range(draw(st.integers(min_value=0, max_value=6))):
        moves = list(board.legal_moves)
        if not moves:
            break
        board.push(draw(st.sampled_from(moves)))
    return board


@st.composite
def _legal_example(draw: st.DrawFn) -> ExamplePosition:
    board = draw(_board())
    legal = [m.uci() for m in board.legal_moves]
    assume(legal)
    return ExamplePosition(fen=board.fen(), move=draw(st.sampled_from(legal)))


@st.composite
def _illegal_example(draw: st.DrawFn) -> ExamplePosition:
    board = draw(_board())
    squares = [chess.square_name(s) for s in range(64)]
    frm = draw(st.sampled_from(squares))
    to = draw(st.sampled_from(squares))
    assume(frm != to)
    move = chess.Move.from_uci(frm + to)
    assume(move not in board.legal_moves)
    return ExamplePosition(fen=board.fen(), move=frm + to)


# Feature: pedagogy-layer, Property 12: Guard verifies example move legality
@settings(max_examples=200)
@given(legal=_legal_example(), illegal=_illegal_example())
def test_property_12_example_move_legality(legal: ExamplePosition, illegal: ExamplePosition) -> None:
    """An entry whose example move is legal is admitted (on the legality
    check); one whose example move is illegal is rejected with a reason.
    The legality check uses python-chess only — no engine.

    Validates: Requirements 6.3
    """
    legal_result = validate_entry(_entry(0, etype="pattern", example=legal), engine=None)
    assert legal_result.admitted, legal_result.reasons

    illegal_result = validate_entry(_entry(1, etype="pattern", example=illegal), engine=None)
    assert not illegal_result.admitted
    assert any("illegal" in r for r in illegal_result.reasons), illegal_result.reasons


# ----------------------------------------------------------- Property 13


# Feature: pedagogy-layer, Property 13: Offline, no-LLM operation
@settings(max_examples=200)
@given(case=_mixed_batch())
def test_property_13_offline_no_llm(
    case: tuple[list[GuidanceEntry], dict[str, tuple[bool, str | None]]],
) -> None:
    """The schema/ref/legality guard completes with NO engine and NO
    network, and is deterministic: two offline runs yield identical
    admissions and identical per-entry results.

    Validates: Requirements 6.7, 7.2, 7.4
    """
    entries, _ = case
    admitted_a, results_a = guard_entries(entries, engine=None)
    admitted_b, results_b = guard_entries(entries, engine=None)

    assert [e.id for e in admitted_a] == [e.id for e in admitted_b]
    assert results_a == results_b
    # No engine was ever supplied, so the run is offline by construction.
    assert all(isinstance(r, GuardResult) for r in results_a)


def test_seed_admitted_offline() -> None:
    """The shipped seed passes the schema/ref/legality guard with no
    engine — every feature reference is in FEATURE_VOCAB, every ECO code
    is well-formed, and the one example move is legal (Req 6.2, 6.3)."""
    resource = load_resource(default_resource_path())
    admitted, results = guard_entries(resource.entries, engine=None)
    rejected = [r for r in results if not r.admitted]
    assert rejected == [], f"seed entries rejected offline: {[(r.entry_id, r.reasons) for r in rejected]}"
    assert len(admitted) == len(resource.entries)


# ------------------------------------------------- engine soundness (mock)


class _StubEngine:
    """Canned-comparison engine stub for the soundness check (Req 6.4).

    Records calls so tests can assert the engine is consulted only for
    present, legal examples.
    """

    def __init__(self, classification: str) -> None:
        self._classification = classification
        self.calls: list[tuple[str, str]] = []

    def get_comparison_report(
        self,
        fen: str,
        user_move: str,
        depth: int | None = None,
        movetime: int | None = None,
    ) -> ComparisonReport:
        self.calls.append((fen, user_move))
        return ComparisonReport(
            fen=fen,
            user_move=user_move,
            user_eval_cp=0,
            best_move=user_move,
            best_eval_cp=0,
            eval_drop_cp=0 if self._classification != "blunder" else 900,
            classification=self._classification,
            nag="!" if self._classification != "blunder" else "??",
            best_move_idea="idea",
            refutation_line=None,
            missed_tactics=[],
            top_lines=[],
            critical_moment=False,
            critical_reason=None,
        )


# A legal mate-in-one: Ra8# (mirrors the seed's back-rank example).
_BACK_RANK = ExamplePosition(fen="6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1", move="a1a8")


def test_soundness_admits_non_blunder_example() -> None:
    """A legal example the engine does not call a blunder is admitted (Req 6.4)."""
    engine = _StubEngine("good")
    result = validate_entry(_entry(0, etype="pattern", example=_BACK_RANK), engine=engine)
    assert result.admitted, result.reasons
    assert engine.calls == [(_BACK_RANK.fen, _BACK_RANK.move)]


def test_soundness_rejects_blunder_example() -> None:
    """A legal example the engine classifies as a blunder is rejected with
    a reason, even though it passes legality (Req 6.4)."""
    engine = _StubEngine("blunder")
    result = validate_entry(_entry(0, etype="pattern", example=_BACK_RANK), engine=engine)
    assert not result.admitted
    assert any("not engine-sound" in r for r in result.reasons), result.reasons


def test_soundness_skipped_for_illegal_example() -> None:
    """An illegal example is rejected on legality and the engine is never
    consulted (no soundness call on an illegal move)."""
    engine = _StubEngine("good")
    illegal = ExamplePosition(fen=chess.Board().fen(), move="e4e6")
    result = validate_entry(_entry(0, etype="pattern", example=illegal), engine=engine)
    assert not result.admitted
    assert any("illegal" in r for r in result.reasons), result.reasons
    assert engine.calls == []


def test_soundness_skipped_when_no_example() -> None:
    """An entry without an example never invokes the engine (Req 6.4 only
    applies where a concrete example exists)."""
    engine = _StubEngine("blunder")
    result = validate_entry(_entry(0), engine=engine)
    assert result.admitted, result.reasons
    assert engine.calls == []


def test_unsound_classifications_constant() -> None:
    """'blunder' is treated as the losing/blunder category (Req 6.4)."""
    assert "blunder" in UNSOUND_CLASSIFICATIONS


def test_seed_examples_engine_sound_integration() -> None:
    """Integration (engine): the seed's example moves are engine-sound.

    Skips when a coaching-capable engine is unavailable, mirroring the
    eval suite — the real check is run by
    ``scripts/pedagogy_check.py --with-engine`` on an engine-capable box.
    """
    try:
        from chess_coach.cli import _resolve_engine_path, load_config
        from chess_coach.engine import CoachingEngine

        config = load_config("config.yaml")
        engine_cfg = config["engine"]
        path = _resolve_engine_path(engine_cfg["path"])
        args = [a for a in engine_cfg.get("args", []) if a != "--xboard"]
        if "--uci" not in args:
            args = ["--uci", *args]
        engine = CoachingEngine(path=path, args=args, coaching_timeout=60.0, ping_timeout=5.0)
        engine.start()
    except Exception as exc:  # noqa: BLE001 - any setup failure => skip
        pytest.skip(f"coaching engine unavailable: {exc}")

    if not engine.coaching_available:
        engine.stop()
        pytest.skip("engine lacks coaching protocol")

    try:
        resource = load_resource(default_resource_path())
        example_entries = [e for e in resource.entries if e.example is not None]
        _admitted, results = guard_entries(example_entries, engine=engine)
        rejected = [(r.entry_id, r.reasons) for r in results if not r.admitted]
        assert rejected == [], f"seed example entries not engine-sound: {rejected}"
    finally:
        engine.stop()
