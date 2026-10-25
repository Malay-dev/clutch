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
    from clutch.connectors.discovery import build_connectors_from_config

    config = load_config()
    env = load_env()
    connectors = build_connectors_from_config(config, env)

    for connector in connectors:
        ok = asyncio.run(connector.health_check())
        status = "[green]+[/green]" if ok else "[red]x[/red]"
        console.print(f"  {status} {connector.name}")


@app.command()
def run(
    once: bool = typer.Option(False, "--once", help="Run the pipeline once and exit"),
    no_calendar: bool = typer.Option(False, "--no-calendar", help="Skip calendar sync"),
    temporal: bool = typer.Option(False, "--temporal", help="Start Temporal scheduled worker"),
    temporal_once: bool = typer.Option(False, "--temporal-once", help="Run once through Temporal (worker must be running)"),
) -> None:
    """Start the Clutch daemon or run once."""
    from clutch.config import load_config, load_env

    config = load_config()
    env = load_env()

    if temporal:
        console.print("[bold]Clutch — Temporal scheduled mode[/bold]\n")
        from clutch.scheduler.temporal_worker import start_temporal_worker

        asyncio.run(start_temporal_worker(config))
    elif temporal_once:
        console.print("[bold]Clutch — Temporal one-shot mode[/bold]\n")
        from clutch.scheduler.temporal_worker import run_once_temporal

        result = asyncio.run(run_once_temporal(config))
        console.print(f"\nResult: {result}")
    elif once:
        console.print("[bold]Clutch — single run[/bold]\n")
        asyncio.run(
            _run_once(config, env, with_calendar=not no_calendar)
        )
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
    try:
        from clutch.actions.menubar import run_menubar
    except ImportError:
        console.print("[red]Menu bar requires macOS. Install with: pip install clutch[menubar][/red]")
        raise typer.Exit(1)
    console.print("[bold]Starting Clutch menu bar...[/bold]")
    run_menubar()


@app.command()
def setup(
    service: str = typer.Argument(help="Service to set up: google"),
) -> None:
    """Guided setup for external services."""
    if service == "google":
        _setup_google()
    else:
        console.print(f"[red]Unknown service: {service}. Available: google[/red]")
        raise typer.Exit(1)


def _setup_google() -> None:
    """Interactive guided setup for Google Calendar."""
    from pathlib import Path

    creds_path = Path.home() / ".clutch" / "google_credentials.json"

    console.print("\n[bold]Google Calendar Setup[/bold]\n")
    console.print("Clutch needs a Google Cloud OAuth credential to manage your calendar.")
    console.print("You can use any existing Google Cloud project.\n")

    console.print("[bold]Step 1: Pick a Google Cloud project[/bold]")
    console.print("  Open: https://console.cloud.google.com/cloud-resource-manager")
    console.print("  Use any existing project, or create a new one.")
    console.print("")

    console.print("[bold]Step 2: Enable the Calendar API[/bold]")
    console.print("  Open: https://console.cloud.google.com/apis/library/calendar-json.googleapis.com")
    console.print("  Select your project, click ENABLE")
    console.print("")

    console.print("[bold]Step 3: Configure OAuth consent screen[/bold]")
    console.print("  Open: https://console.cloud.google.com/apis/credentials/consent")
    console.print("  User type:     External")
    console.print("  App name:      Clutch")
    console.print("  Scopes:        Add .../auth/calendar")
    console.print("  Test users:    Add your Gmail address")
    console.print("")

    console.print("[bold]Step 4: Create OAuth credentials[/bold]")
    console.print("  Open: https://console.cloud.google.com/apis/credentials")
    console.print("  Click: + CREATE CREDENTIALS > OAuth client ID")
    console.print("  Type:  Desktop app")
    console.print("  Name:  clutch-desktop")
    console.print("  Click: CREATE, then DOWNLOAD JSON")
    console.print("")

    console.print(f"[bold]Step 5: Save the credentials file[/bold]")
    console.print(f"  mkdir -p ~/.clutch")
    console.print(f"  mv ~/Downloads/client_secret_*.json {creds_path}")
    console.print("")
    console.print(f"[bold]Step 6: Authenticate[/bold]")
    console.print(f"  clutch auth google")
    console.print("")

    if creds_path.exists():
        console.print(f"[green]+ Credentials file found at {creds_path}[/green]")
        console.print("Ready to authenticate. Run: [bold]clutch auth google[/bold]")
    else:
        console.print(f"[yellow]Credentials file not found at {creds_path}[/yellow]")
        console.print("Complete the steps above, then run: [bold]clutch auth google[/bold]")


