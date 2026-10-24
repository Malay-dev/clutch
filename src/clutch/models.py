"""Core data models for Clutch."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class EventType(str, enum.Enum):
    EVENT = "event"
    TASK = "task"
    MESSAGE = "message"
    DEADLINE = "deadline"
    ANNOUNCEMENT = "announcement"


class Priority(str, enum.Enum):
    CRITICAL = "critical"   # > 0.80 — daily calendar block
    HIGH = "high"           # > 0.50 — 2x/week reminder
    INFO = "info"           # < 0.50 — weekly digest only


class EventStatus(str, enum.Enum):
    ACTIVE = "active"
    DONE = "done"
    SNOOZED = "snoozed"
    EXPIRED = "expired"


class NormalizedEvent(BaseModel):
    """Every connector outputs this standard shape."""

    id: str = Field(description="Unique ID: {source}:{source_id}")
    title: str
    source: str = Field(description="Connector name, e.g. 'discord', 'rss'")
    source_url: Optional[str] = None
    raw_text: str = Field(description="Original text from the source")
    event_type: EventType = EventType.EVENT
    deadline: Optional[datetime] = None
    location: Optional[str] = None
    fetched_at: datetime = Field(default_factory=datetime.now)
    metadata: dict = Field(default_factory=dict)


class ScoringResult(BaseModel):
    """Gemma's assessment of an event."""

    interest_score: float = Field(ge=0.0, le=1.0)
    urgency: float = Field(ge=0.0, le=1.0)
    scarcity: float = Field(ge=0.0, le=1.0)
    impact: float = Field(ge=0.0, le=1.0)
    reason: str = Field(description="One-line explanation of why this matters")
    action_required: Optional[str] = Field(
        default=None, description="What the user should do, e.g. 'Register now'"
    )


class ScoredEvent(BaseModel):
    """Event after scoring — ready for prioritization."""

    event: NormalizedEvent
    scoring: ScoringResult
    final_score: float = Field(ge=0.0, le=1.0)
    priority: Priority
    status: EventStatus = EventStatus.ACTIVE
    calendar_event_id: Optional[str] = None
    escalation_count: int = 0
    first_seen: datetime = Field(default_factory=datetime.now)
    last_escalated: Optional[datetime] = None

    @classmethod
    def from_scoring(cls, event: NormalizedEvent, scoring: ScoringResult) -> ScoredEvent:
        score = (
            scoring.interest_score * 0.4
            + scoring.urgency * 0.3
            + scoring.scarcity * 0.2
            + scoring.impact * 0.1
        )
        if score >= 0.80:
            priority = Priority.CRITICAL
        elif score >= 0.50:
            priority = Priority.HIGH
        else:
            priority = Priority.INFO

        return cls(
            event=event,
            scoring=scoring,
            final_score=round(score, 3),
            priority=priority,
        )
