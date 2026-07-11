"""Shared Playwright capture logic for browser-based runners.

Mixin providing browser lifecycle management and the capture method.
Used by WebRunner and DockerRunner — both use Playwright for screenshots,
differing only in how the application is started/stopped.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING

import httpx
import structlog
from playwright.async_api import async_playwright

from phantom.runners.actions import DETERMINISM_SCRIPT, execute_actions
from phantom.runners.base import CaptureResult, RunnerContext

if TYPE_CHECKING:
    from collections.abc import Callable

    from playwright.async_api import Browser, Playwright

    from phantom.models import ReadyCheck, ResolvedCapture

logger = structlog.get_logger()


class PlaywrightCaptureMixin:
    """Mixin providing Playwright browser management and capture logic.

    Subclasses must call ``_init_playwright_state()`` in ``__init__``,
    ``_launch_browser()`` after the application is ready, and
    ``_close_browser()`` during teardown.
    """

    # These are set by _init_playwright_state and used by the mixin methods.
    _playwright: Playwright | None
    _browser: Browser | None
    _base_url: str

    def _init_playwright_state(self) -> None:
        """Initialise Playwright-related attributes to safe defaults."""
        self._playwright = None
        self._browser = None
        self._base_url = ""

    async def _launch_browser(self) -> None:
        """Start Playwright and launch headless Chromium (ADR-012)."""
        pw = await async_playwright().start()
        self._playwright = pw
        self._browser = await pw.chromium.launch(
            args=[
                "--disable-animations",
                "--force-prefers-reduced-motion",
            ],
        )

    async def _close_browser(self) -> None:
        """Close browser and Playwright, suppressing errors."""
        if self._browser is not None:
            with contextlib.suppress(Exception):
                await self._browser.close()
            self._browser = None

        if self._playwright is not None:
            with contextlib.suppress(Exception):
                await self._playwright.stop()
            self._playwright = None

    async def capture(self, ctx: RunnerContext, capture_def: ResolvedCapture) -> CaptureResult:
        """Execute a single capture with actions and screenshot."""
        start = time.monotonic()
        capture_id = capture_def.id

        try:
            assert self._browser is not None

            # Fresh browser context per capture (ADR-012)
            context = await self._browser.new_context(
                viewport={
                    "width": capture_def.viewport.width,
                    "height": capture_def.viewport.height,
                },
                device_scale_factor=capture_def.device_scale,
                color_scheme=capture_def.theme if capture_def.theme in ("dark", "light") else None,  # type: ignore[arg-type]
                timezone_id="America/New_York",
            )

            page = await context.new_page()

            # Navigate to route
            if capture_def.route:
                url = capture_def.route
                if not url.startswith("http"):
                    url = f"{self._base_url}{url}"
                await page.goto(url, wait_until="domcontentloaded")

            # Inject determinism helpers
            await page.evaluate(DETERMINISM_SCRIPT)

            # Wait for initial selector if specified
            # Use .first to avoid strict mode errors when selector matches multiple elements
            if capture_def.wait_for:
                await page.locator(capture_def.wait_for).first.wait_for(
                    state=capture_def.wait_for_state,
                    timeout=capture_def.timeout * 1000,
                )

            # Execute actions
            if capture_def.actions:
                await execute_actions(page, capture_def.actions, context)

            # Wait after actions
            if capture_def.wait_after_actions > 0:
                await page.wait_for_timeout(capture_def.wait_after_actions)

            # Re-inject determinism (actions may have triggered new animations)
            await page.evaluate(DETERMINISM_SCRIPT)

            # Take screenshot
            output_path = ctx.raw_output_dir / f"{capture_id}.png"
            await page.screenshot(
                path=str(output_path),
                full_page=capture_def.full_page,
            )

            await context.close()

            elapsed = int((time.monotonic() - start) * 1000)
            return CaptureResult(
                capture_id=capture_id,
                success=True,
                output_path=output_path,
                duration_ms=elapsed,
            )

        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            ctx.logger.error(
                "capture_failed",
                capture_id=capture_id,
                error=str(e),
            )

            # Diagnostic screenshot
            try:
                if "page" in dir() and page is not None:
                    diag_path = ctx.raw_output_dir / f"{capture_id}_diagnostic.png"
                    await page.screenshot(path=str(diag_path))
                    ctx.logger.info("diagnostic_screenshot", path=str(diag_path))
            except Exception:
                pass

            try:
                if "context" in dir() and context is not None:
                    await context.close()
            except Exception:
                pass

            return CaptureResult(
                capture_id=capture_id,
                success=False,
                error=str(e),
                duration_ms=elapsed,
            )

    async def _wait_for_ready(
        self,
        ready_check: ReadyCheck,
        ctx: RunnerContext,
        process_died_check: Callable[[], bool] | None = None,
    ) -> bool:
        """Poll until the application is ready or timeout is reached.

        Args:
            ready_check: The ready-check configuration from the manifest.
            ctx: Runner context for logging.
            process_died_check: Optional callable returning True if the
                backing process/container has died. WebRunner passes a
                lambda checking returncode; DockerRunner passes None.
        """
        from phantom.models import ReadyCheck as ReadyCheckModel

        assert isinstance(ready_check, ReadyCheckModel)
        deadline = asyncio.get_event_loop().time() + ready_check.timeout

        while asyncio.get_event_loop().time() < deadline:
            # Check if process died
            if process_died_check is not None and process_died_check():
                return False

            match ready_check.type:
                case "http":
                    assert ready_check.url is not None
                    try:
                        async with httpx.AsyncClient(timeout=2) as client:
                            resp = await client.get(ready_check.url)
                            if resp.status_code == ready_check.status_code:
                                return True
                    except httpx.TransportError:
                        # Transient during container/app startup. A just-started
                        # server may accept the TCP connection before it can serve
                        # a complete response, so the request is reset mid-flight
                        # (httpx.ReadError / RemoteProtocolError), or the port is
                        # not open yet (ConnectError), or the request times out.
                        # TransportError is the httpx base for all connect/read/
                        # protocol/timeout errors — every one means "not ready
                        # yet": swallow it and keep polling until the deadline.
                        # (Previously only ConnectError/TimeoutException were
                        # caught, so a startup-time ReadError/RemoteProtocolError
                        # escaped and aborted launch() — the docker-runner CI flake.)
                        pass

                case "tcp":
                    assert ready_check.port is not None
                    try:
                        _, writer = await asyncio.wait_for(
                            asyncio.open_connection("localhost", ready_check.port),
                            timeout=2,
                        )
                        writer.close()
                        await writer.wait_closed()
                        return True
                    except (ConnectionRefusedError, TimeoutError, OSError):
                        pass

                case "stdout_match":
                    assert ready_check.pattern is not None
                    # stdout_match only works with runners that have a local
                    # process (e.g. WebRunner).  For docker-compose the
                    # process_died_check is None and there is no process to
                    # read from, so this branch is effectively skipped.
                    if hasattr(self, "_app_process") and self._app_process:
                        found = await self._app_process.wait_for_output(
                            ready_check.pattern,
                            timeout=min(ready_check.interval, 1),
                        )
                        if found:
                            return True

                case "delay":
                    assert ready_check.seconds is not None
                    await asyncio.sleep(ready_check.seconds)
                    return True

            await asyncio.sleep(ready_check.interval)

        return False
