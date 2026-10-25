"""Luma events connector — fetches upcoming events from lu.ma.

Config (clutch.yaml):
    connectors:
      luma:
        enabled: true
        cities: [Bengaluru, Remote]
        categories: [tech, ai, developer]

Uses Luma's public discover API (no auth needed).
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

import httpx

from clutch.connectors.base import ClutchConnector
from clutch.models import EventType, NormalizedEvent

# Working Luma endpoint (discovered from their internal API)
DISCOVER_URL = "https://api.lu.ma/discover/get-paginated-events"


class LumaConnector(ClutchConnector):
    """Fetches upcoming events from Luma (lu.ma).

    Uses the public Luma discover API to find events by city.
    No authentication required.
    """

    name = "luma"
    source_type = "event"

    def __init__(
        self,
        cities: list[str] | None = None,
        categories: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        self.cities = cities or []
        self.categories = categories or []

    async def fetch(self, **kwargs: Any) -> list[NormalizedEvent]:
        events: list[NormalizedEvent] = []
        async with httpx.AsyncClient(timeout=30) as client:
            for city in self.cities:
                try:
                    resp = await client.get(
                        DISCOVER_URL,
                        params={"city": city},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        for entry in data.get("entries", []):
                            ev = entry.get("event", entry)
                            events.append(self._normalize(ev, city))
                    else:
                        print(
                            f"[luma] Unexpected status {resp.status_code} for {city}: "
                            f"{resp.text[:200]}"
                        )
                except Exception as e:
                    print(f"[luma] Error fetching events for {city}: {e}")
        return events

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(DISCOVER_URL, params={"city": "Bengaluru"})
                return resp.status_code == 200
        except Exception:
            return False

    def _normalize(self, ev: dict, city: str) -> NormalizedEvent:
        api_id = ev.get("api_id") or ev.get("id") or ""
        stable_id = hashlib.sha256(str(api_id).encode()).hexdigest()[:16]

        title = ev.get("name") or "Luma Event"
        description = ev.get("description") or ev.get("description_short") or ""

        # Build URL from the short slug
        url_slug = ev.get("url") or api_id
        if url_slug and not url_slug.startswith("http"):
            source_url = f"https://lu.ma/{url_slug}"
        else:
            source_url = url_slug

        # Parse start time
        deadline = None
        start_at = ev.get("start_at") or ev.get("start_time")
        if start_at:
            try:
                deadline = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        # Location from geo_address_info or fallback to city param
        geo = ev.get("geo_address_info") or {}
        location = geo.get("city") or city

        return NormalizedEvent(
            id=f"luma:{stable_id}",
            title=title,
            source="luma",
            source_url=source_url,
            raw_text=f"{title}\n\n{description}".strip(),
            event_type=EventType.EVENT,
            deadline=deadline,
            location=location,
            fetched_at=datetime.now(),
            metadata={
                "city": city,
                "luma_api_id": api_id,
                "cover_url": ev.get("cover_url"),
                "location_type": ev.get("location_type"),
                "calendar_api_id": ev.get("calendar_api_id"),
            },
        )
