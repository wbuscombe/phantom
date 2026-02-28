"""Integration tests for the Desktop runner.

These tests require xvfb, xdotool, and imagemagick to be installed.
They are automatically skipped on systems without these tools.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

# Skip entire module if xvfb is not available
pytestmark = pytest.mark.skipif(
    shutil.which("Xvfb") is None
    or shutil.which("xdotool") is None
    or shutil.which("import") is None,
    reason="Desktop runner deps not installed (Xvfb, xdotool, imagemagick)",
)


@pytest.mark.integration
class TestDesktopRunnerIntegration:
    @pytest.mark.asyncio
    async def test_capture_xclock(self, tmp_path: Path) -> None:
        """Launch xclock under Xvfb and capture a screenshot."""
        if shutil.which("xclock") is None:
            pytest.skip("xclock not available")

        from phantom.models import (
            CaptureDefinition,
            DesktopConfig,
            PhantomManifest,
            ReadyCheck,
            RunConfig,
            SetupConfig,
        )
        from phantom.runners.base import RunnerContext
        from phantom.runners.desktop import DesktopRunner

        # Build a minimal manifest
        manifest = PhantomManifest(
            phantom="1",
            project="test-desktop",
            name="Test Desktop",
            setup=SetupConfig(
                type="desktop",
                run=RunConfig(
                    command="xclock",
                    ready_check=ReadyCheck(type="delay", seconds=2),
                ),
            ),
            captures=[
                CaptureDefinition(
                    id="clock",
                    name="Clock",
                    output="docs/screenshots/clock.png",
                ),
            ],
            desktop=DesktopConfig(),
        )

        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()

        ctx = RunnerContext(
            project_dir=tmp_path,
            raw_output_dir=raw_dir,
            manifest=manifest,
        )

        runner = DesktopRunner()

        try:
            await runner.setup(ctx)
            await runner.launch(ctx)

            resolved = manifest.resolve_captures()
            result = await runner.capture(ctx, resolved[0])

            assert result.success, f"Capture failed: {result.error}"
            assert result.output_path is not None
            assert result.output_path.exists()
            assert result.output_path.stat().st_size > 100
        finally:
            await runner.teardown(ctx)
