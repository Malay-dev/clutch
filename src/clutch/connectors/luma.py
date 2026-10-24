"""Luma events connector — fetches upcoming events from lu.ma."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

import httpx

from clutch.connectors.base import ClutchConnector
from clutch.models import EventType, NormalizedEvent


class LumaConnector(ClutchConnector):
    """Fetches upcoming events from Luma (lu.ma).

    Uses the public Luma discover API to find events
    matching configured cities and categories.
    """

    name = "luma"
    source_type = "event"

    BASE_URL = "https://api.lu.ma/public/v2/event/search"

    def __init__(self, cities: list[str], categories: list[str]) -> None:
        self.cities = cities
        self.categories = categories

    async def fetch(self, **kwargs: Any) -> list[NormalizedEvent]:
        events: list[NormalizedEvent] = []
        async with httpx.AsyncClient(timeout=30) as client:
            for city in self.cities:
                try:
                    # Luma's public discover endpoint
                    resp = await client.get(
                        "https://api.lu.ma/public/v2/event/search",
                        params={
                            "query": f"{city} tech",
                            "pagination_limit": 20,
                        },
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        for entry in data.get("entries", []):
                            ev = entry.get("event", {})
                            events.append(self._normalize(ev, city))
                    else:
                        # Fallback: try the discover page scrape approach
                        events.extend(await self._fetch_discover(client, city))
                except Exception as e:
                    print(f"[luma] Error fetching events for {city}: {e}")
                    # Try fallback
                    try:
                        async with httpx.AsyncClient(timeout=30) as fallback_client:
                            events.extend(await self._fetch_discover(fallback_client, city))
                    except Exception as e2:
                        print(f"[luma] Fallback also failed for {city}: {e2}")
        return events

    async def _fetch_discover(
        self, client: httpx.AsyncClient, city: str
    ) -> list[NormalizedEvent]:
        """Fallback: fetch from Luma's discover API."""
        events: list[NormalizedEvent] = []
        try:
            resp = await client.get(
                "https://api.lu.ma/discover/get-events",
                params={"location": city, "limit": 20},
            )
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("events", data.get("data", [])):
                    events.append(self._normalize(item, city))
        except Exception as e:
            print(f"[luma] Discover fallback error for {city}: {e}")
        return events

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get("https://lu.ma")
                return resp.status_code < 500
        except Exception:
            return False

    def _normalize(self, ev: dict, city: str) -> NormalizedEvent:
        api_id = ev.get("api_id") or ev.get("id") or ev.get("url", "")
        stable_id = hashlib.sha256(str(api_id).encode()).hexdigest()[:16]

        title = ev.get("name") or ev.get("title") or "Luma Event"
        description = ev.get("description") or ev.get("description_short") or ""
        url = ev.get("url") or ""
        if api_id and not url:
            url = f"https://lu.ma/{api_id}"

        # Parse start time
        deadline = None
        start_at = ev.get("start_at") or ev.get("start_time")
        if start_at:
            try:
                deadline = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        location = ev.get("geo_address_info", {}).get("city") or city

        return NormalizedEvent(
            id=f"luma:{stable_id}",
            title=title,
            source="luma",
            source_url=url if url.startswith("http") else f"https://lu.ma/{url}",
            raw_text=f"{title}\n\n{description}",
            event_type=EventType.EVENT,
            deadline=deadline,
            location=location,
            fetched_at=datetime.now(),
            metadata={
                "city": city,
                "cover_url": ev.get("cover_url"),
                "hosts": ev.get("hosts", []),
            },
        )
