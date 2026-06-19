"""Move-feedback benchmark: scenarios for evaluating the *step-1* coaching
moment -- feedback on the move a student just played.

The existing benchmark (`benchmark.py` / `positions.yaml`) tests the
position-explanation path ("explain this position"). That is the analyser
path, and pairwise A/Bs showed the pedagogy layer doesn't move it. The
coaching moment that matters most -- and that we had never evaluated -- is
reactive feedback on the student's actual move.

A scenario is deliberately minimal: a position and the move the student
played. The *ground truth* (was it sound? what was better? what idea did it
miss?) is derived from the engine at eval time via
``engine.get_comparison_report(fen, move)`` -- the same oracle the objective
layer trusts -- so there are no hand-authored verdicts to drift (the project
learned that lesson the hard way with mis-annotated positions).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import chess
import yaml


class MoveFeedbackError(ValueError):
    """Raised when a move-feedback scenario file is malformed."""


@dataclass(frozen=True)
class MoveFeedbackScenario:
    """One (position, student-move) coaching scenario.

    ``move`` is the student's move in UCI (e.g. ``"e2e4"``); it must be legal
    in ``fen``. ``level`` selects level-appropriate guidance/feedback. ``note``
    is an optional human hint and is never used for scoring.
    """

    id: str
    fen: str
    move: str
    level: str
    note: str = ""


def default_move_feedback_path() -> Path:
    """Repo path to the move-feedback benchmark file."""
    return Path(__file__).resolve().parents[3] / "data" / "eval" / "move_feedback.yaml"


def load_move_feedback_scenarios(path: str | Path) -> list[MoveFeedbackScenario]:
    """Load and validate move-feedback scenarios.

    Validates that each scenario has the required fields and that ``move`` is
    a legal move in ``fen`` (so a malformed scenario fails loudly here rather
    than producing a junk engine call later). Raises :class:`MoveFeedbackError`
    on any problem.
    """
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MoveFeedbackError(f"cannot read move-feedback file {path}: {exc}") from exc
    if not isinstance(raw, dict) or "scenarios" not in raw:
        raise MoveFeedbackError(f"{path}: top-level 'scenarios' list is required")

    scenarios: list[MoveFeedbackScenario] = []
    seen: set[str] = set()
    for i, item in enumerate(raw["scenarios"] or []):
        if not isinstance(item, dict):
            raise MoveFeedbackError(f"{path}: scenario #{i} is not a mapping")
        for key in ("id", "fen", "move", "level"):
            if not item.get(key):
                raise MoveFeedbackError(f"{path}: scenario #{i} missing required '{key}'")
        sid = str(item["id"])
        if sid in seen:
            raise MoveFeedbackError(f"{path}: duplicate scenario id {sid!r}")
        seen.add(sid)
        fen, move = str(item["fen"]), str(item["move"])
        try:
            board = chess.Board(fen)
        except ValueError as exc:
            raise MoveFeedbackError(f"{path}: scenario {sid!r} has invalid FEN: {exc}") from exc
        try:
            uci = chess.Move.from_uci(move)
        except ValueError as exc:
            raise MoveFeedbackError(f"{path}: scenario {sid!r} move {move!r} is not valid UCI: {exc}") from exc
        if uci not in board.legal_moves:
            raise MoveFeedbackError(f"{path}: scenario {sid!r} move {move!r} is illegal in the given position")
        scenarios.append(
            MoveFeedbackScenario(
                id=sid,
                fen=fen,
                move=move,
                level=str(item["level"]),
                note=str(item.get("note", "")),
            )
        )
    if not scenarios:
        raise MoveFeedbackError(f"{path}: no scenarios found")
    return scenarios
