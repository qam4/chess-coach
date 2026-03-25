"""Mobile entrypoint for Chess Coach.

Provides a clean ``start_server()`` function that the Android wrapper
(or any embedded host) calls to boot the FastAPI server.  Avoids the
Click CLI layer — just config path in, blocking server out.

Usage from Android (Chaquopy / embedded Python)::

    from chess_coach.mobile_entry import start_server
    start_server("/data/data/com.example.chesscoachmobile/files/config.yaml", port=8361)
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

import yaml


def _resolve_placeholders(obj: Any, replacements: dict[str, str]) -> Any:
    """Recursively replace ``{KEY}`` placeholders in config string values."""
    if isinstance(obj, str):
        for key, val in replacements.items():
            obj = obj.replace("{" + key + "}", val)
        return obj
    if isinstance(obj, dict):
        return {k: _resolve_placeholders(v, replacements) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_placeholders(v, replacements) for v in obj]
    return obj


def load_mobile_config(config_path: str, app_data_dir: str | None = None) -> dict[str, Any]:
    """Load config YAML and resolve ``{APP_DATA}`` placeholders.

    If *app_data_dir* is not provided, it defaults to the directory
    containing *config_path*.
    """
    p = Path(config_path)
    with open(p) as f:
        cfg: dict[str, Any] = yaml.safe_load(f)

    base = app_data_dir or str(p.parent)
    resolved: dict[str, Any] = _resolve_placeholders(cfg, {"APP_DATA": base})
    return resolved


def start_server(config_path: str, port: int = 8361, app_data_dir: str | None = None) -> None:
    """Start the Chess Coach FastAPI server.  Blocks until shutdown.

    Parameters
    ----------
    config_path:
        Path to the YAML config file (typically ``config.mobile.yaml``
        with ``{APP_DATA}`` placeholders).
    port:
        Localhost port to bind.  Default 8361.
    app_data_dir:
        Base directory for ``{APP_DATA}`` placeholder resolution.
        Defaults to the parent directory of *config_path*.
    """
    import uvicorn

    from chess_coach.cli import _create_engine, _resolve_book_path
    from chess_coach.coach import Coach
    from chess_coach.llm import create_provider
    from chess_coach.web.server import create_app

    cfg = load_mobile_config(config_path, app_data_dir)

    engine_cfg = cfg["engine"]
    llm_cfg = cfg.get("llm", {})
    coaching_cfg = cfg.get("coaching", {})

    # Ensure engine binary is executable
    engine_path = Path(engine_cfg.get("path", ""))
    if engine_path.exists() and not os.access(engine_path, os.X_OK):
        engine_path.chmod(engine_path.stat().st_mode | stat.S_IEXEC)

    engine = _create_engine(engine_cfg)
    engine.start()

    llm = create_provider(provider=llm_cfg.get("provider", "none"))

    coach = Coach(
        engine=engine,
        llm=llm,
        depth=engine_cfg.get("depth", 8),
        top_moves=coaching_cfg.get("top_moves", 3),
        level=coaching_cfg.get("level", "intermediate"),
        template_only=coaching_cfg.get("template_only", True),
        play_elo=engine_cfg.get("play_elo", 1000),
        book_path=_resolve_book_path(engine_cfg),
    )

    app = create_app(coach)

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
