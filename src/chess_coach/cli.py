"""CLI entry point for chess-coach."""

from __future__ import annotations

import logging
import platform
import sys
import time
from pathlib import Path

import click
import httpx
import yaml
from rich.console import Console
from rich.panel import Panel

from chess_coach.coach import Coach
from chess_coach.engine import EngineProtocol, UciEngine, XboardEngine
from chess_coach.llm import create_provider

console = Console()


def _create_engine(engine_cfg: dict) -> EngineProtocol:  # type: ignore[type-arg]
    """Create the right engine driver based on config protocol setting."""
    protocol = engine_cfg.get("protocol", "xboard")
    path = _resolve_engine_path(engine_cfg["path"])
    args = engine_cfg.get("args", [])

    if protocol == "uci":
        # Filter out --xboard if present (user may have switched protocols)
        args = [a for a in args if a != "--xboard"]
        if "--uci" not in args:
            args = ["--uci"] + args
        return UciEngine(path=path, args=args)

    # Default: xboard
    if "--xboard" not in args:
        args = ["--xboard"] + args
    return XboardEngine(path=path, args=args)


def _resolve_engine_path(path_cfg: str | dict) -> str:  # type: ignore[type-arg]
    """Resolve engine path, supporting per-platform mappings.

    Accepts either a plain string or a dict keyed by platform
    (linux, windows, darwin).  Expands ~ to the user's home directory.
    """
    if isinstance(path_cfg, dict):
        key = platform.system().lower()  # 'linux', 'windows', 'darwin'
        if key not in path_cfg:
            available = ", ".join(path_cfg.keys())
            click.echo(
                f"No engine path for platform '{key}'. Available: {available}",
                err=True,
            )
            sys.exit(1)
        raw = path_cfg[key]
    else:
        raw = path_cfg
    return str(Path(raw).expanduser())


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
    engine = _create_engine(engine_cfg)

    # Create LLM provider
    llm_timeout = float(llm_cfg.get("timeout", 300))
    llm = create_provider(
        provider=llm_cfg["provider"],
        model=llm_cfg["model"],
        base_url=llm_cfg.get("base_url", "http://localhost:11434"),
        timeout=llm_timeout,
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
        with console.status("[bold cyan]Starting engine...", spinner="dots"):
            engine.start()

        t_check = time.perf_counter()
        with console.status("[bold cyan]Checking LLM...", spinner="dots"):
            if not llm.is_available():
                console.print("[red]✗[/] LLM not reachable. Is Ollama running?")
                sys.exit(1)
        elapsed = time.perf_counter() - t_check
        console.print(f"  [green]✓[/] LLM connected ({llm_cfg['model']}) [dim]({elapsed:.1f}s)[/]")

        t_warm = time.perf_counter()
        with console.status(
            "[bold cyan]Warming up model (first call loads into RAM, may take a minute)...",
            spinner="dots",
        ):
            ok, msg = llm.smoke_test()
            if not ok:
                console.print(f"[red]✗[/] LLM smoke test failed: {msg}")
                sys.exit(1)
        console.print(f"  [green]✓[/] Model warm [dim]({time.perf_counter() - t_warm:.1f}s)[/]")

        with console.status("", spinner="dots") as status:

            def _update(msg: str) -> None:
                status.update(f"[bold cyan]{msg}")
                console.log(f"  [dim]{msg}[/]")

            def _debug(step: "TraceStep") -> None:
                status.update(f"[bold cyan]{step.message}")
                elapsed = f" ({step.elapsed_s:.1f}s)" if step.elapsed_s else ""
                console.log(f"  [dim]{step.step}: {step.message}{elapsed}[/]")
                for key, val in step.detail.items():
                    if key == "llm_prompt":
                        console.log(f"    [dim]{key}: ({len(val)} chars)[/]")
                    elif key == "llm_response":
                        console.log(f"    [dim]{key}: ({len(val)} chars)[/]")
                    elif isinstance(val, str) and len(val) > 120:
                        console.log(f"    [dim]{key}: {val[:120]}…[/]")
                    else:
                        console.log(f"    [dim]{key}: {val}[/]")

            try:
                from chess_coach.coach import TraceStep  # noqa: F811

                response = coach.explain(fen, on_progress=_update, on_debug=_debug)
            except httpx.TimeoutException as exc:
                console.print(
                    f"\n[red]✗[/] LLM request timed out after {llm_timeout:.0f}s.\n"
                    f"  The model may be too slow for this prompt length.\n"
                    f"  Try a smaller model or increase llm.timeout in config.yaml.\n"
                    f"  Detail: {exc}"
                )
                sys.exit(1)
            except httpx.HTTPStatusError as exc:
                console.print(
                    f"\n[red]✗[/] LLM returned HTTP {exc.response.status_code}.\n  Detail: {exc}"
                )
                sys.exit(1)
            except httpx.HTTPError as exc:
                console.print(
                    f"\n[red]✗[/] LLM connection error (httpx).\n"
                    f"  Is Ollama still running? Detail: {exc}"
                )
                sys.exit(1)
            except TimeoutError as exc:
                console.print(f"\n[red]✗[/] Engine timed out — it may have hung.\n  Detail: {exc}")
                sys.exit(1)

        console.print()
        console.print(
            Panel(
                response.analysis_text,
                title=f"[bold]Position: {response.fen}[/]",
                subtitle=f"Best move: {response.best_move}  ({response.score})",
                border_style="blue",
            )
        )
        console.print()
        console.print(
            Panel(
                response.coaching_text,
                title="[bold]Coach says[/]",
                border_style="green",
            )
        )
        console.print(
            f"  [dim]Engine: {response.engine_elapsed_s:.1f}s | "
            f"LLM: {response.llm_elapsed_s:.1f}s | "
            f"Total: {response.engine_elapsed_s + response.llm_elapsed_s:.1f}s[/]"
        )
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
    engine_path_str = _resolve_engine_path(engine_cfg["path"])
    click.echo(f"Engine: {engine_path_str}")
    engine_path = Path(engine_path_str)
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
        timeout=float(llm_cfg.get("timeout", 300)),
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

    engine = _create_engine(engine_cfg)

    llm = create_provider(
        provider=llm_cfg["provider"],
        model=llm_cfg["model"],
        base_url=llm_cfg.get("base_url", "http://localhost:11434"),
        timeout=float(llm_cfg.get("timeout", 300)),
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

    # Warm up the LLM model so the first web request isn't slow
    click.echo("Warming up LLM model (first call loads into RAM)...")
    ok, msg = llm.smoke_test()
    if ok:
        click.echo(f"  ✓ Model warm: {msg}")
    else:
        click.echo(f"  ⚠ Warmup failed: {msg} — first request may be slow")

    click.echo(f"Starting Chess Coach on http://localhost:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
