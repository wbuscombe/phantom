"""In-memory async job queue with flock-based process locking.

Jobs are serialized: one runs at a time, others wait in FIFO order.
Queue has a configurable max depth (default 5) — overflow is rejected.
Graceful shutdown finishes the current job and discards queued jobs.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import structlog

from phantom.exceptions import QueueError

if TYPE_CHECKING:
    from phantom.models import PhantomManifest

logger = structlog.get_logger()

DEFAULT_MAX_DEPTH = 5


class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DISCARDED = "discarded"


@runtime_checkable
class JobHandler(Protocol):
    """Protocol for job handler callables."""

    async def __call__(self, job: Job) -> None: ...


@dataclass
class Job:
    """A queued phantom run job."""

    job_id: str
    project: str
    manifest_path: str
    trigger_source: str  # "cli", "webhook", "schedule"
    ref: str | None = None  # git ref/tag
    event_type: str | None = None  # "release.published", "push", etc.
    if_changed: bool = False
    skip_publish: bool = False
    force: bool = False
    capture_id: str | None = None
    status: JobStatus = JobStatus.PENDING
    error: str | None = None
    _manifest: PhantomManifest | None = field(default=None, repr=False)


class JobQueue:
    """Async job queue with process-level flock locking.

    Only one job runs at a time. Jobs wait in FIFO order.
    The queue rejects new jobs when full (max_depth).
    """

    def __init__(
        self,
        lock_dir: Path | None = None,
        max_depth: int = DEFAULT_MAX_DEPTH,
    ) -> None:
        self._queue: asyncio.Queue[Job] = asyncio.Queue(maxsize=max_depth)
        self._max_depth = max_depth
        self._lock_dir = lock_dir or Path("/tmp/phantom/.locks")
        self._running = False
        self._current_job: Job | None = None
        self._shutdown_event = asyncio.Event()
        self._worker_task: asyncio.Task[None] | None = None
        self._lock_fd: int | None = None

    @property
    def current_job(self) -> Job | None:
        return self._current_job

    @property
    def size(self) -> int:
        return self._queue.qsize()

    @property
    def is_running(self) -> bool:
        return self._running

    def submit(self, job: Job) -> None:
        """Submit a job to the queue. Raises QueueError if full."""
        if self._shutdown_event.is_set():
            raise QueueError("Queue is shutting down, not accepting new jobs")

        try:
            self._queue.put_nowait(job)
            logger.info(
                "job_queued",
                job_id=job.job_id,
                project=job.project,
                trigger=job.trigger_source,
                queue_size=self._queue.qsize(),
            )
        except asyncio.QueueFull:
            logger.warning(
                "job_rejected_queue_full",
                job_id=job.job_id,
                project=job.project,
                max_depth=self._max_depth,
            )
            raise QueueError(
                f"Job queue is full ({self._max_depth} jobs). "
                f"Rejecting job {job.job_id} for project '{job.project}'"
            ) from None

    async def start(self, job_handler: JobHandler) -> None:
        """Start processing jobs from the queue."""
        self._running = True
        self._shutdown_event.clear()
        self._worker_task = asyncio.create_task(self._worker_loop(job_handler))
        logger.info("queue_started", max_depth=self._max_depth)

    async def shutdown(self) -> None:
        """Graceful shutdown: finish current job, discard queued jobs."""
        logger.info("queue_shutdown_requested")
        self._shutdown_event.set()

        # Drain and discard queued jobs
        discarded: list[str] = []
        while not self._queue.empty():
            try:
                job = self._queue.get_nowait()
                job.status = JobStatus.DISCARDED
                discarded.append(job.job_id)
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break

        if discarded:
            logger.info("queue_jobs_discarded", count=len(discarded), job_ids=discarded)

        # Wait for current job to finish
        if self._worker_task and not self._worker_task.done():
            await self._worker_task

        self._running = False
        self._release_process_lock()
        logger.info("queue_shutdown_complete")

    async def _worker_loop(self, handler: JobHandler) -> None:
        """Process jobs one at a time until shutdown."""
        while not self._shutdown_event.is_set():
            try:
                job = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except TimeoutError:
                continue

            self._current_job = job
            job.status = JobStatus.RUNNING
            logger.info(
                "job_started",
                job_id=job.job_id,
                project=job.project,
                trigger=job.trigger_source,
            )

            try:
                self._acquire_process_lock(job.project)
                await handler(job)
                job.status = JobStatus.COMPLETED
                logger.info("job_completed", job_id=job.job_id, project=job.project)
            except Exception as e:
                job.status = JobStatus.FAILED
                job.error = str(e)
                logger.error(
                    "job_failed",
                    job_id=job.job_id,
                    project=job.project,
                    error=str(e),
                )
            finally:
                self._release_process_lock()
                self._current_job = None
                self._queue.task_done()

    def _acquire_process_lock(self, project: str) -> None:
        """Acquire flock-based process lock for a project."""
        self._lock_dir.mkdir(parents=True, exist_ok=True)
        lock_file = self._lock_dir / f"{project}.lock"

        try:
            fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_fd = fd
            logger.debug("process_lock_acquired", project=project)
        except OSError:
            logger.warning("process_lock_conflict", project=project)
            raise QueueError(f"Another process is running for project '{project}'") from None

    def _release_process_lock(self) -> None:
        """Release the flock."""
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None
