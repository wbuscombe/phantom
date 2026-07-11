"""Integration tests for the Web Runner.

Requires Playwright + Chromium to be installed:
    playwright install chromium

These tests start a real HTTP server, launch a real browser,
and capture real screenshots.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path

import pytest

from phantom.models import load_manifest
from phantom.runners.base import RunnerContext
from phantom.runners.web import WebRunner

TEST_APP_DIR = Path(__file__).parent.parent / "fixtures" / "test-web-app"
MANIFEST_PATH = TEST_APP_DIR / ".phantom.yml"
PORT = 9753


@pytest.fixture(scope="module")
def test_server():
    """Start the test web server for the entire test module."""
    proc = subprocess.Popen(
        [sys.executable, "server.py", "--port", str(PORT)],
        cwd=TEST_APP_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Wait for server to be ready
    import httpx

    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            resp = httpx.get(f"http://localhost:{PORT}", timeout=1)
            if resp.status_code == 200:
                break
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        time.sleep(0.2)
    else:
        proc.kill()
        pytest.fail("Test server failed to start")

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture
def raw_output_dir(tmp_path: Path) -> Path:
    d = tmp_path / "raw"
    d.mkdir()
    return d


@pytest.fixture
def manifest():
    return load_manifest(str(MANIFEST_PATH))


@pytest.fixture
def runner_ctx(manifest, raw_output_dir) -> RunnerContext:
    return RunnerContext(
        project_dir=TEST_APP_DIR,
        raw_output_dir=raw_output_dir,
        manifest=manifest,
    )


class TestWebRunnerCaptures:
    """Test that the web runner captures non-blank screenshots."""

    @pytest.mark.integration
    def test_capture_dashboard(self, test_server, runner_ctx: RunnerContext) -> None:
        """Capture the dashboard page with device cards."""
        runner = WebRunner()
        result = asyncio.run(_run_single_capture(runner, runner_ctx, "dashboard"))
        assert result.success, f"Capture failed: {result.error}"
        assert result.output_path is not None
        assert result.output_path.exists()
        assert result.output_path.stat().st_size > 1000, "Screenshot looks blank"
        assert result.duration_ms > 0

    @pytest.mark.integration
    def test_capture_with_actions(self, test_server, runner_ctx: RunnerContext) -> None:
        """Capture after clicking a device to open detail panel."""
        runner = WebRunner()
        result = asyncio.run(_run_single_capture(runner, runner_ctx, "detail-view"))
        assert result.success, f"Capture failed: {result.error}"
        assert result.output_path is not None
        assert result.output_path.exists()
        assert result.output_path.stat().st_size > 1000

    @pytest.mark.integration
    def test_capture_with_scroll(self, test_server, runner_ctx: RunnerContext) -> None:
        """Capture settings page after scrolling to advanced section."""
        runner = WebRunner()
        result = asyncio.run(_run_single_capture(runner, runner_ctx, "settings"))
        assert result.success, f"Capture failed: {result.error}"
        assert result.output_path is not None
        assert result.output_path.exists()

    @pytest.mark.integration
    def test_capture_mobile_viewport(self, test_server, runner_ctx: RunnerContext) -> None:
        """Capture at mobile viewport dimensions."""
        runner = WebRunner()
        result = asyncio.run(_run_single_capture(runner, runner_ctx, "mobile-admin"))
        assert result.success, f"Capture failed: {result.error}"
        assert result.output_path is not None
        assert result.output_path.exists()

        # Verify image dimensions (390 * 2 DPR = 780 width)
        from PIL import Image

        img = Image.open(result.output_path)
        assert img.width == 390 * 2  # device_scale: 2
        assert img.height == 844 * 2

    @pytest.mark.integration
    def test_capture_with_typing(self, test_server, runner_ctx: RunnerContext) -> None:
        """Capture after typing into search input."""
        runner = WebRunner()
        result = asyncio.run(_run_single_capture(runner, runner_ctx, "search-typed"))
        assert result.success, f"Capture failed: {result.error}"
        assert result.output_path is not None
        assert result.output_path.exists()

    @pytest.mark.integration
    def test_run_all_captures(self, test_server, runner_ctx: RunnerContext) -> None:
        """Run all captures and verify results."""
        runner = WebRunner()
        results = asyncio.run(_run_all(runner, runner_ctx))
        assert len(results) == 5
        succeeded = [r for r in results if r.success]
        assert len(succeeded) == 5, (
            f"Expected 5 successes, got {len(succeeded)}. "
            f"Failures: {[(r.capture_id, r.error) for r in results if not r.success]}"
        )

    @pytest.mark.integration
    def test_skip_flag_respected(self, test_server, raw_output_dir: Path) -> None:
        """Captures with skip=True should be excluded from results."""

        manifest = load_manifest(str(MANIFEST_PATH))
        # Modify a capture to be skipped
        manifest.captures[0].skip = True

        ctx = RunnerContext(
            project_dir=TEST_APP_DIR,
            raw_output_dir=raw_output_dir,
            manifest=manifest,
        )
        runner = WebRunner()
        results = asyncio.run(_run_all(runner, ctx))
        assert len(results) == 4  # One less because of skip
        ids = [r.capture_id for r in results]
        assert "dashboard" not in ids

    @pytest.mark.integration
    def test_diagnostic_screenshot_on_failure(self, test_server, runner_ctx: RunnerContext) -> None:
        """When a capture fails, a diagnostic screenshot should be saved."""
        from phantom.models import CaptureDefaults, CaptureDefinition, RetryConfig

        cap = CaptureDefinition(
            id="will-fail",
            name="Will Fail",
            route="/dashboard",
            output="docs/screenshots/fail.png",
            wait_for=".nonexistent-element-xyz",
            timeout=2,
        )
        resolved = cap.resolve(CaptureDefaults(retry=RetryConfig(max_attempts=1)))

        runner = WebRunner()
        result = asyncio.run(_run_single_capture_resolved(runner, runner_ctx, resolved))
        assert not result.success
        assert result.error is not None

        # Check diagnostic screenshot was saved
        diag = runner_ctx.raw_output_dir / "will-fail_diagnostic.png"
        assert diag.exists(), "Diagnostic screenshot should be saved on failure"


async def _run_single_capture(runner: WebRunner, ctx: RunnerContext, capture_id: str) -> object:
    """Helper: launch browser, run one capture, teardown."""
    from playwright.async_api import async_playwright

    resolved = ctx.manifest.resolve_captures()
    target = next(r for r in resolved if r.id == capture_id)

    pw = await async_playwright().start()
    browser = await pw.chromium.launch()
    runner._playwright = pw
    runner._browser = browser
    runner._base_url = f"http://localhost:{PORT}"

    try:
        result = await runner.capture(ctx, target)
    finally:
        await browser.close()
        await pw.stop()
        runner._playwright = None
        runner._browser = None

    return result


async def _run_single_capture_resolved(
    runner: WebRunner, ctx: RunnerContext, resolved: object
) -> object:
    """Helper: launch browser, run one resolved capture, teardown."""
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = await pw.chromium.launch()
    runner._playwright = pw
    runner._browser = browser
    runner._base_url = f"http://localhost:{PORT}"

    try:
        result = await runner.capture(ctx, resolved)
    finally:
        await browser.close()
        await pw.stop()
        runner._playwright = None
        runner._browser = None

    return result


async def _run_all(runner: WebRunner, ctx: RunnerContext) -> list[object]:
    """Helper: full lifecycle — launch browser, run all, teardown."""
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = await pw.chromium.launch()
    runner._playwright = pw
    runner._browser = browser
    runner._base_url = f"http://localhost:{PORT}"

    try:
        results = await runner.run_all(ctx)
    finally:
        await browser.close()
        await pw.stop()
        runner._playwright = None
        runner._browser = None

    return results
