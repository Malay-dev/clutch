"""Main Clutch pipeline — fetch -> score -> act."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console

from clutch.config import ClutchConfig, EnvSettings, load_config, load_env
from clutch.connectors.base import ClutchConnector
from clutch.connectors.discord_connector import DiscordConnector
from clutch.connectors.luma import LumaConnector
from clutch.connectors.rss import RSSConnector
from clutch.db import (
    event_exists,
    get_active_events,
    get_db,
    increment_escalation,
    update_calendar_event_id,
    upsert_scored_event,
)
from clutch.engine.scorer import GemmaScorer
from clutch.models import NormalizedEvent, Priority, ScoredEvent

console = Console()


def build_connectors(config: ClutchConfig, env: EnvSettings) -> list[ClutchConnector]:
    """Instantiate enabled connectors from config."""
    connectors: list[ClutchConnector] = []

    if config.connectors.rss.enabled:
        connectors.append(RSSConnector(feeds=config.connectors.rss.feeds))

    if config.connectors.discord.enabled and env.discord_token:
        connectors.append(
            DiscordConnector(
                token=env.discord_token,
                servers=[s.model_dump() for s in config.connectors.discord.servers],
            )
        )

    if config.connectors.luma.enabled:
        connectors.append(
            LumaConnector(
                cities=config.connectors.luma.cities,
                categories=config.connectors.luma.categories,
            )
        )

    return connectors


async def run_pipeline(
    config: Optional[ClutchConfig] = None,
    env: Optional[EnvSettings] = None,
    db_path: Optional[Path] = None,
    with_calendar: bool = True,
) -> dict:
    """Run the full Clutch pipeline once.

    Returns a summary dict with counts.
    """
    config = config or load_config()
    env = env or load_env()
    conn = get_db(db_path)
    stats = {"fetched": 0, "new": 0, "scored": 0, "calendar_created": 0, "escalated": 0}

    # Step 1: Fetch from all connectors
    connectors = build_connectors(config, env)
    if not connectors:
        console.print("[yellow]No connectors enabled. Check clutch.yaml[/yellow]")
        return stats

    console.print(f"[bold]-> Running {len(connectors)} connector(s)...[/bold]")
    all_events: list[NormalizedEvent] = []
    for connector in connectors:
        try:
            events = await connector.fetch()
            all_events.extend(events)
            console.print(f"  + {connector.name}: {len(events)} items")
        except Exception as e:
            console.print(f"  x {connector.name}: {e}")

    stats["fetched"] = len(all_events)

    # Step 2: Filter out already-seen events
    new_events = [e for e in all_events if not event_exists(conn, e.id)]
    stats["new"] = len(new_events)
    console.print(f"[bold]-> {len(new_events)} new events (of {len(all_events)} total)[/bold]")

    if not new_events:
        console.print("[green]Nothing new to process.[/green]")
        conn.close()
        return stats

    # Step 3: Score with Gemma
    console.print(f"[bold]-> Scoring {len(new_events)} events with {config.ollama.model}...[/bold]")
    scorer = GemmaScorer(config)
    scored_events = await scorer.score_batch(new_events)
    stats["scored"] = len(scored_events)

    for se in scored_events:
        upsert_scored_event(conn, se)
        console.print(
            f"  [{se.priority.value.upper():8s}] {se.final_score:.2f}  "
            f"{se.event.title[:55]} — {se.scoring.reason}"
        )

    # Step 4: Calendar actions
    if with_calendar:
        try:
            from clutch.actions.calendar import CalendarManager

            cal = CalendarManager(config)
            if cal.authenticate():
                # Create events for new critical/high items
                for se in scored_events:
                    if se.priority in (Priority.CRITICAL, Priority.HIGH):
                        try:
                            cal_id = cal.create_event(se)
                            update_calendar_event_id(conn, se.event.id, cal_id)
                            stats["calendar_created"] += 1
                        except Exception as e:
                            console.print(f"  [red]Calendar error: {e}[/red]")

                # Escalate existing active events
                active = get_active_events(conn)
                for se in active:
                    if se.calendar_event_id and se.escalation_count < 10:
                        try:
                            cal.escalate_event(se.calendar_event_id, se)
                            increment_escalation(conn, se.event.id)
                            stats["escalated"] += 1
                        except Exception as e:
                            pass  # Calendar event may have been manually deleted
        except Exception as e:
            console.print(f"[yellow]Calendar sync skipped: {e}[/yellow]")

    conn.close()

    # Summary
    console.print(f"\n[bold green]+ Clutch run complete[/bold green]")
    console.print(f"  Fetched: {stats['fetched']}  New: {stats['new']}  Scored: {stats['scored']}")
    if with_calendar:
        console.print(
            f"  Calendar: {stats['calendar_created']} created, {stats['escalated']} escalated"
        )

    return stats
