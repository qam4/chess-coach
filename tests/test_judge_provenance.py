"""The judge's recorded model must be the model that actually answered.

Until 2026-09-21 it was not. The harness passed `--model claude-opus-5` and wrote that into
every ledger row, while kiro-cli 2.22.1 silently ignored the flag and used its `auto` default.
These tests guard the replacement: the agent file pins the model, and the harness refuses to run
when the file and the recorded label disagree.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chess_coach.eval.coach_review import resolve_judge_agent

REPO = Path(__file__).resolve().parent.parent


def _agent(tmp_path: Path, name: str, payload: object) -> Path:
    d = tmp_path / ".kiro" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.json"
    p.write_text(json.dumps(payload) if not isinstance(payload, str) else payload, encoding="utf-8")
    return p


def test_the_committed_judge_agent_pins_the_model_the_harness_records() -> None:
    """Runs against the REAL agent file, so the two cannot drift apart unnoticed."""
    assert resolve_judge_agent("judge-opus5", "claude-opus-5", repo_root=REPO) == "claude-opus-5"


def test_a_mismatch_between_the_agent_and_the_label_is_refused(tmp_path: Path) -> None:
    _agent(tmp_path, "j", {"name": "j", "model": "claude-sonnet-4.6"})
    with pytest.raises(SystemExit) as exc:
        resolve_judge_agent("j", "claude-opus-5", repo_root=tmp_path)
    assert "provenance mismatch" in str(exc.value)


def test_an_agent_with_no_model_is_refused(tmp_path: Path) -> None:
    """Silence here means the run falls back to `auto`, which is the original bug."""
    _agent(tmp_path, "j", {"name": "j"})
    with pytest.raises(SystemExit) as exc:
        resolve_judge_agent("j", "claude-opus-5", repo_root=tmp_path)
    assert "auto" in str(exc.value)


def test_a_missing_agent_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        resolve_judge_agent("nope", "claude-opus-5", repo_root=tmp_path)
    assert "not found" in str(exc.value)


def test_malformed_agent_json_is_refused(tmp_path: Path) -> None:
    _agent(tmp_path, "j", "{not json")
    with pytest.raises(SystemExit) as exc:
        resolve_judge_agent("j", "claude-opus-5", repo_root=tmp_path)
    assert "not valid JSON" in str(exc.value)
