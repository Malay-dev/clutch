"""macOS menu bar app using rumps."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import rumps

from clutch.db import get_db, get_active_events, mark_done
from clutch.models import Priority

PRIORITY_LABEL = {
    Priority.CRITICAL: "CRITICAL",
    Priority.HIGH: "HIGH",
    Priority.INFO: "INFO",
}


class ClutchMenuBar(rumps.App):
    """Clutch menu bar app — shows active item count."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        super().__init__("Clutch", quit_button="Quit Clutch")
        self.db_path = db_path
        self.timer = rumps.Timer(self._refresh, 60)  # refresh every 60s
        self.timer.start()
        self._refresh(None)

    def _refresh(self, _: object) -> None:
        """Refresh the menu bar count and items."""
        try:
            conn = get_db(self.db_path)
            active = get_active_events(conn)
            critical = [e for e in active if e.priority == Priority.CRITICAL]
            high = [e for e in active if e.priority == Priority.HIGH]

            # Update title with count
            count = len(critical) + len(high)
            self.title = f"Clutch ({count})" if count > 0 else "Clutch"

            # Rebuild menu
            self.menu.clear()

            if not active:
                self.menu.add(rumps.MenuItem("All clear — nothing to do"))
            else:
                for se in critical[:5]:
                    label = PRIORITY_LABEL.get(se.priority, "INFO")
                    item = rumps.MenuItem(
                        f"[{label}] {se.event.title[:50]}",
                        callback=lambda sender, eid=se.event.id: self._mark_done(eid),
                    )
                    self.menu.add(item)

                for se in high[:5]:
                    label = PRIORITY_LABEL.get(se.priority, "INFO")
                    item = rumps.MenuItem(
                        f"[{label}] {se.event.title[:50]}",
                        callback=lambda sender, eid=se.event.id: self._mark_done(eid),
                    )
                    self.menu.add(item)

            self.menu.add(rumps.separator)
            self.menu.add(rumps.MenuItem("Refresh", callback=lambda _: self._refresh(None)))

            conn.close()
        except Exception as e:
            self.title = "Clutch (?)"

    def _mark_done(self, event_id: str) -> None:
        """Mark an event as done via menu bar click."""
        try:
            conn = get_db(self.db_path)
            mark_done(conn, event_id)
            conn.close()
            self._refresh(None)
            rumps.notification("Clutch", "Marked done", f"Event cleared: {event_id[:30]}")
        except Exception as e:
            rumps.notification("Clutch", "Error", str(e))


def run_menubar(db_path: Optional[Path] = None) -> None:
    """Launch the menu bar app."""
    ClutchMenuBar(db_path).run()
