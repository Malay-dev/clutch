"""Main Clutch pipeline — fetch -> score -> act."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console

from clutch.config import ClutchConfig, EnvSettings, load_config, load_env
from clutch.connectors.discovery import build_connectors_from_config
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

    # Step 1: Discover and fetch from all enabled connectors
    connectors = build_connectors_from_config(config, env)
    if not connectors:
        console.print("[yellow]No connectors enabled. Check clutch.yaml and installed connectors.[/yellow]")
        console.print("  Install connectors: pip install clutch-connector-rss clutch-connector-discord")
        console.print("  List available: clutch connectors")
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

    # Step 2: Filter out duplicates — both within this batch AND already in DB
    seen_ids: set[str] = set()
    unique_events: list[NormalizedEvent] = []
    for e in all_events:
        if e.id not in seen_ids and not event_exists(conn, e.id):
            seen_ids.add(e.id)
            unique_events.append(e)

    new_events = unique_events
    stats["new"] = len(new_events)
    console.print(f"[bold]-> {len(new_events)} new events (of {len(all_events)} total)[/bold]")

    if not new_events:
        console.print("[green]Nothing new to process.[/green]")
        conn.close()
        return stats

    # Step 3: Pre-filter obvious noise before Gemma
    from clutch.engine.prefilter import prefilter_events

    relevant, noise = prefilter_events(new_events, config.profile)
    if noise:
        console.print(
            f"[bold]-> Pre-filter: {len(relevant)} relevant, "
            f"{len(noise)} skipped (no keyword match)[/bold]"
        )
        # Auto-score noise as INFO with 0.0
        from clutch.models import ScoringResult

        noise_scoring = ScoringResult(
            interest_score=0.0,
            urgency=0.0,
            scarcity=0.0,
            impact=0.0,
            reason="Filtered: no keyword match with interest profile",
            action_required=None,
        )
        for event in noise:
            se = ScoredEvent.from_scoring(event, noise_scoring)
            upsert_scored_event(conn, se)

    if not relevant:
        console.print("[green]Nothing relevant to score.[/green]")
        conn.close()
        return stats

    # Step 4: Score with Gemma (only relevant events)
    console.print(f"[bold]-> Scoring {len(relevant)} events with {config.ollama.model}...[/bold]")
    scorer = GemmaScorer(config)
    scored_events = await scorer.score_batch(relevant)
    stats["scored"] = len(scored_events)

    for se in scored_events:
        upsert_scored_event(conn, se)
        console.print(
            f"  [{se.priority.value.upper():8s}] {se.final_score:.2f}  "
            f"{se.event.title[:55]} -- {se.scoring.reason}"
        )

    # Step 5: Calendar actions (time-aware, capped, no duplicates)
    if with_calendar:
        try:
            from clutch.actions.calendar import CalendarManager

            cal = CalendarManager(config)
            if cal.authenticate():
                # First: escalate ALL existing active events based on current time
                all_active = get_active_events(conn)
                active_with_cal = [se for se in all_active if se.calendar_event_id]
                esc_stats = {"updated": 0, "expired_cleaned": 0}
                if active_with_cal:
                    esc_stats = cal.escalate_all_active(active_with_cal)
                    stats["escalated"] = esc_stats["updated"]
                    console.print(
                        f"[bold]-> Calendar escalation: {esc_stats['updated']} updated, "
                        f"{esc_stats['expired_cleaned']} expired cleaned[/bold]"
                    )

                # Then: create new events (capped)
                active_count = len(active_with_cal) - esc_stats.get("expired_cleaned", 0)
                max_total = config.scoring.max_calendar_events
                max_new = config.scoring.max_new_per_run
                slots_available = max(0, max_total - active_count)
                create_limit = min(max_new, slots_available)

                console.print(
                    f"[bold]-> Calendar: {active_count} active, "
                    f"{create_limit} slots for new events "
                    f"(max {max_total} total, {max_new} per run)[/bold]"
                )

                # Sort by score — highest priority gets calendar slots first
                calendar_candidates = sorted(
                    [se for se in scored_events if se.priority in (Priority.CRITICAL, Priority.HIGH)],
                    key=lambda se: se.final_score,
                    reverse=True,
                )

                created = 0
                for se in calendar_candidates:
                    if created >= create_limit:
                        break
                    try:
                        cal_id = cal.create_event(se)
                        if cal_id:  # empty string means skipped (past event)
                            update_calendar_event_id(conn, se.event.id, cal_id)
                            stats["calendar_created"] += 1
                            created += 1
                    except Exception as e:
                        console.print(f"  [red]Calendar error: {e}[/red]")
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
