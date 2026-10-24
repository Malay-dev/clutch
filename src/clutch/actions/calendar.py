"""Google Calendar integration — creates and escalates reminder events."""

from __future__ import annotations

import json
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

# Google Calendar color IDs (predefined palette)
# https://developers.google.com/calendar/api/v3/reference/colors
COLOR_MAP = {
    Priority.CRITICAL: "11",  # Tomato (red)
    Priority.HIGH: "6",       # Tangerine (orange)
    Priority.INFO: "9",       # Blueberry (blue)
}

# Escalation upgrades the color toward red — no emojis, just the color system
ESCALATION_COLOR = {
    0: None,   # keep original
    1: "6",    # Tangerine
    2: "11",   # Tomato
    3: "11",   # Tomato (stays red)
}

ESCALATION_SUFFIX = {
    0: "",
    1: " [reminder]",
    2: " [action needed]",
    3: " [last chance]",
}


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

        # Check existing calendars
        calendars = self._service.calendarList().list().execute()
        for cal in calendars.get("items", []):
            if cal["summary"] == self.calendar_name:
                self._calendar_id = cal["id"]
                return self._calendar_id

        # Create it
        new_cal = self._service.calendars().insert(
            body={"summary": self.calendar_name, "description": "Clutch — persistent radar"}
        ).execute()
        self._calendar_id = new_cal["id"]
        return self._calendar_id

    def create_event(self, scored: ScoredEvent) -> str:
        """Create a calendar event for a scored item. Returns the event ID."""
        cal_id = self.ensure_calendar()

        # Determine event timing
        if scored.event.deadline:
            start = scored.event.deadline
        else:
            # No deadline — put it tomorrow as an all-day nudge
            start = datetime.now() + timedelta(days=1)

        priority_label = scored.priority.value.upper()
        summary = f"[{priority_label}] {scored.event.title}"
        if scored.scoring.action_required:
            summary += f" - {scored.scoring.action_required}"

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
            "colorId": COLOR_MAP.get(scored.priority, "9"),
            "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 60}]},
            "extendedProperties": {
                "private": {
                    "clutch_event_id": scored.event.id,
                    "clutch_priority": scored.priority.value,
                    "clutch_score": str(scored.final_score),
                }
            },
        }

        event = self._service.events().insert(calendarId=cal_id, body=body).execute()
        return event["id"]

    def escalate_event(self, calendar_event_id: str, scored: ScoredEvent) -> None:
        """Update an existing calendar event with escalated urgency."""
        cal_id = self.ensure_calendar()
        new_count = scored.escalation_count + 1

        # Upgrade color based on escalation count
        color = ESCALATION_COLOR.get(min(new_count, 3)) or COLOR_MAP.get(scored.priority, "9")
        suffix = ESCALATION_SUFFIX.get(min(new_count, 3), "")

        priority_label = scored.priority.value.upper()
        summary = f"[{priority_label}] {scored.event.title}"
        if scored.scoring.action_required:
            summary += f" - {scored.scoring.action_required}"

        # Calculate days remaining
        if scored.event.deadline:
            remaining = (scored.event.deadline - datetime.now()).days
            if remaining <= 0:
                summary += " [TODAY]"
            elif remaining <= 3:
                summary += f" [{remaining}d left]"
            else:
                summary += suffix
        else:
            summary += suffix

        self._service.events().patch(
            calendarId=cal_id,
            eventId=calendar_event_id,
            body={
                "summary": summary[:250],
                "colorId": color,
            },
        ).execute()

    def clear_event(self, calendar_event_id: str) -> None:
        """Delete a calendar event (user marked done)."""
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
