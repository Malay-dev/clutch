"""Hacktoberfest events connector — fetches fests and online events.

Uses the public MLH API: https://hacktoberfest-api.mlh.com/api/events
No authentication needed.

Config (clutch.yaml):
    connectors:
      hacktoberfest:
        enabled: true
        countries: [IN]              # filter by country code, empty = all
        cities: [Bengaluru, Remote]  # filter by city, empty = all
        include_ended: false         # skip events that already ended
        include_online: true         # include online/stream events
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import httpx

from clutch.connectors.base import ClutchConnector
from clutch.models import EventType, NormalizedEvent

API_URL = "https://hacktoberfest-api.mlh.com/api/events"


class HacktoberfestConnector(ClutchConnector):
    """Fetches Hacktoberfest events from the MLH public API.

    Returns hack days, meetups, workshops, and online streams
    happening throughout October.
    """

    name = "hacktoberfest"
    source_type = "event"

    def __init__(
        self,
        countries: list[str] | None = None,
        cities: list[str] | None = None,
        include_ended: bool = False,
        include_online: bool = True,
        **kwargs: Any,
    ) -> None:
        self.countries = [c.upper() for c in (countries or [])]
        self.cities = [c.lower() for c in (cities or [])]
        self.include_ended = include_ended
        self.include_online = include_online

    async def fetch(self, **kwargs: Any) -> list[NormalizedEvent]:
        events: list[NormalizedEvent] = []
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(API_URL)
                resp.raise_for_status()
                data = resp.json()

                for ev in data.get("events", []):
                    # Filter by status
                    if not self.include_ended and ev.get("status") == "ended":
                        continue

                    # Filter by country
                    if self.countries:
                        address = ev.get("address") or {}
                        country = (address.get("country") or "").upper()
                        if country not in self.countries and not self._is_online(ev):
                            continue

                    # Filter by city
                    if self.cities:
                        address = ev.get("address") or {}
                        city = (address.get("city") or "").lower()
                        is_match = any(c in city for c in self.cities)
                        if not is_match and not self._is_online(ev):
                            continue

                    # Filter online events
                    if self._is_online(ev) and not self.include_online:
                        continue

                    events.append(self._normalize(ev))

        except Exception as e:
            print(f"[hacktoberfest] Error fetching events: {e}")

        return events

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(API_URL)
                return resp.status_code == 200
        except Exception:
            return False

    def _is_online(self, ev: dict) -> bool:
        address = ev.get("address")
        if not address:
            return True
        kind = ev.get("kind", "")
        return kind in ("online", "stream", "ceremony")

    def _normalize(self, ev: dict) -> NormalizedEvent:
        event_id = ev.get("id") or ev.get("slug") or ""
        stable_id = hashlib.sha256(event_id.encode()).hexdigest()[:16]

        title = ev.get("name") or "Hacktoberfest Event"
        description = ev.get("description") or ""
        slug = ev.get("slug") or ""

        # Parse times
        deadline = None
        starts_at = ev.get("startsAt")
        if starts_at:
            try:
                deadline = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        # Location
        address = ev.get("address") or {}
        city = address.get("city")
        country = address.get("country")
        location = None
        if city and country:
            location = f"{city}, {country}"
        elif city:
            location = city

        # URLs
        website_url = ev.get("websiteUrl") or ""
        registration_url = ev.get("registrationUrl") or ""
        source_url = registration_url or website_url or f"https://hacktoberfest.com/fests/"

        # Format
        event_format = ev.get("format") or "unknown"
        kind = ev.get("kind") or "fest"
        status = ev.get("status") or "unknown"

        # Build rich raw_text for Gemma scoring
        raw_parts = [title]
        if event_format:
            raw_parts.append(f"Format: {event_format}")
        if kind:
            raw_parts.append(f"Type: {kind}")
        if location:
            raw_parts.append(f"Location: {location}")
        if deadline:
            raw_parts.append(f"Date: {deadline.strftime('%b %d, %Y')}")
        if description:
            raw_parts.append(f"\n{description[:1000]}")
        raw_text = "\n".join(raw_parts)

        return NormalizedEvent(
            id=f"hacktoberfest:{stable_id}",
            title=title,
            source="hacktoberfest",
            source_url=source_url,
            raw_text=raw_text,
            event_type=EventType.EVENT,
            deadline=deadline,
            location=location,
            fetched_at=datetime.now(),
            metadata={
                "format": event_format,
                "kind": kind,
                "status": status,
                "slug": slug,
                "registration_url": registration_url,
                "logo_url": ev.get("logoUrl"),
                "latitude": address.get("latitude"),
                "longitude": address.get("longitude"),
                "timezone": ev.get("timeZone"),
                "series_id": ev.get("seriesId"),
            },
        )
