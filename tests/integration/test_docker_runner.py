"""Integration tests for the Docker runner.

Requires Docker to be installed and running, plus Playwright + Chromium:
    playwright install chromium

These tests start real Docker containers, launch a real browser,
and capture real screenshots. They are auto-skipped if Docker is unavailable.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from phantom.models import load_manifest
from phantom.runners.base import RunnerContext
from phantom.runners.docker import DockerRunner

TEST_APP_DIR = Path(__file__).parent.parent / "fixtures" / "test-docker-app"
MANIFEST_PATH = TEST_APP_DIR / ".phantom.yml"
PORT = 9754


def _docker_available() -> bool:
    """Check if Docker daemon is reachable (not just CLI installed)."""
    try:
        # Check CLI exists
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False
        # Check daemon is actually running
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _docker_available(), reason="Docker not available"),
]


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


async def _full_lifecycle_capture(ctx: RunnerContext, capture_id: str) -> object:
    """Helper: full lifecycle — setup, launch, capture one, teardown."""
    runner = DockerRunner()
    try:
        await runner.setup(ctx)
        await runner.launch(ctx)

        resolved = ctx.manifest.resolve_captures()
        target = next(r for r in resolved if r.id == capture_id)
        result = await runner.capture(ctx, target)
        return result
    finally:
        await runner.teardown(ctx)


async def _full_lifecycle_all(ctx: RunnerContext) -> list[object]:
    """Helper: full lifecycle — setup, launch, run all, teardown."""
    runner = DockerRunner()
    try:
        await runner.setup(ctx)
        await runner.launch(ctx)
        results = await runner.run_all(ctx)
        return results
    finally:
        await runner.teardown(ctx)


class TestDockerRunnerCaptures:
    """Test that the Docker runner captures non-blank screenshots."""

    @pytest.mark.integration
    def test_capture_homepage(self, runner_ctx: RunnerContext) -> None:
        """Capture the homepage served by nginx in Docker."""
        result = asyncio.run(_full_lifecycle_capture(runner_ctx, "homepage"))
        assert result.success, f"Capture failed: {result.error}"
        assert result.output_path is not None
        assert result.output_path.exists()
        assert result.output_path.stat().st_size > 1000, "Screenshot looks blank"
        assert result.duration_ms > 0

    @pytest.mark.integration
    def test_capture_mobile_viewport(self, runner_ctx: RunnerContext) -> None:
        """Capture homepage at mobile viewport dimensions."""
        result = asyncio.run(_full_lifecycle_capture(runner_ctx, "mobile-homepage"))
        assert result.success, f"Capture failed: {result.error}"
        assert result.output_path is not None
        assert result.output_path.exists()

        # Verify image dimensions (390 * 2 DPR = 780 width)
        from PIL import Image

        img = Image.open(result.output_path)
        assert img.width == 390 * 2  # device_scale: 2
        assert img.height == 844 * 2

    @pytest.mark.integration
    def test_run_all_captures(self, runner_ctx: RunnerContext) -> None:
        """Run all captures and verify results."""
        results = asyncio.run(_full_lifecycle_all(runner_ctx))
        assert len(results) == 2
        succeeded = [r for r in results if r.success]
        assert len(succeeded) == 2, (
            f"Expected 2 successes, got {len(succeeded)}. "
            f"Failures: {[(r.capture_id, r.error) for r in results if not r.success]}"
        )

    @pytest.mark.integration
    def test_teardown_removes_containers(self, runner_ctx: RunnerContext) -> None:
        """After teardown, docker compose ps should show no running containers."""

        async def _run() -> None:
            runner = DockerRunner()
            try:
                await runner.setup(runner_ctx)
                await runner.launch(runner_ctx)
            finally:
                await runner.teardown(runner_ctx)

            # Verify containers are gone
            result = subprocess.run(
                ["docker", "compose", "-f", "docker-compose.yml", "ps", "-q"],
                capture_output=True,
                text=True,
                cwd=TEST_APP_DIR,
            )
            assert result.stdout.strip() == "", (
                f"Expected no running containers but found: {result.stdout.strip()}"
            )

        asyncio.run(_run())
