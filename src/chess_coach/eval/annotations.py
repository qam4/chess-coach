"""Benchmark annotation guard.

Compares a position's *structured* ground-truth annotations against
the engine report (the oracle) and reports mismatches. This is the
mechanical defence against the failure we hit live: hand-authored
annotations drifting from what the engine actually says, which
silently scores correct coaching as wrong (Requirement 1.5).

Only engine-verifiable kinds are checked:
- ``eval_direction`` vs the sign of ``eval_cp`` (with the equal band)
- ``hanging_piece`` square vs the report's hanging pieces
- ``tactic`` type vs the report's tactics

``free`` and ``phase`` points are un-checkable here and skipped.
"""

from __future__ import annotations

from ..models import PositionReport
from .benchmark import BenchmarkPosition
from .objective import _engine_direction


def check_position_annotations(position: BenchmarkPosition, report: PositionReport) -> list[str]:
    """Return a list of mismatch messages (empty == annotations agree
    with the engine oracle)."""
    issues: list[str] = []
    engine_dir = _engine_direction(report.eval_cp)
    hanging_squares = {hp.square for side in ("white", "black") for hp in report.hanging_pieces.get(side, [])}
    tactic_types = {t.type for t in report.tactics}

    for pt in position.points:
        if pt.kind == "eval_direction":
            if pt.value != engine_dir:
                issues.append(
                    f"eval_direction: annotated {pt.value!r} but engine says {engine_dir!r} ({report.eval_cp}cp)"
                )
        elif pt.kind == "hanging_piece":
            if pt.value not in hanging_squares:
                found = sorted(hanging_squares) or ["(none)"]
                issues.append(f"hanging_piece: annotated {pt.value!r} but engine hanging = {found}")
        elif pt.kind == "tactic":
            if pt.value not in tactic_types:
                found = sorted(tactic_types) or ["(none)"]
                issues.append(f"tactic: annotated {pt.value!r} but engine tactics = {found}")
        # free / phase: not engine-verifiable here — skip.

    return issues
