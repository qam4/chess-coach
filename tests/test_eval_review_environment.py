"""The transcript's provenance block must record what RAN, not what the config said.

`scripts/eval_coach_review.py` is a script, so it is loaded by path the same way
`test_clause_snapshot.py` reaches its script.

Why this test exists: the first version of `_run_environment` read `config["llm"]`, and a
run launched with `--model gemma4:12b-it-qat` recorded itself as `qwen3:14b` — because
`--model` overrides the config and the config was what got written. It was caught within the
hour, by a multi-model comparison whose two arms both claimed to be the same model. Wrong
provenance is worse than none: the block exists to expose a confound, and it was wearing a
label saying there wasn't one.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
_SCRIPT = REPO / "scripts" / "eval_coach_review.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("eval_coach_review_under_test", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_environment_records_the_model_actually_used_not_the_config() -> None:
    mod = _load()
    # A config that disagrees with the run, which is the whole point of --model.
    engine_cfg = {"path": "does/not/exist/blunder.exe"}

    env = mod._run_environment(
        engine_cfg,
        8,
        model="gemma4:12b-it-qat",
        base_url="http://localhost:11435",
        temperature=0.0,
        seed=13,
    )

    assert env["llm"]["model"] == "gemma4:12b-it-qat"
    assert env["llm"]["base_url"] == "http://localhost:11435"
    assert env["depth"] == 8


def test_environment_records_the_seed_and_the_opening_it_selects() -> None:
    """The seed identifies the GAME, and the game moves the metrics on its own.

    Measured across five openings on one identical build: `cause_given_pct` spans 27 points and
    `spoke` spans 12 turns purely by which opening was played. So two runs on different seeds
    are not comparable, and a run that does not record its seed cannot be placed.
    """
    mod = _load()
    env = mod._run_environment({"path": "nope"}, 8, model="m", base_url="u", temperature=0.0, seed=13)
    assert env["seed"] == 13
    assert env["opening"] == "Queen's Gambit"

    # Seed 7 is the standard start, and the whole historical v-series is seed 7.
    seven = mod._run_environment({"path": "nope"}, 8, model="m", base_url="u", temperature=0.0, seed=7)
    assert seven["opening"] == "standard start"

    # An unknown seed must not claim an opening it did not play.
    other = mod._run_environment({"path": "nope"}, 8, model="m", base_url="u", temperature=0.0, seed=999)
    assert other["seed"] == 999
    assert other["opening"] == "standard start"  # documented fallback in _start_for_seed


def test_environment_records_temperature_from_the_single_source() -> None:
    """Determinism depends on it, so the transcript has to say what it was.

    Pinned against the module constant rather than a literal, so the recorded value cannot
    drift away from the value the coach is actually constructed with.
    """
    mod = _load()
    assert mod._COACH_TEMPERATURE == 0.0
    env = mod._run_environment({"path": "nope"}, 8, model="m", base_url="u", temperature=mod._COACH_TEMPERATURE, seed=7)
    assert env["llm"]["temperature"] == 0.0


def test_environment_never_raises_on_a_missing_engine_binary() -> None:
    """A 20-minute review run must not die over provenance. It records why instead."""
    mod = _load()
    env = mod._run_environment(
        {"path": "definitely/not/here/blunder.exe"}, 8, model="m", base_url="u", temperature=0.0, seed=7
    )
    assert env["engine"]["sha256"] is None
    assert "error" in env["engine"]


def test_environment_does_not_copy_unknown_llm_config_keys() -> None:
    """Only named fields, so a future `api_key` cannot reach a committed artefact."""
    mod = _load()
    env = mod._run_environment({"path": "nope"}, 8, model="m", base_url="u", temperature=0.0, seed=7)
    assert set(env["llm"]) == {"provider", "model", "base_url", "temperature"}
