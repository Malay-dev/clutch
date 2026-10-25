"""Mock connectors that generate realistic test events — no tokens needed."""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta
from typing import Any

from clutch.connectors.base import ClutchConnector
from clutch.models import EventType, NormalizedEvent

# Realistic event templates seeded from actual community patterns
_EVENTS = [
    {
        "title": "GDG DevFest Bengaluru 2026",
        "source": "discord",
        "raw_text": (
            "GDG DevFest Bengaluru 2026 is here! Join us for a full day of talks on "
            "AI/ML, Cloud, Android, and Web. Limited seats — register now on the link. "
            "Date: Nov 15, 2026. Venue: NIMHANS Convention Centre."
        ),
        "event_type": EventType.EVENT,
        "deadline_offset_days": 22,
        "location": "Bengaluru",
    },
    {
        "title": "Hacktoberfest 2026 Week 4: Open Source AI Challenge",
        "source": "rss",
        "raw_text": (
            "Build with open-weight models and OSS AI tools. Submit your project by "
            "Nov 1. Prizes include cash awards from Gemma, Temporal, Sentry, and more. "
            "Theme: Make the machines do the boring stuff."
        ),
        "event_type": EventType.DEADLINE,
        "deadline_offset_days": 8,
        "location": "Remote",
    },
    {
        "title": "Bengaluru Robotics Meetup #42",
        "source": "luma",
        "raw_text": (
            "Monthly meetup for robotics enthusiasts. This month: building autonomous "
            "drones with ROS2. Demos welcome. Pizza provided. RSVP required — only 40 spots."
        ),
        "event_type": EventType.EVENT,
        "deadline_offset_days": 5,
        "location": "Bengaluru",
    },
    {
        "title": "New blog post: 10 Tips for Better CSS Grid Layouts",
        "source": "rss",
        "raw_text": (
            "CSS Grid has matured significantly. Here are 10 practical tips to improve "
            "your layouts, including subgrid patterns and container queries. "
            "Published on dev.to by a frontend developer."
        ),
        "event_type": EventType.ANNOUNCEMENT,
        "deadline_offset_days": None,
        "location": None,
    },
    {
        "title": "Google Summer of Code 2027 — Mentor Org Applications Open",
        "source": "rss",
        "raw_text": (
            "GSoC 2027 mentor organization applications are now open. If your open-source "
            "project wants to participate, apply before Dec 15. Student applications open "
            "in March 2027."
        ),
        "event_type": EventType.DEADLINE,
        "deadline_offset_days": 52,
        "location": "Remote",
    },
    {
        "title": "AI Agents Workshop — Mastra + LangGraph",
        "source": "luma",
        "raw_text": (
            "Hands-on workshop: build production AI agents with Mastra and LangGraph. "
            "Covers tool use, memory, multi-agent orchestration. Bangalore, HSR Layout. "
            "Free entry, RSVP required. 60 spots."
        ),
        "event_type": EventType.EVENT,
        "deadline_offset_days": 10,
        "location": "Bengaluru",
    },
    {
        "title": "AUTH-421: SAML SSO login fails for enterprise customers",
        "source": "jira",
        "raw_text": (
            "Critical bug: SAML SSO login flow fails with 500 error when NameID format "
            "is non-standard. Affects 3 enterprise customers. SLA breach in 48 hours. "
            "Assigned to backend team."
        ),
        "event_type": EventType.TASK,
        "deadline_offset_days": 2,
        "location": None,
    },
    {
        "title": "KCD Bengaluru 2026 — Call for Proposals",
        "source": "discord",
        "raw_text": (
            "Kubernetes Community Days Bengaluru is accepting talk proposals. Topics: "
            "Kubernetes, cloud-native, platform engineering, observability. "
            "Deadline: Nov 30. Speaker benefits include travel reimbursement."
        ),
        "event_type": EventType.DEADLINE,
        "deadline_offset_days": 37,
        "location": "Bengaluru",
    },
    {
        "title": "Weekly Hacker News Digest: Top AI/ML stories",
        "source": "rss",
        "raw_text": (
            "This week in AI: OpenAI releases GPT-5 preview, Anthropic publishes new "
            "safety benchmarks, Meta open-sources Llama 4. Plus: a deep dive into "
            "retrieval-augmented generation patterns."
        ),
        "event_type": EventType.ANNOUNCEMENT,
        "deadline_offset_days": None,
        "location": None,
    },
    {
        "title": "MLOps Community Bengaluru — Nov Meetup",
        "source": "luma",
        "raw_text": (
            "Topic: Deploying LLMs in production — lessons from scale. Speakers from "
            "Flipkart and Razorpay. Venue: WeWork Embassy Golf Links. Nov 8, 6:30 PM. "
            "Free, 100 seats."
        ),
        "event_type": EventType.EVENT,
        "deadline_offset_days": 15,
        "location": "Bengaluru",
    },
]


class MockConnector(ClutchConnector):
    """Generates realistic fake events for sandbox testing."""

    name = "mock"
    source_type = "mixed"

    def __init__(
        self,
        source_filter: str | None = None,
        count: int | None = None,
    ) -> None:
        """
        Args:
            source_filter: Only generate events from this source (e.g. "discord").
            count: Number of events to generate. None = all matching templates.
        """
        self.source_filter = source_filter
        self.count = count

    async def fetch(self, **kwargs: Any) -> list[NormalizedEvent]:
        templates = _EVENTS
        if self.source_filter:
            templates = [e for e in templates if e["source"] == self.source_filter]
        if self.count:
            templates = templates[: self.count]

        now = datetime.now()
        events = []
        for tmpl in templates:
            stable_id = hashlib.sha256(tmpl["title"].encode()).hexdigest()[:16]
            deadline = None
            if tmpl["deadline_offset_days"] is not None:
                deadline = now + timedelta(days=tmpl["deadline_offset_days"])

            events.append(
                NormalizedEvent(
                    id=f"mock:{stable_id}",
                    title=tmpl["title"],
                    source=tmpl["source"],
                    source_url=f"https://example.com/events/{stable_id}",
                    raw_text=tmpl["raw_text"],
                    event_type=tmpl["event_type"],
                    deadline=deadline,
                    location=tmpl.get("location"),
                    fetched_at=now,
                    metadata={"sandbox": True},
                )
            )
        return events

    async def health_check(self) -> bool:
        return True
