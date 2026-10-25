"""RSS/Atom feed connector."""

from __future__ import annotations

import hashlib
from datetime import datetime
from time import mktime
from typing import Any

import feedparser

from clutch.connectors.base import ClutchConnector
from clutch.models import EventType, NormalizedEvent


class RSSConnector(ClutchConnector):
    """Reads RSS 2.0 and Atom feeds.

    Config (clutch.yaml):
        connectors:
          rss:
            enabled: true
            feeds:
              - https://dev.to/feed
              - https://news.ycombinator.com/rss
    """

    name = "rss"
    source_type = "message"

    def __init__(self, feeds: list[str] | None = None, **kwargs: Any) -> None:
        self.feeds = feeds or []

    async def fetch(self, **kwargs: Any) -> list[NormalizedEvent]:
        events: list[NormalizedEvent] = []
        for feed_url in self.feeds:
            try:
                parsed = feedparser.parse(feed_url)
                for entry in parsed.entries[:20]:
                    events.append(self._normalize(entry, feed_url))
            except Exception as e:
                print(f"[rss] Error fetching {feed_url}: {e}")
        return events

    async def health_check(self) -> bool:
        try:
            if self.feeds:
                result = feedparser.parse(self.feeds[0])
                return result.bozo == 0
        except Exception:
            pass
        return False

    def _normalize(self, entry: Any, feed_url: str) -> NormalizedEvent:
        entry_id = entry.get("id") or entry.get("link") or entry.get("title", "")
        stable_id = hashlib.sha256(entry_id.encode()).hexdigest()[:16]

        published = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            published = datetime.fromtimestamp(mktime(entry.published_parsed))

        title = entry.get("title", "Untitled")
        summary = entry.get("summary", entry.get("description", ""))
        link = entry.get("link", "")

        return NormalizedEvent(
            id=f"rss:{stable_id}",
            title=title,
            source="rss",
            source_url=link,
            raw_text=f"{title}\n\n{summary}",
            event_type=EventType.ANNOUNCEMENT,
            deadline=None,
            location=None,
            fetched_at=datetime.now(),
            metadata={
                "feed_url": feed_url,
                "published": published.isoformat() if published else None,
                "author": entry.get("author"),
            },
        )
