"""Google Calendar integration — creates and escalates reminder events.

Escalation is time-driven, not counter-driven:
- >7 days out:  Blueberry (blue) — informational
- 3-7 days out: Tangerine (orange) — act soon
- 1-3 days out: Tomato (red) — urgent
- Today/past:   Tomato (red) + [TODAY] suffix

On each pipeline run, ALL active calendar events are re-evaluated
against the current time. Colors and titles update automatically.
No duplicate events — existing ones are updated in place.
Past events are cleaned up automatically.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from clutch.config import ClutchConfig
from clutch.models import Priority, ScoredEvent

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TOKEN_PATH = Path.home() / ".clutch" / "google_token.json"
CREDENTIALS_PATH = Path.home() / ".clutch" / "google_credentials.json"

# Google Calendar color IDs — time-based, not priority-based
COLOR_BLUE = "9"       # Blueberry — >7 days out
COLOR_ORANGE = "6"     # Tangerine — 3-7 days
COLOR_RED = "11"       # Tomato — <3 days or no deadline


def _days_until(deadline: Optional[datetime]) -> Optional[int]:
    """Calculate days until a deadline. Returns None if no deadline."""
    if not deadline:
        return None
    delta = deadline.replace(tzinfo=None) - datetime.now()
    return delta.days


def _color_for_deadline(deadline: Optional[datetime]) -> str:
    """Pick calendar color based on how close the deadline is."""
    days = _days_until(deadline)
    if days is None:
        return COLOR_ORANGE  # no deadline = treat as moderately urgent
    if days <= 2:
        return COLOR_RED
    if days <= 7:
        return COLOR_ORANGE
    return COLOR_BLUE


def _urgency_suffix(deadline: Optional[datetime]) -> str:
    """Generate a title suffix based on time remaining."""
    days = _days_until(deadline)
    if days is None:
        return ""
    if days < 0:
        return " [EXPIRED]"
    if days == 0:
        return " [TODAY]"
    if days == 1:
        return " [TOMORROW]"
    if days <= 3:
        return f" [{days}d left]"
    if days <= 7:
        return f" [{days}d left]"
    return ""


class CalendarManager:
    """Manages the 'Clutch Radar' calendar and event lifecycle."""

    def __init__(self, config: ClutchConfig) -> None:
        self.config = config
        self.calendar_name = config.output.google_calendar.calendar_name
        self._service = None
        self._calendar_id: Optional[str] = None

    def authenticate(self) -> bool:
        """Run OAuth flow or refresh existing token."""
        creds = None
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)

        if TOKEN_PATH.exists():
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not CREDENTIALS_PATH.exists():
                    print(
                        f"[calendar] Missing credentials file at {CREDENTIALS_PATH}\n"
                        "Download OAuth client JSON from Google Cloud Console and save it there."
                    )
                    return False
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(CREDENTIALS_PATH), SCOPES
                )
                creds = flow.run_local_server(port=0)

            TOKEN_PATH.write_text(creds.to_json())

        self._service = build("calendar", "v3", credentials=creds)
        return True

    def ensure_calendar(self) -> str:
        """Find or create the Clutch Radar calendar. Returns calendar ID."""
        if self._calendar_id:
            return self._calendar_id

        calendars = self._service.calendarList().list().execute()
        for cal in calendars.get("items", []):
            if cal["summary"] == self.calendar_name:
                self._calendar_id = cal["id"]
                return self._calendar_id

        new_cal = self._service.calendars().insert(
            body={"summary": self.calendar_name, "description": "Clutch — persistent radar"}
        ).execute()
        self._calendar_id = new_cal["id"]
        return self._calendar_id

    # ── Create / Update ────────────────────────────────────

    def create_event(self, scored: ScoredEvent) -> str:
        """Create a calendar event, or update if one already exists.

        Skips events with deadlines in the past.
        Returns the Google Calendar event ID.
        """
        cal_id = self.ensure_calendar()

        # Skip past events
        if scored.event.deadline:
            days = _days_until(scored.event.deadline)
            if days is not None and days < -1:
                return ""

        # Check for existing event — update instead of duplicate
        existing_id = self._find_event_by_clutch_id(scored.event.id)
        if existing_id:
            self._update_event(existing_id, scored)
            return existing_id

        # Determine event date
        if scored.event.deadline:
            start = scored.event.deadline
        else:
            start = datetime.now() + timedelta(days=1)

        # Build summary with urgency suffix
        color = _color_for_deadline(scored.event.deadline)
        suffix = _urgency_suffix(scored.event.deadline)
        priority_label = scored.priority.value.upper()
        summary = f"[{priority_label}] {scored.event.title}"
        if scored.scoring.action_required:
            summary += f" - {scored.scoring.action_required}"
        summary = f"{summary}{suffix}"

        description = (
            f"Source: {scored.event.source}\n"
            f"Score: {scored.final_score:.2f} ({scored.priority.value})\n"
            f"Why: {scored.scoring.reason}\n"
        )
        if scored.event.source_url:
            description += f"Link: {scored.event.source_url}\n"
        description += "\nManaged by Clutch. Mark done via CLI or menu bar."

        body = {
            "summary": summary[:250],
            "description": description,
            "start": {"date": start.strftime("%Y-%m-%d")},
            "end": {"date": (start + timedelta(days=1)).strftime("%Y-%m-%d")},
            "colorId": color,
            "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 60}]},
            "extendedProperties": {
                "private": {
                    "clutch_event_id": scored.event.id,
                    "clutch_priority": scored.priority.value,
                    "clutch_score": str(scored.final_score),
                    "clutch_deadline": scored.event.deadline.isoformat() if scored.event.deadline else "",
                }
            },
        }

        event = self._service.events().insert(calendarId=cal_id, body=body).execute()
        return event["id"]

    def _update_event(self, calendar_event_id: str, scored: ScoredEvent) -> None:
        """Update an existing calendar event with current time-based urgency."""
        cal_id = self.ensure_calendar()

        color = _color_for_deadline(scored.event.deadline)
        suffix = _urgency_suffix(scored.event.deadline)
        priority_label = scored.priority.value.upper()
        summary = f"[{priority_label}] {scored.event.title}"
        if scored.scoring.action_required:
            summary += f" - {scored.scoring.action_required}"
        summary = f"{summary}{suffix}"

        self._service.events().patch(
            calendarId=cal_id,
            eventId=calendar_event_id,
            body={
                "summary": summary[:250],
                "colorId": color,
            },
        ).execute()

    # ── Escalation (runs on every pipeline cycle) ──────────

    def escalate_all_active(self, active_events: list[ScoredEvent]) -> dict:
        """Re-evaluate ALL active calendar events based on current time.

        Updates colors and title suffixes for time remaining.
        Removes calendar events for items that have expired.
        Returns stats dict.
        """
        cal_id = self.ensure_calendar()
        stats = {"updated": 0, "expired_cleaned": 0, "errors": 0}

        for se in active_events:
            if not se.calendar_event_id:
                continue

            # Check if event has expired (deadline passed by more than 1 day)
            if se.event.deadline:
                days = _days_until(se.event.deadline)
                if days is not None and days < -1:
                    try:
                        self.clear_event(se.calendar_event_id)
                        stats["expired_cleaned"] += 1
                    except Exception:
                        pass
                    continue

            # Update with current time-based color and suffix
            try:
                self._update_event(se.calendar_event_id, se)
                stats["updated"] += 1
            except Exception:
                stats["errors"] += 1

        return stats

    # ── Cleanup ────────────────────────────────────────────

    def clear_event(self, calendar_event_id: str) -> None:
        """Delete a calendar event (user marked done or event expired)."""
        cal_id = self.ensure_calendar()
        try:
            self._service.events().delete(
                calendarId=cal_id, eventId=calendar_event_id
            ).execute()
        except Exception as e:
            print(f"[calendar] Could not delete event {calendar_event_id}: {e}")

    def clear_all_for_event_id(self, clutch_event_id: str) -> int:
        """Clear all calendar events for a Clutch event ID. Returns count cleared."""
        cal_id = self.ensure_calendar()
        cleared = 0
        page_token = None
        while True:
            events_result = self._service.events().list(
                calendarId=cal_id,
                privateExtendedProperty=f"clutch_event_id={clutch_event_id}",
                pageToken=page_token,
            ).execute()
            for ev in events_result.get("items", []):
                try:
                    self._service.events().delete(
                        calendarId=cal_id, eventId=ev["id"]
                    ).execute()
                    cleared += 1
                except Exception:
                    pass
            page_token = events_result.get("nextPageToken")
            if not page_token:
                break
        return cleared

    def _find_event_by_clutch_id(self, clutch_event_id: str) -> str | None:
        """Find an existing calendar event by its Clutch event ID."""
        cal_id = self.ensure_calendar()
        try:
            events_result = self._service.events().list(
                calendarId=cal_id,
                privateExtendedProperty=f"clutch_event_id={clutch_event_id}",
                maxResults=1,
            ).execute()
            items = events_result.get("items", [])
            if items:
                return items[0]["id"]
        except Exception:
            pass
        return None
