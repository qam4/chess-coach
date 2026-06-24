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

import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

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


# --------------------------------------------------- pairwise A/B runner


def run_move_feedback_pairwise(
    scenarios: list[MoveFeedbackScenario],
    engine: "CoachingEngine",
    model: "LLMProvider",
    judge: object,
    resource: "KnowledgeResource",
    *,
    depth: int | None = None,
    multipv: int = 3,
    guidance_max: int = 3,
    temperature: float = 0.0,
    judge_repeats: int = 1,
    rng: random.Random | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> "tuple[PairwiseSummary | None, list[dict[str, object]]]":
    """Run the move-feedback guidance A/B (off vs on) over ``scenarios``.

    For each scenario: get the engine comparison + position report, build the
    move-feedback prompt with guidance OFF and ON, generate both with ``model``,
    and have ``judge`` pick the better feedback ``judge_repeats`` times,
    majority-voted (denoises the judge without inflating n — generation is
    deterministic at ``temperature=0``).

    The caller owns the engine lifecycle (this does not start or stop it) and
    all I/O: pass ``on_progress`` to receive one human-readable line per
    scenario (result or skip reason). Returns ``(summary, records)`` where
    ``summary`` is ``None`` if no comparison produced a decisive result.

    This is the shared implementation behind both
    ``scripts/eval_move_feedback_pairwise.py`` and the model-capability
    profiler's guidance dimension.
    """
    # Imported here (not at module top) to keep the lightweight scenario
    # loader free of the heavier prompt/pedagogy/judge dependency graph.
    from ..pedagogy.selector import guidance_for_position
    from ..prompts import build_rich_move_evaluation_prompt
    from .aggregate import summarize_pairwise
    from .judge import majority_winner, pairwise_compare_move

    rng = rng or random.Random(0)
    winners: list[str] = []
    records: list[dict[str, object]] = []

    def _emit(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    for sc in scenarios:
        try:
            comparison = engine.get_comparison_report(sc.fen, sc.move, depth=depth)
            pos_report = engine.get_position_report(sc.fen, multipv=multipv, depth=depth)
        except Exception as e:
            _emit(f"{sc.id} ({sc.move})... ENGINE SKIP: {e}")
            continue

        guidance = guidance_for_position(resource, pos_report, sc.level, guidance_max)
        prompt_off = build_rich_move_evaluation_prompt(comparison, level=sc.level)
        prompt_on = build_rich_move_evaluation_prompt(comparison, level=sc.level, guidance=guidance)
        try:
            resp_off = model.generate(prompt_off, max_tokens=512, temperature=temperature)
            resp_on = model.generate(prompt_on, max_tokens=512, temperature=temperature)
        except Exception as e:
            _emit(f"{sc.id} ({sc.move})... GEN ERROR: {e}")
            continue

        try:
            votes: list[str] = []
            last_reason = ""
            for _ in range(max(1, judge_repeats)):
                res = pairwise_compare_move(judge, "off", resp_off, "on", resp_on, comparison, sc.level, rng=rng)
                votes.append(res.winner)
                last_reason = res.reason
            winner, vote_counts = majority_winner(votes, "off", "on")
        except Exception as e:
            _emit(f"{sc.id} ({sc.move})... JUDGE ERROR (skipped): {e}")
            continue

        winners.append(winner)
        records.append(
            {
                "id": sc.id,
                "move": sc.move,
                "classification": comparison.classification,
                "winner": winner,
                "votes": vote_counts,
                "reason": last_reason,
            }
        )
        vote_str = ""
        if judge_repeats > 1:
            vote_str = f" [off {vote_counts['off']} / on {vote_counts['on']} / tie {vote_counts['tie']}]"
        _emit(f"{sc.id} ({sc.move})... {winner} ({comparison.classification}){vote_str}")

    summary = summarize_pairwise(winners, "off", "on") if winners else None
    return summary, records


if TYPE_CHECKING:
    from ..engine import CoachingEngine
    from ..llm.base import LLMProvider
    from ..pedagogy.resource import KnowledgeResource
    from .aggregate import PairwiseSummary
