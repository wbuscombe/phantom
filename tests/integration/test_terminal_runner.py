"""Integration tests for the Terminal runner.

Requires silicon to be installed for full capture tests.
PTY-only tests (no silicon) run regardless.

These tests launch a real TUI app in a real PTY, send real keystrokes,
and capture real screenshots via silicon.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from phantom.models import load_manifest
from phantom.runners.base import RunnerContext
from phantom.runners.terminal import TerminalRunner, _dump_screen_ansi

TEST_APP_DIR = Path(__file__).parent.parent / "fixtures" / "test-tui-app"
MANIFEST_PATH = TEST_APP_DIR / ".phantom.yml"

_silicon_available = shutil.which("silicon") is not None


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


async def _launch_runner(ctx: RunnerContext) -> TerminalRunner:
    """Helper: create runner, skip setup (no silicon check), and launch."""
    import asyncio

    runner = TerminalRunner()
    runner._tui_config = ctx.manifest.tui
    await runner.launch(ctx)
    # Give the reader task a moment to process initial output
    await asyncio.sleep(0.5)
    return runner


class TestTerminalRunnerPTY:
    """Tests that only need a PTY + pyte (no silicon)."""

    @pytest.mark.integration
    async def test_launch_and_screen_content(self, runner_ctx: RunnerContext) -> None:
        """Launch the TUI app and verify screen has expected content."""
        runner = await _launch_runner(runner_ctx)
        try:
            assert runner._screen is not None
            screen_text = _dump_screen_ansi(runner._screen)
            assert "Phantom Test TUI" in screen_text
            assert "Dashboard" in screen_text
        finally:
            await runner.teardown(runner_ctx)

    @pytest.mark.integration
    async def test_keystroke_navigation(self, runner_ctx: RunnerContext) -> None:
        """Send j keystrokes and verify the selection moved."""
        import asyncio

        runner = await _launch_runner(runner_ctx)
        try:
            assert runner._screen is not None

            # Send j twice to move selection down
            runner._send_key("j")
            await asyncio.sleep(0.3)
            runner._send_key("j")
            await asyncio.sleep(0.3)

            screen_text = _dump_screen_ansi(runner._screen)
            # Third item "Users" should now be selected (has ▸ prefix)
            assert "▸ Users" in screen_text
        finally:
            await runner.teardown(runner_ctx)

    @pytest.mark.integration
    async def test_type_text_search(self, runner_ctx: RunnerContext) -> None:
        """Enter search mode and type text, verify it appears on screen."""
        import asyncio

        runner = await _launch_runner(runner_ctx)
        try:
            assert runner._screen is not None

            # Enter search mode
            runner._send_key("/")
            await asyncio.sleep(0.3)

            # Type search text
            for ch in "set":
                runner._send_key(ch)
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.3)

            screen_text = _dump_screen_ansi(runner._screen)
            assert "Search: set" in screen_text
        finally:
            await runner.teardown(runner_ctx)

    @pytest.mark.integration
    async def test_screen_stable_readiness(self, runner_ctx: RunnerContext) -> None:
        """Test screen_stable readiness detection with the TUI app."""
        from phantom.models import ReadyCheck

        runner = TerminalRunner()
        runner._tui_config = runner_ctx.manifest.tui

        # Override ready check to use screen_stable
        runner_ctx.manifest.setup.run.ready_check = ReadyCheck(
            type="screen_stable",
            timeout=10,
            stability_window=500,
            check_interval=100,
        )

        await runner.launch(runner_ctx)
        try:
            assert runner._screen is not None
            screen_text = _dump_screen_ansi(runner._screen)
            assert "Phantom Test TUI" in screen_text
        finally:
            await runner.teardown(runner_ctx)

    @pytest.mark.integration
    async def test_teardown_removes_process(self, runner_ctx: RunnerContext) -> None:
        """After teardown, the child process should be gone."""
        runner = await _launch_runner(runner_ctx)
        pid = runner._child_pid
        assert pid is not None
        await runner.teardown(runner_ctx)
        assert runner._child_pid is None
        assert runner._master_fd is None


@pytest.mark.skipif(not _silicon_available, reason="silicon not found on PATH")
class TestTerminalRunnerCaptures:
    """Full capture tests requiring silicon."""

    @pytest.mark.integration
    async def test_capture_main_view(self, runner_ctx: RunnerContext) -> None:
        """Capture the main view and verify PNG is produced."""
        runner = TerminalRunner()
        try:
            await runner.setup(runner_ctx)
            await runner.launch(runner_ctx)

            resolved = runner_ctx.manifest.resolve_captures()
            target = next(r for r in resolved if r.id == "main-view")
            result = await runner.capture(runner_ctx, target)
        finally:
            await runner.teardown(runner_ctx)

        assert result.success, f"Capture failed: {result.error}"
        assert result.output_path is not None
        assert result.output_path.exists()
        assert result.output_path.stat().st_size > 1000, "Screenshot looks blank"

    @pytest.mark.integration
    async def test_capture_with_keystrokes(self, runner_ctx: RunnerContext) -> None:
        """Capture after sending keystrokes to navigate."""
        runner = TerminalRunner()
        try:
            await runner.setup(runner_ctx)
            await runner.launch(runner_ctx)

            resolved = runner_ctx.manifest.resolve_captures()
            target = next(r for r in resolved if r.id == "navigate-down")
            result = await runner.capture(runner_ctx, target)
        finally:
            await runner.teardown(runner_ctx)

        assert result.success, f"Capture failed: {result.error}"
        assert result.output_path is not None
        assert result.output_path.exists()

    @pytest.mark.integration
    async def test_capture_with_type_text(self, runner_ctx: RunnerContext) -> None:
        """Capture after typing text in search mode."""
        runner = TerminalRunner()
        try:
            await runner.setup(runner_ctx)
            await runner.launch(runner_ctx)

            resolved = runner_ctx.manifest.resolve_captures()
            target = next(r for r in resolved if r.id == "search-mode")
            result = await runner.capture(runner_ctx, target)
        finally:
            await runner.teardown(runner_ctx)

        assert result.success, f"Capture failed: {result.error}"
        assert result.output_path is not None
        assert result.output_path.exists()

    @pytest.mark.integration
    async def test_run_all_captures(self, runner_ctx: RunnerContext) -> None:
        """Run all captures and verify results."""
        runner = TerminalRunner()
        try:
            await runner.setup(runner_ctx)
            await runner.launch(runner_ctx)
            results = await runner.run_all(runner_ctx)
        finally:
            await runner.teardown(runner_ctx)

        assert len(results) == 4
        succeeded = [r for r in results if r.success]
        assert len(succeeded) == 4, (
            f"Expected 4 successes, got {len(succeeded)}. "
            f"Failures: {[(r.capture_id, r.error) for r in results if not r.success]}"
        )
