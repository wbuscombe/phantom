"""Base runner interface and shared data types.

All runners implement BaseRunner. This is the extension point for
community-contributed runners.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from pathlib import Path

    from phantom.models import PhantomManifest, ResolvedCapture


@dataclass
class CaptureResult:
    """Result of a single capture attempt."""

    capture_id: str
    success: bool
    output_path: Path | None = None
    error: str | None = None
    duration_ms: int = 0
    attempt: int = 1
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class RunnerContext:
    """Everything a runner needs to execute captures."""

    project_dir: Path
    raw_output_dir: Path
    manifest: PhantomManifest
    logger: structlog.stdlib.BoundLogger = field(default_factory=lambda: structlog.get_logger())


class BaseRunner(ABC):
    """Abstract base class for all capture runners."""

    @abstractmethod
    async def setup(self, ctx: RunnerContext) -> None:
        """Build the project and prepare the environment.

        Raises RunnerSetupError on failure.
        """

    @abstractmethod
    async def launch(self, ctx: RunnerContext) -> None:
        """Start the application and wait for it to be ready.

        Raises RunnerLaunchError on failure (including timeout).
        """

    @abstractmethod
    async def capture(self, ctx: RunnerContext, capture_def: ResolvedCapture) -> CaptureResult:
        """Execute a single capture.

        Performs actions, waits, and takes screenshot.
        Must not raise — returns CaptureResult with success=False on error.
        """

    @abstractmethod
    async def teardown(self, ctx: RunnerContext) -> None:
        """Stop the application and clean up.

        Must not raise. Always runs, even after failures.
        """

    async def run_all(self, ctx: RunnerContext) -> list[CaptureResult]:
        """Execute all captures. Override for custom sequencing
        (e.g., dependency-aware ordering, parallel execution).

        Default: sequential execution in manifest order.
        """
        resolved = ctx.manifest.resolve_captures()
        results: list[CaptureResult] = []

        for capture_def in resolved:
            if capture_def.skip:
                ctx.logger.info("capture_skipped", capture_id=capture_def.id)
                continue

            result = await self._capture_with_retry(ctx, capture_def)
            results.append(result)

            ctx.logger.info(
                "capture_complete",
                capture_id=capture_def.id,
                success=result.success,
                duration_ms=result.duration_ms,
                attempt=result.attempt,
            )

        return results

    async def _capture_with_retry(
        self, ctx: RunnerContext, capture_def: ResolvedCapture
    ) -> CaptureResult:
        """Execute a capture with retry logic."""
        import asyncio

        retry = capture_def.retry
        last_result: CaptureResult | None = None

        for attempt in range(1, retry.max_attempts + 1):
            result = await self.capture(ctx, capture_def)
            result.attempt = attempt

            if result.success:
                return result

            last_result = result
            if attempt < retry.max_attempts:
                wait_ms = retry.backoff_ms * (2 ** (attempt - 1))
                ctx.logger.warning(
                    "capture_retry",
                    capture_id=capture_def.id,
                    attempt=attempt,
                    error=result.error,
                    next_wait_ms=wait_ms,
                )
                await asyncio.sleep(wait_ms / 1000)

        # All retries exhausted
        assert last_result is not None
        return last_result
