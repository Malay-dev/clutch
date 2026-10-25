"""Dry-run calendar — prints what would happen instead of calling Google API."""

from __future__ import annotations

from datetime import datetime, timedelta

from rich.console import Console
from rich.table import Table

from clutch.models import Priority, ScoredEvent

console = Console()

# Same color mapping as the real calendar, but displayed as text
COLOR_NAMES = {
    Priority.CRITICAL: "Tomato (red)",
    Priority.HIGH: "Tangerine (orange)",
    Priority.INFO: "Blueberry (blue)",
}

ESCALATION_SUFFIX = {
    0: "",
    1: " [reminder]",
    2: " [action needed]",
    3: " [last chance]",
}


class DryCalendar:
    """Simulates Google Calendar operations — prints instead of calling API."""

    def __init__(self) -> None:
        self._events: list[dict] = []
        self._next_id = 1

    def create_event(self, scored: ScoredEvent) -> str:
        """Simulate creating a calendar event."""
        cal_id = f"dry-{self._next_id}"
        self._next_id += 1

        if scored.event.deadline:
            start = scored.event.deadline
        else:
            start = datetime.now() + timedelta(days=1)

        color = COLOR_NAMES.get(scored.priority, "Blueberry (blue)")
        summary = f"[{scored.priority.value.upper()}] {scored.event.title}"
        if scored.scoring.action_required:
            summary += f" - {scored.scoring.action_required}"

        entry = {
            "id": cal_id,
            "summary": summary[:250],
            "date": start.strftime("%Y-%m-%d"),
            "color": color,
            "priority": scored.priority.value,
            "score": scored.final_score,
            "source": scored.event.source,
            "reason": scored.scoring.reason,
            "clutch_id": scored.event.id,
        }
        self._events.append(entry)

        console.print(
            f"  [DRY-RUN] Would create calendar event:\n"
            f"    Calendar: Clutch Radar\n"
            f"    Summary:  {entry['summary']}\n"
            f"    Date:     {entry['date']}\n"
            f"    Color:    {color}\n"
        )
        return cal_id

    def escalate_event(self, calendar_event_id: str, scored: ScoredEvent) -> None:
        """Simulate escalating a calendar event."""
        new_count = scored.escalation_count + 1
        suffix = ESCALATION_SUFFIX.get(min(new_count, 3), "")

        if new_count >= 2:
            color = COLOR_NAMES[Priority.CRITICAL]
        elif new_count >= 1:
            color = COLOR_NAMES[Priority.HIGH]
        else:
            color = COLOR_NAMES.get(scored.priority, "Blueberry (blue)")

        console.print(
            f"  [DRY-RUN] Would escalate event {calendar_event_id}:\n"
            f"    Title:  [{scored.priority.value.upper()}] {scored.event.title}{suffix}\n"
            f"    Color:  {color}\n"
            f"    Escalation count: {new_count}\n"
        )

    def clear_event(self, calendar_event_id: str) -> None:
        """Simulate deleting a calendar event."""
        console.print(f"  [DRY-RUN] Would delete calendar event: {calendar_event_id}")
        self._events = [e for e in self._events if e["id"] != calendar_event_id]

    def print_summary(self) -> None:
        """Print a summary table of all simulated calendar events."""
        if not self._events:
            console.print("\n  [DRY-RUN] No calendar events would be created.")
            return

        table = Table(title="Dry-Run Calendar Preview: Clutch Radar", show_lines=True)
        table.add_column("Date", width=12)
        table.add_column("Color", width=20)
        table.add_column("Summary", width=55)
        table.add_column("Score", width=6)

        for entry in self._events:
            table.add_row(
                entry["date"],
                entry["color"],
                entry["summary"][:55],
                f"{entry['score']:.2f}",
            )

        console.print(table)
