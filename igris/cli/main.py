"""IGRIS CLI - main entry point."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import click
from rich.console import Console
from rich.logging import RichHandler

from igris.models.config import IgrisConfig

console = Console()


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, console=console)],
    )


@click.group()
@click.option("--project", "-p", default=".", help="Project root directory")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def cli(ctx: click.Context, project: str, verbose: bool) -> None:
    """IGRIS - AI Engineering Agent"""
    ctx.ensure_object(dict)
    setup_logging("DEBUG" if verbose else "INFO")
    ctx.obj["project_root"] = str(Path(project).resolve())
    ctx.obj["config"] = IgrisConfig.load_or_default(project)


@cli.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """Initialize IGRIS in the current project."""
    config = ctx.obj["config"]
    config_path = config.save()
    console.print("[green]IGRIS initialized![/green]")
    console.print(f"Config: {config_path}")
    console.print(f"Project: {config.project_root}")

    for d in [config.tasks_dir, config.reports_dir, config.logs_dir, config.memory_dir]:
        path = Path(config.project_root) / d
        path.mkdir(parents=True, exist_ok=True)
        console.print(f"  Created: {path}")


@cli.command()
@click.option("--max-cycles", "-n", default=10, help="Maximum cycles to run")
@click.pass_context
def run(ctx: click.Context, max_cycles: int) -> None:
    """Run the autonomous loop."""
    from igris.core.autonomous_loop import AutonomousLoop

    config = ctx.obj["config"]
    loop = AutonomousLoop(config)

    console.print("[bold purple]IGRIS[/bold purple] autonomous loop starting...")
    console.print(f"Project: {config.project_root}")
    console.print(f"Max cycles: {max_cycles}")
    console.print(f"Local LLM: {config.local_llm.provider}/{config.local_llm.model}")
    console.print()

    status = asyncio.run(loop.run(max_cycles=max_cycles))

    console.print()
    console.print("[bold]Loop completed[/bold]")
    console.print(f"  Cycles: {status.cycle_count}")
    console.print(f"  Stop reason: {status.stop_reason}")
    if status.errors:
        console.print(f"  [red]Errors: {len(status.errors)}[/red]")


@cli.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=7777, help="Port to bind to")
@click.option("--reload", "do_reload", is_flag=True, default=True, help="Auto-reload on changes (default: on)")
@click.option("--no-reload", "do_reload", is_flag=False, help="Disable auto-reload")
@click.pass_context
def web(ctx: click.Context, host: str, port: int, do_reload: bool) -> None:
    """Start the IGRIS web interface."""
    import uvicorn

    console.print("[bold purple]IGRIS[/bold purple] Web UI starting...")
    console.print(f"Open: [link=http://{host}:{port}]http://{host}:{port}[/link]")
    if do_reload:
        console.print("[dim]Auto-reload attivo — i cambiamenti ai file vengono applicati automaticamente[/dim]")
    console.print()

    uvicorn.run(
        "igris.web.server:create_app",
        host=host,
        port=port,
        reload=do_reload,
        factory=True,
        log_level="info",
    )


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show project status."""
    from igris.layers.context.project_reader import ProjectReader

    config = ctx.obj["config"]
    reader = ProjectReader(config)
    state = reader.read_project_state()

    console.print("[bold purple]IGRIS[/bold purple] Project Status")
    console.print(f"  Project: {state.project_name}")
    console.print(f"  Root: {state.project_root}")
    console.print(f"  Branch: {state.current_branch}")
    console.print(f"  Health: {state.project_health}")
    console.print(f"  Key files: {', '.join(state.key_files)}")
    console.print(f"  Active tasks: {len(state.active_tasks)}")
    console.print(f"  Blocked tasks: {len(state.blocked_tasks)}")
    console.print(f"  Completed tasks: {len(state.completed_tasks)}")

    if state.recent_commits:
        console.print("\n  Recent commits:")
        for c in state.recent_commits[:5]:
            console.print(f"    {c}")


@cli.command()
@click.argument("message")
@click.pass_context
def chat(ctx: click.Context, message: str) -> None:
    """Send a single message to IGRIS (CLI mode)."""
    from igris.core.chat_engine import ChatEngine

    config = ctx.obj["config"]
    engine = ChatEngine(config)
    session = engine.create_session()

    console.print("[bold purple]IGRIS[/bold purple]> Processing...")
    response = asyncio.run(engine.send_message(session.id, message))

    console.print()
    console.print(f"[bold purple]IGRIS[/bold purple]: {response.content}")
    if response.metadata:
        tier = response.metadata.get("tier", "")
        model = response.metadata.get("model", "")
        console.print(f"  [dim]({tier}/{model})[/dim]")


@cli.command()
@click.pass_context
def config(ctx: click.Context) -> None:
    """Show current configuration."""
    cfg = ctx.obj["config"]
    console.print("[bold purple]IGRIS[/bold purple] Configuration")
    console.print(f"  Project: {cfg.project_name}")
    console.print(f"  Root: {cfg.project_root}")
    console.print(f"  Local LLM: {cfg.local_llm.provider}/{cfg.local_llm.model} @ {cfg.local_llm.base_url}")
    console.print(f"  Fallback LLM: {cfg.fallback_llm.provider}/{cfg.fallback_llm.model}")
    console.print(f"  Vast.ai GPU: {cfg.vastai.gpu_type} (max ${cfg.vastai.max_cost_per_hour}/h)")
    console.print(f"  Auto-commit: {cfg.auto_commit}")
    console.print(f"  Auto-push: {cfg.auto_push}")
    console.print(f"  Anti-loop max reps: {cfg.anti_loop.max_family_repetitions}")
    console.print(f"  Max cycles: {cfg.anti_loop.max_total_cycles}")


@cli.command()
@click.pass_context
def diagnose(ctx: click.Context) -> None:
    """Run diagnostics on the project."""
    from igris.layers.context.project_reader import ProjectReader
    from igris.layers.validation.diagnostics import Diagnostics

    config = ctx.obj["config"]
    reader = ProjectReader(config)
    state = reader.read_project_state()

    tasks_dir = Path(config.project_root) / config.tasks_dir
    tasks = []
    if tasks_dir.exists():
        from igris.models.task import Task
        for f in tasks_dir.glob("*.json"):
            try:
                tasks.append(Task.load(f))
            except Exception:
                pass

    diag = Diagnostics()
    results = diag.run_full_diagnostic(state, tasks)

    console.print("[bold purple]IGRIS[/bold purple] Diagnostics")
    if not results:
        console.print("  [green]No issues found[/green]")
    else:
        for r in results:
            color = {"critical": "red", "error": "red", "warning": "yellow"}.get(r.severity, "white")
            console.print(f"  [{color}][{r.severity.upper()}][/{color}] {r.name}: {r.message}")
            if r.suggestion:
                console.print(f"    -> {r.suggestion}")


if __name__ == "__main__":
    cli()
