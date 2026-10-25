"""Sandbox pipeline runner — full pipeline with mocks, no tokens needed."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from rich.console import Console

from clutch.config import ClutchConfig, load_config
from clutch.db import (
    event_exists,
    get_db,
    upsert_scored_event,
)
from clutch.engine.scorer import GemmaScorer
from clutch.models import NormalizedEvent, Priority, ScoredEvent
from clutch.sandbox.dry_calendar import DryCalendar
from clutch.sandbox.mock_connectors import MockConnector

console = Console()


async def run_sandbox_connectors(
    source_filter: str | None = None,
    count: int | None = None,
) -> list[NormalizedEvent]:
    """Fetch events from mock connectors and display them."""
    mock = MockConnector(source_filter=source_filter, count=count)
    events = await mock.fetch()

    console.print(f"\n[bold]Mock connector returned {len(events)} events:[/bold]\n")
    for i, ev in enumerate(events, 1):
        deadline_str = ev.deadline.strftime("%b %d") if ev.deadline else "none"
        console.print(
            f"  {i:2d}. [{ev.source:8s}] {ev.title}\n"
            f"      Type: {ev.event_type.value}  "
            f"Deadline: {deadline_str}  "
            f"Location: {ev.location or '-'}"
        )
    return events


async def run_sandbox_score(
    config: Optional[ClutchConfig] = None,
    source_filter: str | None = None,
    count: int | None = None,
) -> list[ScoredEvent]:
    """Score mock events with Gemma. Needs Ollama running, but nothing else."""
    config = config or load_config()

    events = await run_sandbox_connectors(source_filter=source_filter, count=count)
    if not events:
        return []

    console.print(f"\n[bold]Scoring {len(events)} events with {config.ollama.model}...[/bold]\n")
    scorer = GemmaScorer(config)
    scored = await scorer.score_batch(events)

    for se in scored:
        console.print(
            f"  [{se.priority.value.upper():8s}] {se.final_score:.2f}  "
            f"{se.event.title[:50]}\n"
            f"            Reason: {se.scoring.reason}\n"
            f"            Action: {se.scoring.action_required or '-'}"
        )
    return scored


async def run_sandbox_calendar(
    config: Optional[ClutchConfig] = None,
    source_filter: str | None = None,
    count: int | None = None,
) -> None:
    """Full pipeline with dry-run calendar. Needs Ollama, nothing else."""
    config = config or load_config()

    scored = await run_sandbox_score(config=config, source_filter=source_filter, count=count)
    if not scored:
        return

    console.print(f"\n[bold]Calendar dry-run:[/bold]\n")
    dry_cal = DryCalendar()

    for se in scored:
        if se.priority in (Priority.CRITICAL, Priority.HIGH):
            dry_cal.create_event(se)

    dry_cal.print_summary()


async def run_sandbox_full(
    config: Optional[ClutchConfig] = None,
    db_path: Optional[Path] = None,
    source_filter: str | None = None,
    count: int | None = None,
) -> dict:
    """Full sandbox pipeline: mock fetch -> real scoring -> dry-run calendar -> SQLite.

    Tests everything except actual API calls. Needs only Ollama running.
    """
    config = config or load_config()
    conn = get_db(db_path or Path("data/clutch-sandbox.db"))
    stats = {"fetched": 0, "new": 0, "scored": 0, "calendar_simulated": 0}

    # Step 1: Mock fetch
    mock = MockConnector(source_filter=source_filter, count=count)
    events = await mock.fetch()
    stats["fetched"] = len(events)
    console.print(f"[bold]-> Mock fetch: {len(events)} events[/bold]")

    # Step 2: Dedup
    new_events = [e for e in events if not event_exists(conn, e.id)]
    stats["new"] = len(new_events)
    console.print(f"[bold]-> {len(new_events)} new events[/bold]")

    if not new_events:
        console.print("[green]All events already seen in sandbox DB.[/green]")
        conn.close()
        return stats

    # Step 3: Real Gemma scoring
    console.print(f"[bold]-> Scoring with {config.ollama.model}...[/bold]")
    scorer = GemmaScorer(config)
    scored = await scorer.score_batch(new_events)
    stats["scored"] = len(scored)

    for se in scored:
        upsert_scored_event(conn, se)
        console.print(
            f"  [{se.priority.value.upper():8s}] {se.final_score:.2f}  "
            f"{se.event.title[:55]} -- {se.scoring.reason}"
        )

    # Step 4: Dry-run calendar
    console.print(f"\n[bold]-> Calendar dry-run:[/bold]")
    dry_cal = DryCalendar()
    for se in scored:
        if se.priority in (Priority.CRITICAL, Priority.HIGH):
            dry_cal.create_event(se)
            stats["calendar_simulated"] += 1

    dry_cal.print_summary()
    conn.close()

    console.print(f"\n[bold green]+ Sandbox run complete[/bold green]")
    console.print(
        f"  Fetched: {stats['fetched']}  New: {stats['new']}  "
        f"Scored: {stats['scored']}  Calendar (dry): {stats['calendar_simulated']}"
    )
    console.print(f"  Data saved to: data/clutch-sandbox.db")
    return stats
