"""Temporal workflow — durable ingestion cycle that survives restarts."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import Optional

from clutch.config import ClutchConfig, EnvSettings

# Temporal imports are optional — gracefully degrade
try:
    from temporalio import activity, workflow
    from temporalio.client import Client as TemporalClient
    from temporalio.worker import Worker

    TEMPORAL_AVAILABLE = True
except ImportError:
    TEMPORAL_AVAILABLE = False

TASK_QUEUE = "clutch-ingestion"
WORKFLOW_ID = "clutch-main-cycle"

SCHEDULE_MAP = {
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "nightly": timedelta(hours=24),
}


if TEMPORAL_AVAILABLE:

    @activity.defn
    async def run_pipeline_activity() -> dict:
        """Temporal activity that runs the Clutch pipeline."""
        from clutch.pipeline import run_pipeline

        return await run_pipeline()

    @workflow.defn
    class ClutchIngestionWorkflow:
        """Durable workflow that runs the pipeline on a schedule."""

        @workflow.run
        async def run(self, schedule: str = "4h") -> None:
            interval = SCHEDULE_MAP.get(schedule, timedelta(hours=4))

            while True:
                # Run the pipeline as an activity
                await workflow.execute_activity(
                    run_pipeline_activity,
                    start_to_close_timeout=timedelta(minutes=10),
                )
                # Sleep until next cycle — Temporal persists this across restarts
                await workflow.sleep(interval)

    async def start_temporal_worker(
        config: ClutchConfig,
        temporal_address: str = "localhost:7233",
    ) -> None:
        """Connect to Temporal and start the worker + workflow."""
        client = await TemporalClient.connect(temporal_address)

        # Start (or signal) the workflow
        try:
            await client.start_workflow(
                ClutchIngestionWorkflow.run,
                config.clutch.schedule,
                id=WORKFLOW_ID,
                task_queue=TASK_QUEUE,
            )
            print(f"[temporal] Started workflow: {WORKFLOW_ID}")
        except Exception as e:
            if "already started" in str(e).lower():
                print(f"[temporal] Workflow already running: {WORKFLOW_ID}")
            else:
                raise

        # Run the worker
        worker = Worker(
            client,
            task_queue=TASK_QUEUE,
            workflows=[ClutchIngestionWorkflow],
            activities=[run_pipeline_activity],
        )
        print(f"[temporal] Worker listening on queue: {TASK_QUEUE}")
        await worker.run()

else:

    async def start_temporal_worker(
        config: ClutchConfig,
        temporal_address: str = "localhost:7233",
    ) -> None:
        raise ImportError(
            "Temporal is not installed. Install with: pip install clutch[temporal]"
        )
