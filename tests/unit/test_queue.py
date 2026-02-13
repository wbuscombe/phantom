"""Unit tests for the job queue."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from phantom.conductor.queue import Job, JobQueue, JobStatus
from phantom.exceptions import QueueError

if TYPE_CHECKING:
    from pathlib import Path


def _make_job(project: str = "test-project", job_id: str = "j1") -> Job:
    return Job(
        job_id=job_id,
        project=project,
        manifest_path="/tmp/test/.phantom.yml",
        trigger_source="cli",
    )


class TestJobQueue:
    def test_submit_and_size(self) -> None:
        queue = JobQueue(max_depth=5)
        assert queue.size == 0
        queue.submit(_make_job(job_id="j1"))
        assert queue.size == 1
        queue.submit(_make_job(job_id="j2"))
        assert queue.size == 2

    def test_overflow_rejects(self) -> None:
        queue = JobQueue(max_depth=2)
        queue.submit(_make_job(job_id="j1"))
        queue.submit(_make_job(job_id="j2"))
        with pytest.raises(QueueError, match="full"):
            queue.submit(_make_job(job_id="j3"))

    def test_fifo_order(self) -> None:
        queue = JobQueue(max_depth=5)
        queue.submit(_make_job(job_id="first"))
        queue.submit(_make_job(job_id="second"))
        queue.submit(_make_job(job_id="third"))

        # Internal queue should be FIFO
        j1 = queue._queue.get_nowait()
        j2 = queue._queue.get_nowait()
        j3 = queue._queue.get_nowait()
        assert j1.job_id == "first"
        assert j2.job_id == "second"
        assert j3.job_id == "third"

    async def test_worker_processes_jobs(self, tmp_path: Path) -> None:
        processed: list[str] = []

        async def handler(job: Job) -> None:
            processed.append(job.job_id)

        queue = JobQueue(lock_dir=tmp_path / "locks", max_depth=5)
        await queue.start(handler)  # type: ignore[arg-type]

        queue.submit(_make_job(job_id="j1"))
        queue.submit(_make_job(job_id="j2"))

        # Give the worker time to process
        await asyncio.sleep(0.5)

        await queue.shutdown()

        assert "j1" in processed
        assert "j2" in processed

    async def test_graceful_shutdown_discards_queued(self, tmp_path: Path) -> None:
        processed: list[str] = []

        async def slow_handler(job: Job) -> None:
            await asyncio.sleep(2)  # Slow job
            processed.append(job.job_id)

        queue = JobQueue(lock_dir=tmp_path / "locks", max_depth=5)
        await queue.start(slow_handler)  # type: ignore[arg-type]

        queue.submit(_make_job(job_id="slow"))
        await asyncio.sleep(0.1)  # Let the worker pick up the first job
        queue.submit(_make_job(job_id="discarded"))

        # Shutdown should finish current job and discard queued
        await queue.shutdown()

        assert "slow" in processed
        assert "discarded" not in processed

    def test_submit_during_shutdown_rejected(self) -> None:
        queue = JobQueue(max_depth=5)
        queue._shutdown_event.set()

        with pytest.raises(QueueError, match="shutting down"):
            queue.submit(_make_job())

    async def test_failed_job_recorded(self, tmp_path: Path) -> None:
        async def failing_handler(job: Job) -> None:
            raise ValueError("test error")

        queue = JobQueue(lock_dir=tmp_path / "locks", max_depth=5)
        await queue.start(failing_handler)  # type: ignore[arg-type]

        job = _make_job(job_id="fail")
        queue.submit(job)

        await asyncio.sleep(0.5)
        await queue.shutdown()

        assert job.status == JobStatus.FAILED
        assert job.error == "test error"

    def test_default_max_depth(self) -> None:
        queue = JobQueue()
        assert queue._max_depth == 5
