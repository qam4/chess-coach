"""Tests for scoring + scoreboard + run recording (Task 3)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from chess_coach.eval.objective import ObjectiveResult
from chess_coach.eval.scoring import (
    ResponseEval,
    RunConfig,
    Scoreboard,
    persist_results,
    summarize_model,
)


@dataclass
class _FakeVerdict:
    """Structurally satisfies the _QualityVerdict protocol."""

    quality_score: float


def _obj(
    *,
    factual: float,
    coverage: float = 1.0,
    hallucinations: int = 0,
    illegal: int = 0,
    direction_ok: bool | None = None,
) -> ObjectiveResult:
    return ObjectiveResult(
        hallucinations=["h"] * hallucinations,
        illegal_moves=["i"] * illegal,
        eval_direction_ok=direction_ok,
        coverage_hits=[],
        coverage_total=0 if coverage == 1.0 else 1,
        factual_score=factual,
    )

    # note: coverage_fraction derives from hits/total; we set
    # factual directly for deterministic aggregation tests.


def _ev(
    model: str,
    *,
    factual: float,
    quality: float | None = None,
    latency: float = 1.0,
    words: int = 100,
    error: str | None = None,
) -> ResponseEval:
    return ResponseEval(
        position_id="p",
        model=model,
        response="text",
        word_count=words,
        latency_s=latency,
        objective=_obj(factual=factual),
        judge=_FakeVerdict(quality) if quality is not None else None,
        error=error,
    )


# --------------------------------------------------------------- summarize


def test_summarize_all_pass() -> None:
    evals = [_ev("m", factual=1.0), _ev("m", factual=0.9)]
    s = summarize_model("m", evals)
    assert s.n == 2
    assert s.factual_pass_rate == 1.0
    assert s.factual_mean == 0.95
    assert s.quality_mean is None  # no judge verdicts
    assert s.judged_n == 0


def test_summarize_all_fail() -> None:
    evals = [_ev("m", factual=0.3), _ev("m", factual=0.0)]
    s = summarize_model("m", evals)
    assert s.factual_pass_rate == 0.0
    assert s.factual_mean == 0.15


def test_summarize_with_judge() -> None:
    evals = [_ev("m", factual=1.0, quality=0.8), _ev("m", factual=1.0, quality=0.6)]
    s = summarize_model("m", evals)
    assert s.judged_n == 2
    assert s.quality_mean == 0.7


def test_summarize_mixed_judge_presence() -> None:
    # quality_mean averages only the judged responses.
    evals = [_ev("m", factual=1.0, quality=1.0), _ev("m", factual=1.0)]
    s = summarize_model("m", evals)
    assert s.judged_n == 1
    assert s.quality_mean == 1.0


def test_summarize_counts_errors() -> None:
    evals = [_ev("m", factual=0.0, error="gen failed"), _ev("m", factual=1.0)]
    s = summarize_model("m", evals)
    assert s.errors == 1


# --------------------------------------------------------------- scoreboard


def test_scoreboard_groups_and_orders_by_factual() -> None:
    evals = [
        _ev("weak", factual=0.2),
        _ev("strong", factual=0.95),
        _ev("weak", factual=0.4),
    ]
    sb = Scoreboard.from_response_evals(evals)
    assert [s.model for s in sb.summaries] == ["strong", "weak"]
    assert sb.summaries[0].factual_mean == 0.95


def test_scoreboard_render_runs() -> None:
    evals = [_ev("m", factual=1.0, quality=0.8)]
    text = Scoreboard.from_response_evals(evals).render()
    assert "SCOREBOARD" in text
    assert "m" in text


def test_scoreboard_render_empty() -> None:
    assert Scoreboard.from_response_evals([]).render() == "(no results)"


# --------------------------------------------------------------- run recording


def test_run_config_create_stamps_timestamp() -> None:
    cfg = RunConfig.create(models=["qwen3:8b"], judge_model="fitt-smart", rubric_version="v1")
    assert cfg.models == ["qwen3:8b"]
    assert cfg.judge_model == "fitt-smart"
    assert cfg.rubric_version == "v1"
    assert cfg.benchmark_version >= 1
    assert "T" in cfg.timestamp  # ISO-8601


# P7: run is fully recorded.
def test_persist_records_run_config_and_responses(tmp_path: Path) -> None:
    evals = [_ev("qwen3:8b", factual=1.0, quality=0.8), _ev("qwen3:8b", factual=0.3)]
    sb = Scoreboard.from_response_evals(evals)
    cfg = RunConfig.create(
        models=["qwen3:8b"],
        judge_model="fitt-smart",
        rubric_version="v1",
        benchmark_path="data/eval/positions.yaml",
    )
    results_path, summary_path = persist_results(tmp_path, cfg, evals, sb)

    assert results_path.exists()
    assert summary_path.exists()

    data = json.loads(results_path.read_text(encoding="utf-8"))
    run = data["run"]
    # All required run-config fields present (Property 7).
    assert run["models"] == ["qwen3:8b"]
    assert run["judge_model"] == "fitt-smart"
    assert run["rubric_version"] == "v1"
    assert run["benchmark_version"] >= 1
    assert run["timestamp"]
    # Per-response detail persisted.
    assert len(data["responses"]) == 2
    first = data["responses"][0]
    assert first["model"] == "qwen3:8b"
    assert "objective" in first
    assert "factual_score" in first["objective"]
    # Scoreboard persisted too.
    assert data["scoreboard"]["summaries"]


def test_persist_handles_no_judge(tmp_path: Path) -> None:
    evals = [_ev("m", factual=1.0)]
    sb = Scoreboard.from_response_evals(evals)
    cfg = RunConfig.create(models=["m"])
    results_path, _ = persist_results(tmp_path, cfg, evals, sb)
    data = json.loads(results_path.read_text(encoding="utf-8"))
    assert data["run"]["judge_model"] is None
    assert data["responses"][0]["judge"] is None


def test_summary_txt_is_readable(tmp_path: Path) -> None:
    evals = [_ev("m", factual=1.0)]
    sb = Scoreboard.from_response_evals(evals)
    cfg = RunConfig.create(models=["m"])
    _, summary_path = persist_results(tmp_path, cfg, evals, sb)
    text = summary_path.read_text(encoding="utf-8")
    assert "Models: m" in text
    assert "SCOREBOARD" in text
