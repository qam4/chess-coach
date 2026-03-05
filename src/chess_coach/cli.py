"""CLI entry point for chess-coach."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click
import yaml

from chess_coach.coach import Coach
from chess_coach.engine import XboardEngine
from chess_coach.llm import create_provider


def load_config(path: str | Path) -> dict:  # type: ignore[type-arg]
    """Load configuration from YAML file."""
    p = Path(path)
    if not p.exists():
        click.echo(f"Config not found: {p}", err=True)
        sys.exit(1)
    with open(p) as f:
        return yaml.safe_load(f)  # type: ignore[no-any-return]


@click.group()
@click.option("--config", "-c", default="config.yaml", help="Path to config file")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Show timing and debug info")
@click.pass_context
def cli(ctx: click.Context, config: str, verbose: bool) -> None:
    """Chess Coach — engine analysis + LLM explanations."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    if verbose:
        logging.basicConfig(
            level=logging.WARNING,
            format="%(name)s: %(message)s",
            stream=sys.stderr,
        )
        # Enable debug for our modules only
        logging.getLogger("chess_coach").setLevel(logging.DEBUG)


@cli.command()
@click.argument("fen")
@click.option("--depth", "-d", type=int, default=None, help="Override analysis depth")
@click.option(
    "--level",
    "-l",
    type=click.Choice(["beginner", "intermediate", "advanced"]),
    default=None,
    help="Override coaching level",
)
@click.pass_context
def explain(ctx: click.Context, fen: str, depth: int | None, level: str | None) -> None:
    """Explain a chess position given as a FEN string."""
    cfg = load_config(ctx.obj["config_path"])

    engine_cfg = cfg["engine"]
    llm_cfg = cfg["llm"]
    coaching_cfg = cfg.get("coaching", {})

    # Create engine
    engine = XboardEngine(
        path=engine_cfg["path"],
        args=engine_cfg.get("args", []),
    )

    # Create LLM provider
    llm = create_provider(
        provider=llm_cfg["provider"],
        model=llm_cfg["model"],
        base_url=llm_cfg.get("base_url", "http://localhost:11434"),
    )

    # Check LLM availability
    if not llm.is_available():
        click.echo(f"LLM not available ({llm_cfg['provider']}: {llm_cfg['model']})", err=True)
        click.echo("Make sure Ollama is running: ollama serve", err=True)
        sys.exit(1)

    # Create coach
    coach = Coach(
        engine=engine,
        llm=llm,
        depth=depth or engine_cfg.get("depth", 18),
        top_moves=coaching_cfg.get("top_moves", 3),
        level=level or coaching_cfg.get("level", "intermediate"),
        max_tokens=llm_cfg.get("max_tokens", 512),
        temperature=llm_cfg.get("temperature", 0.7),
    )

    try:
        engine.start()
        click.echo("Analyzing position...\n")
        response = coach.explain(fen)

        click.echo("=" * 60)
        click.echo(f"Position: {response.fen}")
        click.echo(f"Best move: {response.best_move}  ({response.score})")
        click.echo("=" * 60)
        click.echo()
        click.echo(response.analysis_text)
        click.echo()
        click.echo("-" * 60)
        click.echo("Coach says:")
        click.echo("-" * 60)
        click.echo(response.coaching_text)
    finally:
        engine.stop()


@cli.command()
@click.pass_context
def check(ctx: click.Context) -> None:
    """Check that the engine and LLM are reachable."""
    cfg = load_config(ctx.obj["config_path"])

    engine_cfg = cfg["engine"]
    llm_cfg = cfg["llm"]

    # Check engine
    click.echo(f"Engine: {engine_cfg['path']}")
    engine_path = Path(engine_cfg["path"])
    if engine_path.exists():
        click.echo("  ✓ Binary found")
    else:
        click.echo("  ✗ Binary not found")

    # Check LLM
    click.echo(f"LLM: {llm_cfg['provider']} / {llm_cfg['model']}")
    llm = create_provider(
        provider=llm_cfg["provider"],
        model=llm_cfg["model"],
        base_url=llm_cfg.get("base_url", "http://localhost:11434"),
    )
    if llm.is_available():
        click.echo("  ✓ Model available")
        click.echo("  Running smoke test (short generation)...")
        ok, msg = llm.smoke_test()
        if ok:
            click.echo(f"  ✓ Generation works: {msg}")
        else:
            click.echo(f"  ✗ Generation failed: {msg}")
    else:
        click.echo("  ✗ Not reachable (is Ollama running?)")


@cli.command()
@click.option("--port", "-p", type=int, default=8000, help="Port to listen on")
@click.pass_context
def serve(ctx: click.Context, port: int) -> None:
    """Start the web UI server."""
    import uvicorn

    from chess_coach.web.server import create_app

    cfg = load_config(ctx.obj["config_path"])

    engine_cfg = cfg["engine"]
    llm_cfg = cfg["llm"]
    coaching_cfg = cfg.get("coaching", {})

    engine = XboardEngine(
        path=engine_cfg["path"],
        args=engine_cfg.get("args", []),
    )

    llm = create_provider(
        provider=llm_cfg["provider"],
        model=llm_cfg["model"],
        base_url=llm_cfg.get("base_url", "http://localhost:11434"),
    )

    coach = Coach(
        engine=engine,
        llm=llm,
        depth=engine_cfg.get("depth", 18),
        top_moves=coaching_cfg.get("top_moves", 3),
        level=coaching_cfg.get("level", "intermediate"),
        max_tokens=llm_cfg.get("max_tokens", 512),
        temperature=llm_cfg.get("temperature", 0.7),
    )

    engine.start()
    app = create_app(coach)

    click.echo(f"Starting Chess Coach on http://localhost:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
