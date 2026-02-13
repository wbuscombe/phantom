"""Schedule/cron support for automatic Phantom runs.

Runs as a simple async loop that checks a schedule table on a 60-second tick.
Parses cron expressions from manifests using croniter. Scheduled jobs default
to --if-changed behavior.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from croniter import croniter  # type: ignore[import-untyped]

from phantom.conductor.queue import Job

if TYPE_CHECKING:
    from phantom.conductor.queue import JobQueue

logger = structlog.get_logger()

TICK_INTERVAL_SECONDS = 60


@dataclass
class ScheduleEntry:
    """A scheduled job from a manifest's trigger config."""

    project: str
    manifest_path: str
    cron_expression: str
    if_changed: bool = True


class Scheduler:
    """Checks scheduled runs on a 60-second tick loop.

    Reads schedule entries from manifests and creates jobs
    when their cron expression indicates it's time to run.
    """

    def __init__(self, queue: JobQueue) -> None:
        self._queue = queue
        self._entries: list[ScheduleEntry] = []
        self._last_check: dict[str, datetime] = {}  # project -> last trigger time
        self._running = False
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def add_entry(self, entry: ScheduleEntry) -> None:
        """Register a schedule entry."""
        # Validate the cron expression
        if not croniter.is_valid(entry.cron_expression):
            logger.error(
                "scheduler_invalid_cron",
                project=entry.project,
                cron=entry.cron_expression,
            )
            return

        self._entries.append(entry)
        logger.info(
            "scheduler_entry_added",
            project=entry.project,
            cron=entry.cron_expression,
        )

    def add_entries_from_manifests(
        self,
        manifest_configs: list[dict[str, str]],
    ) -> None:
        """Add schedule entries from a list of manifest configs.

        Each config should have keys: project, manifest_path, cron.
        """
        for config in manifest_configs:
            entry = ScheduleEntry(
                project=config["project"],
                manifest_path=config["manifest_path"],
                cron_expression=config["cron"],
                if_changed=config.get("if_changed", "true").lower() == "true",
            )
            self.add_entry(entry)

    async def start(self) -> None:
        """Start the scheduler tick loop."""
        self._running = True
        self._task = asyncio.create_task(self._tick_loop())
        logger.info("scheduler_started", entries=len(self._entries))

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("scheduler_stopped")

    async def _tick_loop(self) -> None:
        """Main loop: check schedules every TICK_INTERVAL_SECONDS."""
        while self._running:
            try:
                await self._check_schedules()
            except Exception as e:
                logger.error("scheduler_tick_error", error=str(e))

            try:
                await asyncio.sleep(TICK_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                break

    async def _check_schedules(self) -> None:
        """Check all schedule entries and create jobs for due items."""
        now = datetime.now(tz=UTC)

        for entry in self._entries:
            if self._is_due(entry, now):
                self._create_job(entry)
                self._last_check[entry.project] = now

    def _is_due(self, entry: ScheduleEntry, now: datetime) -> bool:
        """Check if a schedule entry is due to run."""
        last = self._last_check.get(entry.project)

        if last is None:
            # First check — use the cron expression to determine if
            # we should have already run in the last tick interval
            cron = croniter(entry.cron_expression, now)
            prev_time = cron.get_prev(datetime)
            # If the previous scheduled time was within the last tick interval, it's due
            diff = (now - prev_time).total_seconds()
            return bool(diff <= TICK_INTERVAL_SECONDS)

        # Calculate next run time from last check
        cron = croniter(entry.cron_expression, last)
        next_time = cron.get_next(datetime)
        return bool(now >= next_time)

    def _create_job(self, entry: ScheduleEntry) -> None:
        """Create and submit a job for a schedule entry."""
        job = Job(
            job_id=str(uuid.uuid4()),
            project=entry.project,
            manifest_path=entry.manifest_path,
            trigger_source="schedule",
            if_changed=entry.if_changed,
        )

        try:
            self._queue.submit(job)
            logger.info(
                "scheduler_job_created",
                job_id=job.job_id,
                project=entry.project,
                cron=entry.cron_expression,
            )
        except Exception as e:
            logger.warning(
                "scheduler_job_submit_failed",
                project=entry.project,
                error=str(e),
            )

    @staticmethod
    def get_next_run(cron_expression: str, base_time: datetime | None = None) -> datetime:
        """Calculate the next run time for a cron expression.

        Args:
            cron_expression: A standard cron expression.
            base_time: Base time to calculate from (default: now UTC).

        Returns:
            The next scheduled run time.
        """
        base = base_time or datetime.now(tz=UTC)
        cron = croniter(cron_expression, base)
        result: datetime = cron.get_next(datetime)
        return result