@app.command("connectors")
def list_connectors() -> None:
    """List all discovered connectors (installed plugins)."""
    from clutch.connectors.discovery import list_available_connectors

    connectors = list_available_connectors()
    if not connectors:
        console.print("[yellow]No connectors installed.[/yellow]")
        console.print("  Install one: pip install clutch-connector-rss")
        console.print("  Build your own: see connectors/template/")
        return

    table = Table(title="Installed Connectors", show_lines=False)
    table.add_column("Name", width=12)
    table.add_column("Class", width=25)
    table.add_column("Type", width=10)
    table.add_column("Module", width=40)

    for c in connectors:
        table.add_row(c["name"], c["class"], c["source_type"], c["module"])

    console.print(table)


@app.command()
def escalate(
    title: Optional[str] = typer.Argument(None, help="Title fragment to escalate, or omit for all"),
) -> None:
    """Force-escalate calendar events to show color changes (useful for demos)."""
    from clutch.actions.calendar import CalendarManager, _days_until, _color_for_deadline, _urgency_suffix
    from clutch.config import load_config
    from clutch.db import get_active_events, get_db

    config = load_config()
    conn = get_db()
    active = get_active_events(conn)
    cal_events = [se for se in active if se.calendar_event_id]

    if title:
        cal_events = [se for se in cal_events if title.lower() in se.event.title.lower()]

    if not cal_events:
        console.print("[yellow]No matching calendar events to escalate.[/yellow]")
        conn.close()
        return

    cal = CalendarManager(config)
    cal.authenticate()

    console.print(f"\n[bold]Escalating {len(cal_events)} calendar event(s):[/bold]\n")

    for se in cal_events:
        days = _days_until(se.event.deadline)
        color_name = {
            "9": "Blueberry (blue)",
            "6": "Tangerine (orange)",
            "11": "Tomato (red)",
        }
        new_color = _color_for_deadline(se.event.deadline)
        suffix = _urgency_suffix(se.event.deadline)
        days_str = f"{days}d left" if days is not None and days >= 0 else "past" if days is not None else "no deadline"

        console.print(f"  {se.event.title[:50]}")
        console.print(f"    Deadline: {se.event.deadline.strftime('%b %d') if se.event.deadline else '-'} ({days_str})")
        console.print(f"    Color:    {color_name.get(new_color, new_color)}")
        console.print(f"    Suffix:   {suffix or '(none)'}")

        try:
            cal._update_event(se.calendar_event_id, se)
            console.print(f"    Status:   [green]updated[/green]\n")
        except Exception as e:
            console.print(f"    Status:   [red]failed: {e}[/red]\n")

    conn.close()
    console.print("[bold]Check your Google Calendar to see the color changes.[/bold]")


# ── Sandbox commands ──────────────────────────────────────

sandbox_app = typer.Typer(
    name="sandbox",
    help="Test features without real tokens or API keys.",
    no_args_is_help=True,
)
app.add_typer(sandbox_app, name="sandbox")


@sandbox_app.command("connectors")
def sandbox_connectors(
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Filter by source: discord, rss, luma, jira"),
    count: Optional[int] = typer.Option(None, "--count", "-n", help="Max events to generate"),
) -> None:
    """Generate mock events from fake connectors. No tokens needed."""
    from clutch.sandbox.runner import run_sandbox_connectors

    asyncio.run(run_sandbox_connectors(source_filter=source, count=count))


@sandbox_app.command("score")
def sandbox_score(
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Filter by source"),
    count: Optional[int] = typer.Option(None, "--count", "-n", help="Max events to score"),
) -> None:
    """Score mock events with Gemma. Needs Ollama running, nothing else."""
    from clutch.config import load_config
    from clutch.sandbox.runner import run_sandbox_score

    config = load_config()
    asyncio.run(run_sandbox_score(config=config, source_filter=source, count=count))


@sandbox_app.command("calendar")
def sandbox_calendar(
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Filter by source"),
    count: Optional[int] = typer.Option(None, "--count", "-n", help="Max events"),
) -> None:
    """Full pipeline with dry-run calendar. No Google auth needed."""
    from clutch.config import load_config
    from clutch.sandbox.runner import run_sandbox_calendar

    config = load_config()
    asyncio.run(run_sandbox_calendar(config=config, source_filter=source, count=count))


@sandbox_app.command("full")
def sandbox_full(
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Filter by source"),
    count: Optional[int] = typer.Option(None, "--count", "-n", help="Max events"),
) -> None:
    """Full sandbox pipeline: mock fetch -> Gemma scoring -> dry-run calendar -> SQLite."""
    from clutch.config import load_config
    from clutch.sandbox.runner import run_sandbox_full

    config = load_config()
    asyncio.run(run_sandbox_full(config=config, source_filter=source, count=count))


@app.command()
def version() -> None:
    """Show version."""
    console.print(f"Clutch v{__version__}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
