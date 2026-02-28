"""Unit tests for the Desktop runner."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from phantom.runners.desktop import DesktopRunner


@pytest.fixture
def runner() -> DesktopRunner:
    return DesktopRunner()


@pytest.fixture
def mock_ctx(tmp_path: Path) -> MagicMock:
    """Build a minimal RunnerContext mock."""
    from phantom.runners.base import RunnerContext

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    manifest = MagicMock()
    manifest.setup.type = "desktop"
    manifest.setup.requires = None
    manifest.setup.build = None
    manifest.setup.run.command = "./myapp"
    manifest.setup.run.env = {"DISPLAY": ":99", "PHANTOM_MODE": "1"}
    manifest.setup.run.ready_check.type = "delay"
    manifest.setup.run.ready_check.seconds = 1
    manifest.setup.run.ready_check.timeout = 5
    manifest.setup.teardown = None
    manifest.desktop = None

    ctx = MagicMock(spec=RunnerContext)
    ctx.project_dir = tmp_path
    ctx.raw_output_dir = raw_dir
    ctx.manifest = manifest
    ctx.logger = MagicMock()
    return ctx


class TestDesktopRunnerInit:
    def test_initial_state(self, runner: DesktopRunner) -> None:
        assert runner._xvfb_proc is None
        assert runner._app_proc is None
        assert runner._display == ":99"
        assert runner._window_id is None
        assert runner._desktop_config is None


class TestDesktopRunnerSetup:
    @pytest.mark.asyncio
    async def test_setup_checks_tools(self, runner: DesktopRunner, mock_ctx: MagicMock) -> None:
        """Setup should verify Xvfb, xdotool, and import are available."""
        with patch("phantom.runners.desktop.run_command") as mock_run:
            # All tools found
            mock_run.return_value = MagicMock(returncode=0)
            await runner.setup(mock_ctx)

            # Should check each required tool
            calls = [c.args for c in mock_run.call_args_list]
            assert ("which", "Xvfb") in calls
            assert ("which", "xdotool") in calls
            assert ("which", "import") in calls

    @pytest.mark.asyncio
    async def test_setup_fails_missing_tool(
        self, runner: DesktopRunner, mock_ctx: MagicMock
    ) -> None:
        """Setup should raise RunnerSetupError if a tool is missing."""
        from phantom.exceptions import RunnerSetupError

        with patch("phantom.runners.desktop.run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            with pytest.raises(RunnerSetupError, match="Xvfb"):
                await runner.setup(mock_ctx)

    @pytest.mark.asyncio
    async def test_setup_runs_build_commands(
        self, runner: DesktopRunner, mock_ctx: MagicMock
    ) -> None:
        """Setup should run build commands if configured."""
        mock_ctx.manifest.setup.build = ["make clean", "make"]

        with (
            patch("phantom.runners.desktop.run_command") as mock_cmd,
            patch("phantom.runners.desktop.run_shell") as mock_shell,
        ):
            mock_cmd.return_value = MagicMock(returncode=0)
            mock_shell.return_value = MagicMock(returncode=0)
            await runner.setup(mock_ctx)

            # Should call run_shell for each build command
            assert mock_shell.call_count == 2


class TestDesktopRunnerActions:
    @pytest.mark.asyncio
    async def test_click_action(self, runner: DesktopRunner, mock_ctx: MagicMock) -> None:
        """Click action should invoke xdotool mousemove + click."""
        from phantom.models import ClickAction

        runner._display = ":99"

        action = ClickAction(type="click", x=100, y=200)
        with patch("phantom.runners.desktop.run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            await runner._execute_desktop_actions([action], mock_ctx)

            mock_run.assert_called_once()
            args = mock_run.call_args.args
            assert "xdotool" in args
            assert "mousemove" in args
            assert "100" in args
            assert "200" in args

    @pytest.mark.asyncio
    async def test_keystroke_action(self, runner: DesktopRunner, mock_ctx: MagicMock) -> None:
        """Keystroke action should invoke xdotool key."""
        from phantom.models import KeystrokeAction

        runner._display = ":99"

        action = KeystrokeAction(type="keystroke", key="Return")
        with patch("phantom.runners.desktop.run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            await runner._execute_desktop_actions([action], mock_ctx)

            args = mock_run.call_args.args
            assert "xdotool" in args
            assert "key" in args
            assert "Return" in args

    @pytest.mark.asyncio
    async def test_type_text_action(self, runner: DesktopRunner, mock_ctx: MagicMock) -> None:
        """TypeText action should invoke xdotool type."""
        from phantom.models import TypeTextAction

        runner._display = ":99"

        action = TypeTextAction(type="type_text", text="hello", delay=50)
        with patch("phantom.runners.desktop.run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            await runner._execute_desktop_actions([action], mock_ctx)

            args = mock_run.call_args.args
            assert "xdotool" in args
            assert "type" in args
            assert "hello" in args

    @pytest.mark.asyncio
    async def test_wait_action(self, runner: DesktopRunner, mock_ctx: MagicMock) -> None:
        """Wait action should sleep for the specified duration."""
        from phantom.models import WaitAction

        runner._display = ":99"

        action = WaitAction(type="wait", ms=100)
        # This should just sleep, no xdotool call
        with patch("phantom.runners.desktop.run_command") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            await runner._execute_desktop_actions([action], mock_ctx)
            # run_command should NOT be called for wait
            mock_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_unsupported_action_warns(
        self, runner: DesktopRunner, mock_ctx: MagicMock
    ) -> None:
        """Unsupported actions should log a warning."""
        runner._display = ":99"

        action = MagicMock()
        action.type = "unknown"
        with patch("phantom.runners.desktop.run_command"):
            await runner._execute_desktop_actions([action], mock_ctx)
            mock_ctx.logger.warning.assert_called_once()


class TestDesktopRunnerCapture:
    @pytest.mark.asyncio
    async def test_capture_success(
        self, runner: DesktopRunner, mock_ctx: MagicMock
    ) -> None:
        """Capture should return success when window is found and screenshot produced."""
        capture_def = MagicMock()
        capture_def.id = "test-capture"
        capture_def.actions = []
        capture_def.wait_after_actions = 0

        # Create a fake screenshot file
        output_path = mock_ctx.raw_output_dir / "test-capture.png"

        with patch.object(runner, "_find_window", return_value="12345"):
            with patch.object(runner, "_capture_window") as mock_cap:
                async def _create_file(wid: str, path: Path, ctx: MagicMock) -> None:
                    path.write_bytes(b"\x89PNG" + b"\x00" * 200)

                mock_cap.side_effect = _create_file
                result = await runner.capture(mock_ctx, capture_def)

        assert result.success
        assert result.capture_id == "test-capture"
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_capture_no_window(
        self, runner: DesktopRunner, mock_ctx: MagicMock
    ) -> None:
        """Capture should fail if no window is found."""
        capture_def = MagicMock()
        capture_def.id = "test-capture"
        capture_def.actions = []
        capture_def.wait_after_actions = 0

        with patch.object(runner, "_find_window", return_value=None):
            result = await runner.capture(mock_ctx, capture_def)

        assert not result.success
        assert "No application window found" in (result.error or "")


class TestDesktopRunnerTeardown:
    @pytest.mark.asyncio
    async def test_teardown_cleans_up(
        self, runner: DesktopRunner, mock_ctx: MagicMock
    ) -> None:
        """Teardown should kill app and Xvfb processes."""
        # Set up mock processes
        app_proc = AsyncMock()
        app_proc.returncode = None
        app_proc.terminate = MagicMock()
        app_proc.kill = MagicMock()
        app_proc.wait = AsyncMock(return_value=0)
        # After terminate, set returncode
        async def _wait_terminate() -> int:
            app_proc.returncode = 0
            return 0
        app_proc.wait.side_effect = _wait_terminate

        xvfb_proc = AsyncMock()
        xvfb_proc.returncode = None
        xvfb_proc.terminate = MagicMock()
        xvfb_proc.kill = MagicMock()
        xvfb_proc.wait = AsyncMock(return_value=0)
        async def _wait_xvfb() -> int:
            xvfb_proc.returncode = 0
            return 0
        xvfb_proc.wait.side_effect = _wait_xvfb

        runner._app_proc = app_proc
        runner._xvfb_proc = xvfb_proc
        runner._window_id = "12345"

        await runner.teardown(mock_ctx)

        assert runner._app_proc is None
        assert runner._xvfb_proc is None
        assert runner._window_id is None

    @pytest.mark.asyncio
    async def test_teardown_never_raises(
        self, runner: DesktopRunner, mock_ctx: MagicMock
    ) -> None:
        """Teardown should never raise, even if processes throw."""
        app_proc = MagicMock()
        app_proc.terminate.side_effect = OSError("already dead")
        app_proc.returncode = None
        app_proc.wait = AsyncMock(side_effect=OSError("already dead"))
        app_proc.kill = MagicMock(side_effect=OSError("already dead"))
        runner._app_proc = app_proc

        # Should not raise
        await runner.teardown(mock_ctx)
        assert runner._app_proc is None


class TestDesktopRunnerRegistry:
    def test_desktop_runner_registered(self) -> None:
        """Desktop runner should be available in the registry."""
        from phantom.runners import available_runners, get_runner

        assert "desktop" in available_runners()
        runner = get_runner("desktop")
        assert isinstance(runner, DesktopRunner)
