"""KonfHub events connector — fetches events from konfhub.com.

Two-phase fetch:
1. List: GET featured-events API for event list (fast, no auth)
2. Detail: GET each event's page __NEXT_DATA__ for description (richer scoring)

Config (clutch.yaml):
    connectors:
      konfhub:
        enabled: true
        countries: [India]
        cities: [Bengaluru]
        include_paid: true
        fetch_details: true     # fetch per-event descriptions (slower but richer)
        max_detail_fetches: 20  # cap detail fetches to avoid hammering
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

import httpx

from clutch.connectors.base import ClutchConnector
from clutch.models import EventType, NormalizedEvent

API_URL = "https://manage-api.konfhub.com/featured-events"
EVENT_PAGE_URL = "https://konfhub.com/{slug}"

HEADERS = {
    "accept": "application/json",
    "origin": "https://konfhub.com",
    "referer": "https://konfhub.com/",
}


class KonfHubConnector(ClutchConnector):
    """Fetches featured events from KonfHub.

    KonfHub is a popular event platform in India for tech conferences,
    hackathons, workshops, and meetups.
    """

    name = "konfhub"
    source_type = "event"

    def __init__(
        self,
        countries: list[str] | None = None,
        cities: list[str] | None = None,
        include_paid: bool = True,
        fetch_details: bool = True,
        max_detail_fetches: int = 20,
        **kwargs: Any,
    ) -> None:
        self.countries = countries or ["India"]
        self.cities = [c.lower() for c in (cities or [])]
        self.include_paid = include_paid
        self.fetch_details = fetch_details
        self.max_detail_fetches = max_detail_fetches

    async def fetch(self, **kwargs: Any) -> list[NormalizedEvent]:
        events: list[NormalizedEvent] = []

        async with httpx.AsyncClient(timeout=30, headers=HEADERS) as client:
            for country in self.countries:
                try:
                    resp = await client.get(API_URL, params={"country": country})
                    resp.raise_for_status()
                    data = resp.json()

                    filtered = []
                    for ev in data.get("featuredEvents", []):
                        if self.cities:
                            ev_city = (ev.get("city") or "").lower()
                            if not any(c in ev_city for c in self.cities):
                                continue

                        if not self.include_paid and not ev.get("is_free", False):
                            continue

                        end_date = ev.get("end_date")
                        if end_date:
                            try:
                                end = datetime.fromisoformat(end_date)
                                if end < datetime.now():
                                    continue
                            except (ValueError, TypeError):
                                pass

                        filtered.append(ev)

                    # Fetch details for top events (by date proximity)
                    if self.fetch_details:
                        detail_count = 0
                        for ev in filtered:
                            if detail_count >= self.max_detail_fetches:
                                break
                            slug = ev.get("event_url")
                            if slug:
                                detail = await self._fetch_detail(client, slug)
                                if detail:
                                    ev["_detail"] = detail
                                    detail_count += 1

                    for ev in filtered:
                        events.append(self._normalize(ev, country))

                except Exception as e:
                    print(f"[konfhub] Error fetching events for {country}: {e}")

        return events

    async def _fetch_detail(self, client: httpx.AsyncClient, slug: str) -> dict | None:
        """Fetch event detail from the page's __NEXT_DATA__ JSON."""
        try:
            resp = await client.get(
                EVENT_PAGE_URL.format(slug=slug),
                headers={"accept": "text/html"},
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return None

            text = resp.text
            # Extract __NEXT_DATA__ JSON
            match = re.search(
                r'__NEXT_DATA__"\s*type="application/json">(.*?)</script>',
                text,
            )
            if not match:
                return None

            data = json.loads(match.group(1))
            return data.get("props", {}).get("pageProps", {}).get("eventData")

        except Exception:
            return None

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10, headers=HEADERS) as client:
                resp = await client.get(API_URL, params={"country": "India"})
                return resp.status_code == 200
        except Exception:
            return False

    def _normalize(self, ev: dict, country: str) -> NormalizedEvent:
        detail = ev.get("_detail") or {}

        event_id = (
            detail.get("event_id")
            or ev.get("event_id")
            or ev.get("event_url")
            or ev.get("name", "")
        )
        stable_id = hashlib.sha256(str(event_id).encode()).hexdigest()[:16]

        title = detail.get("name") or ev.get("name") or "KonfHub Event"
        event_url = ev.get("event_url") or ""
        source_url = f"https://konfhub.com/{event_url}" if event_url else "https://konfhub.com"

        # Parse start time
        deadline = None
        start_date = detail.get("start_date") or ev.get("start_date")
        start_time = detail.get("start_time") or ev.get("start_time") or ""
        if start_date:
            try:
                dt_str = f"{start_date} {start_time}".strip()
                deadline = datetime.fromisoformat(dt_str)
            except (ValueError, TypeError):
                try:
                    deadline = datetime.fromisoformat(start_date)
                except (ValueError, TypeError):
                    pass

        # Location
        city = detail.get("city") or ev.get("city") or ""
        venue = detail.get("venue") or ev.get("venue") or ""
        ev_country = detail.get("country") or ev.get("country") or country
        location_parts = [p for p in [city, ev_country] if p]
        location = ", ".join(location_parts) if location_parts else None

        # Description from detail page (HTML stripped to plain text)
        description = ""
        raw_desc = detail.get("description") or ""
        if raw_desc:
            description = re.sub(r"<[^>]+>", " ", raw_desc)
            description = re.sub(r"\s+", " ", description).strip()

        # Build rich raw text for Gemma scoring
        is_free = ev.get("is_free", False)
        is_virtual = detail.get("is_virtual") or ev.get("is_virtual", False)

        raw_parts = [title]
        if venue:
            raw_parts.append(f"Venue: {venue}")
        if city:
            raw_parts.append(f"City: {city}")
        if deadline:
            raw_parts.append(f"Date: {deadline.strftime('%b %d, %Y')}")
        raw_parts.append(f"Free: {'Yes' if is_free else 'No'}")
        raw_parts.append(f"Virtual: {'Yes' if is_virtual else 'No'}")
        if detail.get("event_website"):
            raw_parts.append(f"Website: {detail['event_website']}")
        if description:
            raw_parts.append(f"\n{description[:800]}")
        raw_text = "\n".join(raw_parts)

        return NormalizedEvent(
            id=f"konfhub:{stable_id}",
            title=title,
            source="konfhub",
            source_url=source_url,
            raw_text=raw_text,
            event_type=EventType.EVENT,
            deadline=deadline,
            location=location,
            fetched_at=datetime.now(),
            metadata={
                "is_free": is_free,
                "is_virtual": is_virtual,
                "venue": venue,
                "featured_category": ev.get("featured_category"),
                "poster_url": detail.get("event_poster_url") or ev.get("event_poster_url"),
                "event_website": detail.get("event_website"),
                "timezone": detail.get("time_zone") or ev.get("time_zone"),
                "event_id": event_id,
                "has_detail": bool(detail),
            },
        )
