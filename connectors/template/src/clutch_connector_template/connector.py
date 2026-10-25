"""Template connector — replace this with your own source.

To build a Clutch connector:

1. Clone this template:
   cp -r connectors/template connectors/my-source
   mv src/clutch_connector_template src/clutch_connector_mysource

2. Implement fetch() and health_check()

3. Update pyproject.toml:
   - name = "clutch-connector-mysource"
   - entry point: mysource = "clutch_connector_mysource:MySourceConnector"

4. Install: pip install -e connectors/my-source

5. Clutch auto-discovers it on next run.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from clutch.connectors.base import ClutchConnector
from clutch.models import EventType, NormalizedEvent


class TemplateConnector(ClutchConnector):
    """Replace this with your connector.

    Attributes:
        name: Short identifier used in event IDs and config (e.g. "github").
        source_type: What kind of data this produces — "event", "task", or "message".
    """

    name = "template"
    source_type = "event"

    def __init__(self, **kwargs: Any) -> None:
        """Initialize with config values from clutch.yaml.

        The connector receives its section from clutch.yaml as kwargs.
        For example, if clutch.yaml has:

            connectors:
              template:
                enabled: true
                api_key: "abc123"
                channels: [general, announcements]

        Then kwargs = {"enabled": True, "api_key": "abc123", "channels": ["general", "announcements"]}
        """
        self.config = kwargs

    async def fetch(self, **kwargs: Any) -> list[NormalizedEvent]:
        """Fetch events from your source and normalize them.

        Returns a list of NormalizedEvent objects. Each event must have:
        - id: Unique, stable ID in format "{source}:{hash}". Use a hash of
              something that won't change (e.g. the source's own event ID).
        - title: Short title for display.
        - source: Must match self.name.
        - raw_text: The full text content. Gemma scores based on this.
        - event_type: One of EventType (EVENT, TASK, MESSAGE, DEADLINE, ANNOUNCEMENT).

        Optional but valuable:
        - deadline: When this expires. Drives urgency scoring.
        - location: Where it happens. Helps with location-based scoring.
        - source_url: Link to the original. Included in calendar events.
        - metadata: Dict of extra data for your connector's use.
        """
        # Example: fetch from an API and normalize
        raw_items = await self._fetch_from_api()
        return [self._normalize(item) for item in raw_items]

    async def health_check(self) -> bool:
        """Return True if the connector can reach its source.

        Used by `clutch auth test` to verify credentials and connectivity.
        Keep this lightweight — just check if the API is reachable.
        """
        # Example: try to hit the API root
        return True

    # -- Private methods below -- #

    async def _fetch_from_api(self) -> list[dict]:
        """Replace this with your actual API call.

        Use httpx for async HTTP:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get("https://api.example.com/events")
                return resp.json()["events"]
        """
        # Placeholder — remove this and add your implementation
        return []

    def _normalize(self, item: dict) -> NormalizedEvent:
        """Convert a raw API response item into a NormalizedEvent.

        Use a stable hash for the ID so Clutch can dedup across runs.
        """
        raw_id = item.get("id", item.get("url", ""))
        stable_id = hashlib.sha256(str(raw_id).encode()).hexdigest()[:16]

        return NormalizedEvent(
            id=f"{self.name}:{stable_id}",
            title=item.get("title", "Untitled"),
            source=self.name,
            source_url=item.get("url"),
            raw_text=item.get("description", ""),
            event_type=EventType.EVENT,
            deadline=None,  # Parse from item if available
            location=item.get("location"),
            fetched_at=datetime.now(),
            metadata={},
        )
