"""Temporal workflow — durable ingestion cycle with per-step activities.

Each pipeline step is a separate Temporal activity:
- fetch_* activities run in parallel, isolated from each other
- score_events batches through Gemma with retry
- sync_calendar pushes to Google Calendar with retry

If one connector fails, the rest still proceed. If Gemma times out,
it retries without re-fetching. The 4h sleep is a durable Temporal
timer that survives process restarts and machine reboots.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from clutch.config import ClutchConfig, EnvSettings, load_config, load_env

# Temporal imports are optional — gracefully degrade
try:
    from temporalio import activity, workflow
    from temporalio.client import Client as TemporalClient
    from temporalio.common import RetryPolicy
    from temporalio.worker import Worker

    TEMPORAL_AVAILABLE = True
except ImportError:
    TEMPORAL_AVAILABLE = False

TASK_QUEUE = "clutch-ingestion"

SCHEDULE_MAP = {
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "nightly": timedelta(hours=24),
}


if TEMPORAL_AVAILABLE:

    # ── Activities ─────────────────────────────────────────
    # Each activity is independently retryable and observable
    # in the Temporal UI.

    @activity.defn
    async def fetch_connector_activity(connector_name: str) -> list[dict]:
        """Fetch events from a single connector. Returns serialized NormalizedEvents."""
        config = load_config()
        env = load_env()

        from clutch.connectors.discovery import discover_connector_classes

        available = discover_connector_classes()
        cls = available.get(connector_name)
        if not cls:
            activity.logger.warning(f"Connector '{connector_name}' not found")
            return []

        # Build the connector instance
        from clutch.connectors.discovery import _get_connector_config, _instantiate_connector

        connectors_cfg = config.connectors
        connector_cfg = _get_connector_config(connector_name, connectors_cfg)
        if connector_cfg is None:
            return []

        instance = _instantiate_connector(connector_name, cls, connector_cfg, env)
        if instance is None:
            return []

        activity.logger.info(f"Fetching from {connector_name}...")
        events = await instance.fetch()
        activity.logger.info(f"Fetched {len(events)} events from {connector_name}")

        # Serialize to dicts for Temporal payload
        return [e.model_dump(mode="json") for e in events]

    @activity.defn
    async def score_events_activity(event_dicts: list[dict]) -> list[dict]:
        """Pre-filter noise, then score relevant events with Gemma.
        
        Returns serialized ScoredEvents for both filtered noise (auto-scored 0.0)
        and Gemma-scored relevant events.
        """
        if not event_dicts:
            return []

        config = load_config()
        from clutch.engine.prefilter import prefilter_events
        from clutch.engine.scorer import GemmaScorer
        from clutch.models import NormalizedEvent, ScoredEvent, ScoringResult

        events = [NormalizedEvent.model_validate(d) for d in event_dicts]

        # Pre-filter: keyword match against interest profile
        relevant, noise = prefilter_events(events, config.profile)
        activity.logger.info(
            f"Pre-filter: {len(relevant)} relevant, {len(noise)} noise"
        )

        all_scored: list[ScoredEvent] = []

        # Auto-score noise as INFO 0.0
        noise_scoring = ScoringResult(
            interest_score=0.0, urgency=0.0, scarcity=0.0, impact=0.0,
            reason="Filtered: no keyword match with interest profile",
            action_required=None,
        )
        for event in noise:
            all_scored.append(ScoredEvent.from_scoring(event, noise_scoring))

        # Score relevant events with Gemma
        if relevant:
            activity.logger.info(f"Scoring {len(relevant)} events with {config.ollama.model}...")
            scorer = GemmaScorer(config)
            scored = await scorer.score_batch(relevant)
            all_scored.extend(scored)
            activity.logger.info(f"Scored {len(scored)} events")

        return [se.model_dump(mode="json") for se in all_scored]

    @activity.defn
    async def persist_events_activity(scored_dicts: list[dict]) -> int:
        """Write scored events to SQLite. Returns count persisted."""
        if not scored_dicts:
            return 0

        from clutch.db import get_db, upsert_scored_event
        from clutch.models import ScoredEvent

        conn = get_db()
        count = 0
        for d in scored_dicts:
            se = ScoredEvent.model_validate(d)
            upsert_scored_event(conn, se)
            count += 1
        conn.close()

        activity.logger.info(f"Persisted {count} events to SQLite")
        return count

    @activity.defn
    async def sync_calendar_activity(scored_dicts: list[dict]) -> dict:
        """Create/escalate Google Calendar events with caps. Returns stats."""
        stats = {"created": 0, "escalated": 0, "errors": 0, "skipped": 0}
        if not scored_dicts:
            return stats

        config = load_config()
        from clutch.actions.calendar import CalendarManager
        from clutch.db import (
            get_active_events,
            get_db,
            increment_escalation,
            update_calendar_event_id,
        )
        from clutch.models import Priority, ScoredEvent

        cal = CalendarManager(config)
        if not cal.authenticate():
            activity.logger.warning("Google Calendar auth failed — skipping")
            return stats

        conn = get_db()

        # Enforce caps
        existing_active = [se for se in get_active_events(conn) if se.calendar_event_id]
        active_count = len(existing_active)
        max_total = config.scoring.max_calendar_events
        max_new = config.scoring.max_new_per_run
        slots_available = max(0, max_total - active_count)
        create_limit = min(max_new, slots_available)

        activity.logger.info(
            f"Calendar: {active_count} active, {create_limit} slots "
            f"(max {max_total} total, {max_new} per run)"
        )

        # Sort candidates by score, take top N
        candidates = []
        for d in scored_dicts:
            se = ScoredEvent.model_validate(d)
            if se.priority in (Priority.CRITICAL, Priority.HIGH):
                candidates.append(se)
        candidates.sort(key=lambda se: se.final_score, reverse=True)

        created = 0
        for se in candidates:
            if created >= create_limit:
                stats["skipped"] += 1
                continue
            try:
                cal_id = cal.create_event(se)
                update_calendar_event_id(conn, se.event.id, cal_id)
                stats["created"] += 1
                created += 1
            except Exception as e:
                activity.logger.error(f"Calendar create failed: {e}")
                stats["errors"] += 1

        # Escalate existing active events
        for se in existing_active:
            if se.escalation_count < 10:
                try:
                    cal.escalate_event(se.calendar_event_id, se)
                    increment_escalation(conn, se.event.id)
                    stats["escalated"] += 1
                except Exception:
                    pass

        conn.close()
        activity.logger.info(
            f"Calendar: {stats['created']} created, "
            f"{stats['escalated']} escalated, {stats['skipped']} skipped (cap), "
            f"{stats['errors']} errors"
        )
        return stats

    @activity.defn
    async def get_enabled_connectors_activity() -> list[str]:
        """Return names of connectors that are enabled in config."""
        config = load_config()
        env = load_env()
        from clutch.connectors.discovery import build_connectors_from_config

        connectors = build_connectors_from_config(config, env)
        names = [c.name for c in connectors]
        activity.logger.info(f"Enabled connectors: {names}")
        return names

    @activity.defn
    async def dedup_events_activity(event_dicts: list[dict]) -> list[dict]:
        """Filter out duplicates — both within the batch and against DB."""
        from clutch.db import event_exists, get_db

        conn = get_db()
        seen_ids: set[str] = set()
        new: list[dict] = []
        for d in event_dicts:
            eid = d["id"]
            if eid not in seen_ids and not event_exists(conn, eid):
                seen_ids.add(eid)
                new.append(d)
        conn.close()
        activity.logger.info(f"Dedup: {len(new)} new of {len(event_dicts)} total ({len(event_dicts) - len(new)} duplicates/seen)")
        return new

    # ── Retry policies ─────────────────────────────────────

    FETCH_RETRY = RetryPolicy(
        initial_interval=timedelta(seconds=5),
        maximum_interval=timedelta(seconds=30),
        maximum_attempts=3,
    )

    SCORE_RETRY = RetryPolicy(
        initial_interval=timedelta(seconds=10),
        maximum_interval=timedelta(minutes=1),
        maximum_attempts=2,
    )

    CALENDAR_RETRY = RetryPolicy(
        initial_interval=timedelta(seconds=5),
        maximum_interval=timedelta(seconds=30),
        maximum_attempts=2,
    )

    # ── Workflow ───────────────────────────────────────────

    @workflow.defn
    class ClutchIngestionWorkflow:
        """Durable scheduled workflow — runs the pipeline on a loop.

        Each connector runs as a parallel activity. Failures are isolated.
        The schedule sleep is a Temporal durable timer — survives restarts.
        """

        @workflow.run
        async def run(self, schedule: str = "4h") -> dict:
            interval = SCHEDULE_MAP.get(schedule, timedelta(hours=4))

            while True:
                result = await _run_pipeline_steps()
                workflow.logger.info(f"Cycle complete: {result}")

                # Durable sleep — Temporal persists this timer across restarts
                workflow.logger.info(f"Sleeping for {interval}")
                await workflow.sleep(interval)

    @workflow.defn
    class ClutchOneShotWorkflow:
        """Single-run workflow — runs the pipeline once and completes.

        Same activities as the scheduled workflow but exits after one cycle.
        Useful for testing, demos, and manual triggers from the Temporal UI.
        """

        @workflow.run
        async def run(self) -> dict:
            return await _run_pipeline_steps()

    async def _run_pipeline_steps() -> dict:
        """Shared pipeline steps used by both scheduled and one-shot workflows."""
        workflow.logger.info("Starting ingestion cycle")

        # Step 1: Discover enabled connectors
        connector_names = await workflow.execute_activity(
            get_enabled_connectors_activity,
            start_to_close_timeout=timedelta(seconds=30),
        )

        if not connector_names:
            workflow.logger.warning("No connectors enabled")
            return {"status": "no_connectors"}

        # Step 2: Fetch from all connectors in parallel
        fetch_handles = []
        for name in connector_names:
            handle = workflow.execute_activity(
                fetch_connector_activity,
                args=[name],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=FETCH_RETRY,
            )
            fetch_handles.append(handle)

        # Wait for all fetches — each can fail independently
        all_events: list[dict] = []
        results = await asyncio.gather(*fetch_handles, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                workflow.logger.error(
                    f"Connector '{connector_names[i]}' failed: {result}"
                )
            elif isinstance(result, list):
                all_events.extend(result)

        workflow.logger.info(f"Total fetched: {len(all_events)} events")

        if not all_events:
            return {"status": "no_events", "fetched": 0}

        # Step 3: Dedup against database + within batch
        new_events = await workflow.execute_activity(
            dedup_events_activity,
            args=[all_events],
            start_to_close_timeout=timedelta(seconds=30),
        )

        if not new_events:
            workflow.logger.info("No new events")
            return {"status": "no_new", "fetched": len(all_events), "new": 0}

        # Step 4: Pre-filter + Score with Gemma
        scored_events = await workflow.execute_activity(
            score_events_activity,
            args=[new_events],
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=SCORE_RETRY,
        )

        # Step 5: Persist to SQLite
        persisted = await workflow.execute_activity(
            persist_events_activity,
            args=[scored_events],
            start_to_close_timeout=timedelta(seconds=30),
        )

        # Step 6: Sync to Google Calendar (with caps)
        cal_stats = await workflow.execute_activity(
            sync_calendar_activity,
            args=[scored_events],
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=CALENDAR_RETRY,
        )

        return {
            "status": "complete",
            "fetched": len(all_events),
            "new": len(new_events),
            "scored": len(scored_events),
            "persisted": persisted,
            "calendar": cal_stats,
        }

    # ── Worker entrypoint ──────────────────────────────────

    ALL_ACTIVITIES = [
        get_enabled_connectors_activity,
        fetch_connector_activity,
        dedup_events_activity,
        score_events_activity,
        persist_events_activity,
        sync_calendar_activity,
    ]

    WORKFLOW_ID_SCHEDULED = "clutch-scheduled"
    WORKFLOW_ID_ONESHOT = "clutch-oneshot"

    async def start_temporal_worker(
        config: ClutchConfig,
        temporal_address: str = "localhost:7233",
    ) -> None:
        """Connect to Temporal and start the worker + scheduled workflow."""
        client = await TemporalClient.connect(temporal_address)

        # Start the scheduled workflow
        try:
            await client.start_workflow(
                ClutchIngestionWorkflow.run,
                config.clutch.schedule,
                id=WORKFLOW_ID_SCHEDULED,
                task_queue=TASK_QUEUE,
            )
            print(f"[temporal] Started scheduled workflow: {WORKFLOW_ID_SCHEDULED}")
            print(f"[temporal] Schedule: every {config.clutch.schedule}")
        except Exception as e:
            if "already started" in str(e).lower():
                print(f"[temporal] Scheduled workflow already running: {WORKFLOW_ID_SCHEDULED}")
            else:
                raise

        # Run the worker
        worker = Worker(
            client,
            task_queue=TASK_QUEUE,
            workflows=[ClutchIngestionWorkflow, ClutchOneShotWorkflow],
            activities=ALL_ACTIVITIES,
        )
        print(f"[temporal] Worker listening on queue: {TASK_QUEUE}")
        print(f"[temporal] Activities: {[a.__name__ for a in ALL_ACTIVITIES]}")
        print(f"[temporal] Open UI: http://localhost:8233")
        await worker.run()

    async def run_once_temporal(
        config: ClutchConfig,
        temporal_address: str = "localhost:7233",
    ) -> dict:
        """Trigger a single pipeline run through Temporal and wait for result.

        Requires the Temporal worker to be running (`clutch run --temporal`).
        """
        client = await TemporalClient.connect(temporal_address)

        import uuid
        run_id = f"{WORKFLOW_ID_ONESHOT}-{uuid.uuid4().hex[:8]}"

        print(f"[temporal] Starting one-shot workflow: {run_id}")
        print(f"[temporal] Watch progress at: http://localhost:8233/namespaces/default/workflows/{run_id}")

        result = await client.execute_workflow(
            ClutchOneShotWorkflow.run,
            id=run_id,
            task_queue=TASK_QUEUE,
        )

        print(f"[temporal] Workflow complete: {result}")
        return result

else:

    async def start_temporal_worker(
        config: ClutchConfig,
        temporal_address: str = "localhost:7233",
    ) -> None:
        raise ImportError(
            "Temporal is not installed. Install with: pip install clutch[temporal]"
        )

    async def run_once_temporal(
        config: ClutchConfig,
        temporal_address: str = "localhost:7233",
    ) -> dict:
        raise ImportError(
            "Temporal is not installed. Install with: pip install clutch[temporal]"
        )
