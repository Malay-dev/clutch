"""Clutch CLI — the command-line interface."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from clutch import __version__

app = typer.Typer(
    name="clutch",
    help="Clutch — The AI that won't let you miss what matters.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def init() -> None:
    """Scaffold clutch.yaml and .env.example in the current directory."""
    config_src = Path(__file__).parent.parent.parent / "clutch.yaml"
    env_src = Path(__file__).parent.parent.parent / ".env.example"

    if not Path("clutch.yaml").exists():
        if config_src.exists():
            shutil.copy(config_src, "clutch.yaml")
        else:
            Path("clutch.yaml").write_text(
                "clutch:\n  schedule: '4h'\n  timezone: 'Asia/Kolkata'\n\n"
                "profile:\n  name: User\n  interests: []\n  location: ''\n\n"
                "connectors:\n  rss:\n    enabled: true\n    feeds:\n"
                "      - https://dev.to/feed\n"
            )
        console.print("[green]+ Created clutch.yaml[/green]")
    else:
        console.print("[yellow]clutch.yaml already exists[/yellow]")

    if not Path(".env").exists():
        if env_src.exists():
            shutil.copy(env_src, ".env")
        else:
            Path(".env").write_text("# Fill in your secrets\nOLLAMA_HOST=http://localhost:11434\n")
        console.print("[green]+ Created .env[/green]")
    else:
        console.print("[yellow].env already exists[/yellow]")

    console.print("\n-> Fill in .env, then run: [bold]clutch auth google[/bold]")


@app.command()
def auth(
    service: str = typer.Argument(help="Service to authenticate: google"),
) -> None:
    """Authenticate with a service (e.g., Google Calendar)."""
    if service == "google":
        from clutch.actions.calendar import CalendarManager
        from clutch.config import load_config

        config = load_config()
        cal = CalendarManager(config)
        if cal.authenticate():
            console.print("[green]+ Google Calendar authenticated[/green]")
            cal.ensure_calendar()
            console.print(f"[green]+ Calendar '{config.output.google_calendar.calendar_name}' ready[/green]")
        else:
            console.print("[red]x Authentication failed[/red]")
            raise typer.Exit(1)
    elif service == "test":
        _test_auth()
    else:
        console.print(f"[red]Unknown service: {service}[/red]")
        raise typer.Exit(1)


def _test_auth() -> None:
    """Test all configured connector credentials."""
    from clutch.config import load_config, load_env
    from clutch.pipeline import build_connectors

    config = load_config()
    env = load_env()
    connectors = build_connectors(config, env)

    for connector in connectors:
        ok = asyncio.run(connector.health_check())
        status = "[green]+[/green]" if ok else "[red]x[/red]"
        console.print(f"  {status} {connector.name}")


@app.command()
def run(
    once: bool = typer.Option(False, "--once", help="Run the pipeline once and exit"),
    no_calendar: bool = typer.Option(False, "--no-calendar", help="Skip calendar sync"),
    temporal: bool = typer.Option(False, "--temporal", help="Use Temporal scheduler"),
) -> None:
    """Start the Clutch daemon or run once."""
    from clutch.config import load_config, load_env

    config = load_config()
    env = load_env()

    if once:
        console.print("[bold]Clutch — single run[/bold]\n")
        asyncio.run(
            _run_once(config, env, with_calendar=not no_calendar)
        )
    elif temporal:
        console.print("[bold]Clutch — Temporal mode[/bold]\n")
        from clutch.scheduler.temporal_worker import start_temporal_worker

        asyncio.run(start_temporal_worker(config))
    else:
        console.print("[bold]Clutch — daemon mode[/bold]\n")
        console.print(f"Schedule: every {config.clutch.schedule}")
        from clutch.scheduler.fallback import run_scheduler

        asyncio.run(run_scheduler(config, env))


async def _run_once(config, env, with_calendar: bool = True) -> None:
    from clutch.engine.scorer import check_ollama
    from clutch.pipeline import run_pipeline

    # Pre-flight checks
    ollama_ok = await check_ollama(config.ollama.host, config.ollama.model)
    if not ollama_ok:
        console.print(
            f"[red]x Ollama not ready. Is it running? Is {config.ollama.model} pulled?[/red]"
        )
        console.print(f"  Try: ollama pull {config.ollama.model}")
        raise typer.Exit(1)
    console.print(f"+ Ollama: {config.ollama.model} ready")

    await run_pipeline(config=config, env=env, with_calendar=with_calendar)


@app.command()
def status() -> None:
    """Show current Clutch status — events, priorities, next run."""
    from clutch.db import get_active_events, get_db
    from clutch.models import Priority

    conn = get_db()
    active = get_active_events(conn)

    critical = [e for e in active if e.priority == Priority.CRITICAL]
    high = [e for e in active if e.priority == Priority.HIGH]
    info = [e for e in active if e.priority == Priority.INFO]

    console.print(f"\n[bold]Clutch Status[/bold]")
    console.print(f"  Active events: {len(active)}")
    console.print(f"  CRITICAL: {len(critical)}")
    console.print(f"  HIGH:     {len(high)}")
    console.print(f"  INFO:     {len(info)}")

    conn.close()


@app.command()
def radar() -> None:
    """Show today's priorities in a table."""
    from clutch.db import get_active_events, get_db

    conn = get_db()
    active = get_active_events(conn)

    if not active:
        console.print("\n[green]All clear — nothing on the radar.[/green]")
        conn.close()
        return

    table = Table(title="Clutch Radar", show_lines=True)
    table.add_column("Priority", width=10)
    table.add_column("Score", width=6)
    table.add_column("Title", width=45)
    table.add_column("Source", width=10)
    table.add_column("Action", width=25)
    table.add_column("Deadline", width=12)

    for se in active[:20]:
        deadline = se.event.deadline.strftime("%b %d") if se.event.deadline else "-"
        table.add_row(
            se.priority.value.upper(),
            f"{se.final_score:.2f}",
            se.event.title[:45],
            se.event.source,
            (se.scoring.action_required or "-")[:25],
            deadline,
        )

    console.print(table)
    conn.close()


@app.command()
def done(
    title: str = typer.Argument(help="Title fragment to match (e.g., 'DevFest')"),
) -> None:
    """Mark events matching a title as done and clear calendar."""
    from clutch.db import get_db, mark_done_by_title

    conn = get_db()
    matched_ids = mark_done_by_title(conn, title)

    if matched_ids:
        console.print(f"[green]+ Marked {len(matched_ids)} event(s) as done[/green]")
        for eid in matched_ids:
            console.print(f"  -> {eid}")
    else:
        console.print(f"[yellow]No active events matching '{title}'[/yellow]")

    conn.close()


@app.command()
def digest() -> None:
    """Generate and display the morning digest."""
    from clutch.actions.digest import generate_digest
    from clutch.config import load_config
    from clutch.db import get_active_events, get_db

    config = load_config()
    conn = get_db()
    active = get_active_events(conn)
    conn.close()

    brief = asyncio.run(generate_digest(active, config))
    console.print(f"\n{brief}\n")


@app.command()
def menubar() -> None:
    """Launch the macOS menu bar app."""
    from clutch.actions.menubar import run_menubar

    console.print("[bold]Starting Clutch menu bar...[/bold]")
    run_menubar()


@app.command()
def version() -> None:
    """Show version."""
    console.print(f"Clutch v{__version__}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
