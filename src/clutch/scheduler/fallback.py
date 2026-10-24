"""APScheduler fallback — used when Temporal is not available."""

from __future__ import annotations

import asyncio
import signal
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from clutch.config import ClutchConfig, EnvSettings
from clutch.pipeline import run_pipeline

SCHEDULE_MAP = {
    "30m": {"minutes": 30},
    "1h": {"hours": 1},
    "4h": {"hours": 4},
    "nightly": {"hours": 24},
}


def parse_schedule(schedule_str: str) -> dict:
    """Convert schedule string to APScheduler interval kwargs."""
    return SCHEDULE_MAP.get(schedule_str, {"hours": 4})


async def run_scheduler(
    config: ClutchConfig,
    env: EnvSettings,
    db_path: Optional[Path] = None,
) -> None:
    """Run the Clutch pipeline on a schedule using APScheduler."""
    interval = parse_schedule(config.clutch.schedule)

    scheduler = AsyncIOScheduler(timezone=config.clutch.timezone)

    async def _job() -> None:
        print(f"\n[clutch] Running scheduled pipeline...")
        try:
            await run_pipeline(config=config, env=env, db_path=db_path)
        except Exception as e:
            print(f"[clutch] Pipeline error: {e}")

    scheduler.add_job(_job, "interval", **interval, id="clutch_main")
    scheduler.start()

    print(f"[clutch] Scheduler started: every {config.clutch.schedule}")
    print(f"[clutch] Next run: {scheduler.get_job('clutch_main').next_run_time}")

    # Run once immediately
    await _job()

    # Keep running until interrupted
    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    await stop_event.wait()
    scheduler.shutdown()
    print("\n[clutch] Scheduler stopped.")
