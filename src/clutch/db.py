"""SQLite storage for events and state."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from clutch.models import (
    EventStatus,
    NormalizedEvent,
    Priority,
    ScoredEvent,
    ScoringResult,
)

DEFAULT_DB_PATH = Path("data/clutch.db")


def get_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Get a database connection, creating tables if needed."""
    path = db_path or DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _create_tables(conn)
    return conn


def _create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            source TEXT NOT NULL,
            source_url TEXT,
            raw_text TEXT NOT NULL,
            event_type TEXT NOT NULL,
            deadline TEXT,
            location TEXT,
            fetched_at TEXT NOT NULL,
            metadata_json TEXT DEFAULT '{}',

            -- scoring
            interest_score REAL,
            urgency REAL,
            scarcity REAL,
            impact REAL,
            final_score REAL,
            reason TEXT,
            action_required TEXT,
            priority TEXT,

            -- state
            status TEXT DEFAULT 'active',
            calendar_event_id TEXT,
            escalation_count INTEGER DEFAULT 0,
            first_seen TEXT NOT NULL,
            last_escalated TEXT,

            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
        CREATE INDEX IF NOT EXISTS idx_events_priority ON events(priority);
        CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);
    """)
    conn.commit()


def event_exists(conn: sqlite3.Connection, event_id: str) -> bool:
    """Check if an event is already stored."""
    row = conn.execute("SELECT 1 FROM events WHERE id = ?", (event_id,)).fetchone()
    return row is not None


def upsert_scored_event(conn: sqlite3.Connection, se: ScoredEvent) -> None:
    """Insert or update a scored event."""
    conn.execute(
        """
        INSERT INTO events (
            id, title, source, source_url, raw_text, event_type,
            deadline, location, fetched_at, metadata_json,
            interest_score, urgency, scarcity, impact, final_score,
            reason, action_required, priority,
            status, calendar_event_id, escalation_count,
            first_seen, last_escalated
        ) VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?
        )
        ON CONFLICT(id) DO UPDATE SET
            final_score = excluded.final_score,
            priority = excluded.priority,
            escalation_count = excluded.escalation_count,
            last_escalated = excluded.last_escalated,
            calendar_event_id = excluded.calendar_event_id,
            updated_at = datetime('now')
        """,
        (
            se.event.id,
            se.event.title,
            se.event.source,
            se.event.source_url,
            se.event.raw_text,
            se.event.event_type.value,
            se.event.deadline.isoformat() if se.event.deadline else None,
            se.event.location,
            se.event.fetched_at.isoformat(),
            json.dumps(se.event.metadata),
            se.scoring.interest_score,
            se.scoring.urgency,
            se.scoring.scarcity,
            se.scoring.impact,
            se.final_score,
            se.scoring.reason,
            se.scoring.action_required,
            se.priority.value,
            se.status.value,
            se.calendar_event_id,
            se.escalation_count,
            se.first_seen.isoformat(),
            se.last_escalated.isoformat() if se.last_escalated else None,
        ),
    )
    conn.commit()


def get_active_events(
    conn: sqlite3.Connection, priority: Optional[Priority] = None
) -> list[ScoredEvent]:
    """Fetch all active events, optionally filtered by priority."""
    query = "SELECT * FROM events WHERE status = 'active'"
    params: list = []
    if priority:
        query += " AND priority = ?"
        params.append(priority.value)
    query += " ORDER BY final_score DESC"

    rows = conn.execute(query, params).fetchall()
    return [_row_to_scored_event(row) for row in rows]


def mark_done(conn: sqlite3.Connection, event_id: str) -> bool:
    """Mark an event as done."""
    cursor = conn.execute(
        "UPDATE events SET status = 'done', updated_at = datetime('now') WHERE id = ?",
        (event_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def mark_done_by_title(conn: sqlite3.Connection, title_fragment: str) -> list[str]:
    """Mark events matching a title fragment as done. Returns matched IDs."""
    rows = conn.execute(
        "SELECT id FROM events WHERE status = 'active' AND title LIKE ?",
        (f"%{title_fragment}%",),
    ).fetchall()
    ids = [row["id"] for row in rows]
    if ids:
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE events SET status = 'done', updated_at = datetime('now') WHERE id IN ({placeholders})",
            ids,
        )
        conn.commit()
    return ids


def update_calendar_event_id(
    conn: sqlite3.Connection, event_id: str, calendar_event_id: str
) -> None:
    conn.execute(
        "UPDATE events SET calendar_event_id = ?, updated_at = datetime('now') WHERE id = ?",
        (calendar_event_id, event_id),
    )
    conn.commit()


def increment_escalation(conn: sqlite3.Connection, event_id: str) -> None:
    conn.execute(
        """UPDATE events SET
            escalation_count = escalation_count + 1,
            last_escalated = datetime('now'),
            updated_at = datetime('now')
        WHERE id = ?""",
        (event_id,),
    )
    conn.commit()


def _row_to_scored_event(row: sqlite3.Row) -> ScoredEvent:
    event = NormalizedEvent(
        id=row["id"],
        title=row["title"],
        source=row["source"],
        source_url=row["source_url"],
        raw_text=row["raw_text"],
        event_type=row["event_type"],
        deadline=datetime.fromisoformat(row["deadline"]) if row["deadline"] else None,
        location=row["location"],
        fetched_at=datetime.fromisoformat(row["fetched_at"]),
        metadata=json.loads(row["metadata_json"] or "{}"),
    )
    scoring = ScoringResult(
        interest_score=row["interest_score"] or 0.0,
        urgency=row["urgency"] or 0.0,
        scarcity=row["scarcity"] or 0.0,
        impact=row["impact"] or 0.0,
        reason=row["reason"] or "",
        action_required=row["action_required"],
    )
    return ScoredEvent(
        event=event,
        scoring=scoring,
        final_score=row["final_score"] or 0.0,
        priority=row["priority"] or "info",
        status=row["status"] or "active",
        calendar_event_id=row["calendar_event_id"],
        escalation_count=row["escalation_count"] or 0,
        first_seen=datetime.fromisoformat(row["first_seen"]),
        last_escalated=(
            datetime.fromisoformat(row["last_escalated"]) if row["last_escalated"] else None
        ),
    )
