"""The register must cover every engine field, or a new one slips in unjudged."""

from __future__ import annotations

import pytest

from chess_coach import engine_trust as et
from chess_coach.models import ComparisonReport, PositionReport


@pytest.mark.parametrize("report_cls", [ComparisonReport, PositionReport])
def test_every_engine_field_has_a_judgement(report_cls: type) -> None:
    """A new engine field cannot arrive without someone recording a verdict.

    This is the whole point of the register: dropping data because we do not trust
    it is fine, forgetting that we dropped it is not. If Blunder grows a field and
    the models follow, this fails until a judgement is written down.
    """
    missing = et.missing_for(report_cls)
    assert not missing, (
        f"no trust judgement recorded for {sorted(missing)}. Add an entry to "
        "chess_coach.engine_trust so the decision is not silently forgotten."
    )


def test_untrusted_fields_name_a_measurable_reinstatement_criterion() -> None:
    """Every drop must say what would make us believe it again."""
    for e in et.with_verdict(et.USED_UNVERIFIED, et.DROPPED, et.DROPPED_PARTIAL):
        assert e.reinstate_when, f"{e.field} has no reinstate_when"
        assert e.evidence, f"{e.field} has no evidence reference"


def test_verdicts_are_known() -> None:
    for e in et.entries():
        assert e.verdict in {
            et.BOARD_TRUTH,
            et.BOARD_VERIFIED,
            et.BOARD_VERIFIABLE,
            et.USED_UNVERIFIED,
            et.DROPPED,
            et.DROPPED_PARTIAL,
        }


def test_bad_verdict_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown verdict"):
        et.FieldTrust(field="X.y", verdict="probably_fine", basis="b", reason="r", evidence="e")


def test_drop_without_reinstatement_criterion_is_rejected() -> None:
    with pytest.raises(ValueError, match="reinstate_when"):
        et.FieldTrust(field="X.y", verdict=et.DROPPED, basis="b", reason="r", evidence="e")


def test_no_partial_drops_remain() -> None:
    """A field dropped on one path and live on another is always a defect.

    This test used to assert the opposite — that ``critical_reason`` and
    ``best_move_idea`` WERE recorded as partial — because both were, and recording
    them was how they stayed visible instead of being rediscovered. Row 63 closed
    both: ``critical_reason`` came off the position prompt (it was already off the
    move prompt), and the dead v1 template that still rendered ``best_move_idea``
    was deleted.

    Inverted rather than deleted, so the register cannot quietly acquire a new
    partial drop. If this fails, a field is being suppressed on one surface and
    rendered on another, and the fix is to pick one.
    """
    partial = et.inconsistent()
    assert not partial, "partial drops must be completed or reversed, not left: " + ", ".join(
        f"{e.field} ({e.reason[:60]}...)" for e in partial
    )


def test_capability_gaps_are_enumerable() -> None:
    """Fields with no compensating source are the engine-work priority queue.

    Asserted non-empty deliberately: today we know of several. When one is closed,
    this test still passes, and when the last one closes the assertion should be
    updated to reflect that genuinely good news.
    """
    gaps = et.capability_gaps()
    assert gaps, "expected known capability gaps to be recorded"
    for e in gaps:
        assert not e.compensated_by


def test_format_report_mentions_every_field() -> None:
    text = et.format_report()
    for e in et.entries():
        assert e.field in text
