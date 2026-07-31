"""End-to-end game-coaching eval — pure core (game loop + trajectory).

Drives a whole game between two players (injected ``move_fn``) and coaches
the *student* side's moves (injected ``coach_fn``), capturing a serializable
:class:`GameTrajectory`. Pure and I/O-free: the engine, the LLM coach, and
the judge are all injected as callables, so the loop, the trajectory model,
and the aggregation are unit-testable with fakes (no live engine/LLM/judge).

The played game is a *generator* of move-feedback scenarios: each student
move + the coach's feedback on it is one :class:`TurnRecord`, carrying the
engine ground truth so a downstream consumer (the frontier judge, or the
cross-game progress tracker) needs no re-analysis.

See ``.kiro/specs/game-coaching-eval/``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import chess

# (fen, elo) -> chosen move in UCI. The player engine at a set strength.
MoveFn = Callable[[str, int], str]
# (ply, fen_before, student_move_uci) -> a fully-built TurnRecord. The driver
# wires this to Coach.evaluate_move + the engine comparison report + fidelity.
CoachFn = Callable[[int, str, str], "TurnRecord"]


@dataclass(frozen=True)
class TurnRecord:
    """One coached student move + its engine ground truth and coach output."""

    ply: int
    fen_before: str
    student_move: str  # UCI
    engine_best: str  # UCI
    eval_before_cp: int
    eval_after_cp: int
    eval_drop_cp: int
    classification: str  # good | inaccuracy | blunder
    active_features: list[str]  # pedagogy/dimension tags for this position
    coach_feedback: str
    fidelity_kinds: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "ply": self.ply,
            "fen_before": self.fen_before,
            "student_move": self.student_move,
            "engine_best": self.engine_best,
            "eval_before_cp": self.eval_before_cp,
            "eval_after_cp": self.eval_after_cp,
            "eval_drop_cp": self.eval_drop_cp,
            "classification": self.classification,
            "active_features": list(self.active_features),
            "coach_feedback": self.coach_feedback,
            "fidelity_kinds": dict(self.fidelity_kinds),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TurnRecord:
        """Build a TurnRecord from its dict form."""
        return cls(
            ply=d["ply"],
            fen_before=d["fen_before"],
            student_move=d["student_move"],
            engine_best=d["engine_best"],
            eval_before_cp=d["eval_before_cp"],
            eval_after_cp=d["eval_after_cp"],
            eval_drop_cp=d["eval_drop_cp"],
            classification=d["classification"],
            active_features=list(d.get("active_features", [])),
            coach_feedback=d["coach_feedback"],
            fidelity_kinds=dict(d.get("fidelity_kinds", {})),
        )


@dataclass(frozen=True)
class GameTrajectory:
    """A played game reduced to its coached student turns + metadata.

    ``result`` is ``"1-0"``/``"0-1"``/``"1/2-1/2"`` for a finished game,
    ``"ply-cap"`` when the ply cap stopped it, or ``"error"`` when an illegal
    player move / driver error ended it (details in ``issues``).
    """

    meta: dict[str, Any]
    turns: list[TurnRecord]
    result: str
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "meta": dict(self.meta),
            "turns": [t.to_dict() for t in self.turns],
            "result": self.result,
            "issues": list(self.issues),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GameTrajectory:
        """Build a GameTrajectory from its dict form."""
        return cls(
            meta=dict(d.get("meta", {})),
            turns=[TurnRecord.from_dict(t) for t in d.get("turns", [])],
            result=d["result"],
            issues=list(d.get("issues", [])),
        )


def student_moves(traj: GameTrajectory) -> list[tuple[int, str, str]]:
    """``(ply, fen_before, student_move)`` for each coached turn.

    The played game's student moves are exactly move-feedback scenarios; the
    pairwise driver turns these into ``MoveFeedbackScenario``s so a whole game
    feeds the existing pairwise A/B judging over realistic positions.
    """
    return [(t.ply, t.fen_before, t.student_move) for t in traj.turns]


def _result_string(board: chess.Board, ply: int, ply_cap: int) -> str:
    if board.is_game_over(claim_draw=True):
        return board.result(claim_draw=True)
    if ply >= ply_cap:
        return "ply-cap"
    return "*"


def play_game(
    *,
    start_fen: str,
    student_elo: int,
    opponent_elo: int,
    student_is_white: bool,
    ply_cap: int,
    move_fn: MoveFn,
    coach_fn: CoachFn,
    seed: int | None = None,
) -> GameTrajectory:
    """Play a full game and coach the student side's moves.

    Alternates ``move_fn`` for both sides (the mover's Elo passed in), and for
    each *student* move calls ``coach_fn`` to build a :class:`TurnRecord`. Ends
    at game over or ``ply_cap``. An illegal move from a player ends the game
    with ``result="error"`` and a surfaced issue. Pure over the injected
    callables — no engine/LLM/judge import.
    """
    meta: dict[str, Any] = {
        "start_fen": start_fen,
        "student_elo": student_elo,
        "opponent_elo": opponent_elo,
        "student_is_white": student_is_white,
        "ply_cap": ply_cap,
        "seed": seed,
    }
    try:
        board = chess.Board(start_fen)
    except ValueError as exc:
        return GameTrajectory(meta=meta, turns=[], result="error", issues=[f"invalid start FEN: {exc}"])

    turns: list[TurnRecord] = []
    issues: list[str] = []
    ply = 0
    while not board.is_game_over(claim_draw=True) and ply < ply_cap:
        is_student = (board.turn == chess.WHITE) == student_is_white
        elo = student_elo if is_student else opponent_elo
        fen_before = board.fen()

        move_uci = move_fn(fen_before, elo)
        try:
            move = chess.Move.from_uci(move_uci)
        except ValueError:
            move = chess.Move.null()
        if move not in board.legal_moves:
            issues.append(f"ply {ply}: player returned illegal move {move_uci!r} in {fen_before}")
            return GameTrajectory(meta=meta, turns=turns, result="error", issues=issues)

        if is_student:
            turn = coach_fn(ply, fen_before, move_uci)
            turns.append(turn)
            # The coach intentionally stays silent on good moves; empty
            # feedback is only a problem when the move deserved comment.
            if not turn.coach_feedback.strip() and turn.classification != "good":
                issues.append(f"ply {ply}: empty coach feedback on a {turn.classification} ({move_uci})")

        board.push(move)
        ply += 1

    return GameTrajectory(meta=meta, turns=turns, result=_result_string(board, ply, ply_cap), issues=issues)


@dataclass(frozen=True)
class GameReport:
    """Aggregated read of one game's coaching."""

    result: str
    n_turns: int
    judged_n: int
    unjudged_n: int
    mean_quality: float | None  # over judged turns only; None if none judged
    classification_counts: dict[str, int]
    mean_fidelity_violations: float
    issues: list[str]

    def render(self) -> str:
        """Compact text summary."""
        q = f"{self.mean_quality:.2f}" if self.mean_quality is not None else "n/a"
        counts = ", ".join(f"{k}={v}" for k, v in sorted(self.classification_counts.items())) or "none"
        lines = [
            f"Game result: {self.result}  |  coached turns: {self.n_turns} "
            f"(judged {self.judged_n}, un-judged {self.unjudged_n})",
            f"Mean coaching quality: {q}   Moves: {counts}",
            f"Mean fidelity violations/turn: {self.mean_fidelity_violations:.2f}",
        ]
        if self.issues:
            lines.append(f"Issues surfaced ({len(self.issues)}):")
            lines.extend(f"  - {i}" for i in self.issues)
        return "\n".join(lines)


def aggregate(traj: GameTrajectory, verdicts: dict[int, float] | None = None) -> GameReport:
    """Roll a trajectory (+ optional per-ply judge quality scores) into a report.

    ``verdicts`` maps a turn's ``ply`` to its judge quality score; a ply absent
    from it is un-judged. Mean quality is over judged turns only. Fidelity and
    empty-feedback issues are derived from the turns; game-level issues come
    from ``traj.issues``.
    """
    verdicts = verdicts or {}
    turns = traj.turns
    judged = [verdicts[t.ply] for t in turns if t.ply in verdicts]
    class_counts: dict[str, int] = dict(Counter(t.classification for t in turns))
    total_violations = sum(sum(t.fidelity_kinds.values()) for t in turns)
    mean_fid = total_violations / len(turns) if turns else 0.0

    issues = list(traj.issues)
    for t in turns:
        if not t.coach_feedback.strip() and t.classification != "good":
            issues.append(f"ply {t.ply}: empty coach feedback on a {t.classification}")
        for kind in ("illegal_move", "off_menu"):
            if t.fidelity_kinds.get(kind):
                issues.append(f"ply {t.ply}: coach named {t.fidelity_kinds[kind]} {kind} move(s)")

    return GameReport(
        result=traj.result,
        n_turns=len(turns),
        judged_n=len(judged),
        unjudged_n=len(turns) - len(judged),
        mean_quality=round(sum(judged) / len(judged), 4) if judged else None,
        classification_counts=class_counts,
        mean_fidelity_violations=round(mean_fid, 4),
        issues=issues,
    )
