"""Desktop runner for capturing native GUI application screenshots.

Starts the application under Xvfb (virtual X11 framebuffer), interacts via
xdotool (mouse/keyboard), and captures the screen or window via ImageMagick's
``import`` command. Linux-only (designed for GitHub Actions CI).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from typing import TYPE_CHECKING

import structlog

from phantom.conductor.requirements import check_requirements
from phantom.exceptions import RunnerLaunchError, RunnerSetupError
from phantom.runners.base import BaseRunner, CaptureResult, RunnerContext
from phantom.utils.process import run_command, run_shell

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from phantom.models import DesktopConfig, ResolvedCapture

logger = structlog.get_logger()

# Default Xvfb display and resolution
_DEFAULT_DISPLAY = ":99"
_DEFAULT_RESOLUTION = "1920x1080x24"

# Required system tools
_REQUIRED_TOOLS = ["Xvfb", "xdotool", "import"]


class DesktopRunner(BaseRunner):
    """Runner for native GUI applications using Xvfb + xdotool + ImageMagick."""

    def __init__(self) -> None:
        self._xvfb_proc: asyncio.subprocess.Process | None = None
        self._app_proc: asyncio.subprocess.Process | None = None
        self._display: str = _DEFAULT_DISPLAY
        self._resolution: str = _DEFAULT_RESOLUTION
        self._window_id: str | None = None
        self._desktop_config: DesktopConfig | None = None

    async def setup(self, ctx: RunnerContext) -> None:
        """Check requirements and run build commands."""
        setup = ctx.manifest.setup

        if setup.requires:
            await check_requirements(setup.requires)

        # Verify desktop runner tools are available
        for tool in _REQUIRED_TOOLS:
            result = await run_command("which", tool, timeout=5)
            if result.returncode != 0:
                raise RunnerSetupError(
                    f"'{tool}' is required for desktop captures but was not found on PATH.\n"
                    "Install: sudo apt-get install -y xvfb xdotool imagemagick"
                )

        # Run build commands
        if setup.build:
            env = setup.run.env or {}
            for cmd in setup.build:
                ctx.logger.info("build_step", command=cmd)
                result = await run_shell(
                    cmd,
                    cwd=ctx.project_dir,
                    env=env,
                    timeout=setup.runner_timeout,
                )
                if result.returncode != 0:
                    raise RunnerSetupError(f"Build command failed: {cmd}\n{result.stderr[:1000]}")

        ctx.logger.info("setup_complete")

    async def launch(self, ctx: RunnerContext) -> None:
        """Start Xvfb and launch the application."""
        from phantom.models import DesktopConfig

        setup = ctx.manifest.setup
        run_config = setup.run
        ready = run_config.ready_check

        desktop_config = ctx.manifest.desktop or DesktopConfig()
        self._desktop_config = desktop_config

        # Parse display config
        display_conf = desktop_config.display
        self._resolution = f"{display_conf.resolution}x{display_conf.depth}"

        # Use DISPLAY from env config, or derive from resolution config
        env_display = (run_config.env or {}).get("DISPLAY")
        if env_display:
            self._display = env_display

        # Start Xvfb
        ctx.logger.info(
            "starting_xvfb",
            display=self._display,
            resolution=self._resolution,
        )
        self._xvfb_proc = await asyncio.create_subprocess_exec(
            "Xvfb",
            self._display,
            "-screen",
            "0",
            self._resolution,
            "-ac",  # Disable access control
            "+extension",
            "GLX",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        # Give Xvfb a moment to start
        await asyncio.sleep(0.5)
        if self._xvfb_proc.returncode is not None:
            raise RunnerLaunchError(
                f"Xvfb failed to start on display {self._display} "
                f"(exit code {self._xvfb_proc.returncode})"
            )

        # Build env for the application
        app_env = {**os.environ, **(run_config.env or {})}
        app_env["DISPLAY"] = self._display

        # Start the application
        ctx.logger.info("starting_app", command=run_config.command)
        self._app_proc = await asyncio.create_subprocess_shell(
            run_config.command,
            cwd=str(ctx.project_dir),
            env=app_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Wait for readiness
        ctx.logger.info("launch_ready_check", type=ready.type, timeout=ready.timeout)
        success = await self._wait_for_ready(ready, ctx)
        if not success:
            stderr_data = b""
            if self._app_proc.stderr:
                with contextlib.suppress(asyncio.TimeoutError):
                    stderr_data = await asyncio.wait_for(
                        self._app_proc.stderr.read(4096), timeout=1.0
                    )
            raise RunnerLaunchError(
                f"Desktop application failed ready check after {ready.timeout}s. "
                f"Type: {ready.type}\n"
                f"Stderr: {stderr_data.decode(errors='replace')[:500]}"
            )

        ctx.logger.info("launch_complete")

    async def _wait_for_ready(self, ready_check: object, ctx: RunnerContext) -> bool:
        """Wait for the application to be ready."""
        from phantom.models import ReadyCheck

        assert isinstance(ready_check, ReadyCheck)
        deadline = asyncio.get_event_loop().time() + ready_check.timeout

        match ready_check.type:
            case "delay":
                assert ready_check.seconds is not None
                await asyncio.sleep(ready_check.seconds)
                return not self._app_died()

            case "screen_stable":
                # Wait for a window to appear, then ensure it's stable
                window_appeared = False
                while asyncio.get_event_loop().time() < deadline:
                    if self._app_died():
                        return False
                    result = await run_command(
                        "xdotool",
                        "search",
                        "--onlyvisible",
                        "--name",
                        ".",
                        env={"DISPLAY": self._display},
                        timeout=2,
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        if not window_appeared:
                            window_appeared = True
                            # Give app time to finish rendering
                            await asyncio.sleep(ready_check.stability_window / 1000.0)
                        else:
                            return True
                    await asyncio.sleep(0.2)
                return window_appeared

            case "stdout_match":
                assert ready_check.pattern is not None
                while asyncio.get_event_loop().time() < deadline:
                    if self._app_died():
                        return False
                    if self._app_proc and self._app_proc.stdout:
                        with contextlib.suppress(asyncio.TimeoutError):
                            line = await asyncio.wait_for(
                                self._app_proc.stdout.readline(), timeout=0.5
                            )
                            if ready_check.pattern.encode() in line:
                                return True
                    await asyncio.sleep(0.1)
                return False

            case _:
                # For http/tcp, just use delay as fallback
                await asyncio.sleep(min(ready_check.timeout, 5))
                return not self._app_died()

    def _app_died(self) -> bool:
        """Check if the application process has exited."""
        if self._app_proc is None:
            return True
        return self._app_proc.returncode is not None

    async def _find_window(self, ctx: RunnerContext) -> str | None:
        """Find the application window ID via xdotool."""
        env = {"DISPLAY": self._display}

        # Try window title from desktop config or run env
        search_args = ["xdotool", "search", "--onlyvisible"]

        # Use generic "any visible window" search
        search_args.extend(["--name", "."])

        result = await run_command(*search_args, env=env, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            # Return the first (topmost) window
            windows = result.stdout.strip().split("\n")
            return windows[0]

        return None

    async def capture(self, ctx: RunnerContext, capture_def: ResolvedCapture) -> CaptureResult:
        """Execute actions and capture the window to PNG."""
        start = time.monotonic()
        capture_id = capture_def.id

        try:
            # Find the window
            window_id = await self._find_window(ctx)
            if not window_id:
                raise RuntimeError("No application window found for capture")
            self._window_id = window_id

            # Execute actions
            if capture_def.actions:
                await self._execute_desktop_actions(capture_def.actions, ctx)

            # Wait after actions
            if capture_def.wait_after_actions > 0:
                await asyncio.sleep(capture_def.wait_after_actions / 1000.0)

            # Capture the window
            output_path = ctx.raw_output_dir / f"{capture_id}.png"
            await self._capture_window(window_id, output_path, ctx)

            if not output_path.exists():
                raise RuntimeError(f"Screenshot not produced: {output_path}")

            # Check file size
            size = output_path.stat().st_size
            if size < 100:
                raise RuntimeError(f"Screenshot too small ({size} bytes), likely blank")

            elapsed = int((time.monotonic() - start) * 1000)
            return CaptureResult(
                capture_id=capture_id,
                success=True,
                output_path=output_path,
                duration_ms=elapsed,
            )

        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            ctx.logger.error("capture_failed", capture_id=capture_id, error=str(e))
            return CaptureResult(
                capture_id=capture_id,
                success=False,
                error=str(e),
                duration_ms=elapsed,
            )

    async def _capture_window(self, window_id: str, output_path: Path, ctx: RunnerContext) -> None:
        """Capture a window to PNG using ImageMagick's import."""
        env = {"DISPLAY": self._display}

        screenshot_target = "window"
        if self._desktop_config:
            screenshot_target = self._desktop_config.screenshot_target

        if screenshot_target == "screen":
            # Capture entire screen
            result = await run_command(
                "import",
                "-window",
                "root",
                str(output_path),
                env=env,
                timeout=10,
            )
        else:
            # Capture specific window
            result = await run_command(
                "import",
                "-window",
                window_id,
                str(output_path),
                env=env,
                timeout=10,
            )

        if result.returncode != 0:
            raise RuntimeError(f"import command failed: {result.stderr[:500]}")

    async def _execute_desktop_actions(
        self,
        actions: Sequence[object],
        ctx: RunnerContext,
    ) -> None:
        """Execute desktop-relevant actions via xdotool."""
        from phantom.models import (
            ClickAction,
            KeyboardShortcutAction,
            KeystrokeAction,
            TypeTextAction,
            WaitAction,
            WaitForAction,
            XdotoolAction,
        )

        env = {"DISPLAY": self._display}

        for action in actions:
            match action:
                case ClickAction():
                    if action.x is not None and action.y is not None:
                        btn = {"left": "1", "right": "3", "middle": "2"}.get(action.button, "1")
                        await run_command(
                            "xdotool",
                            "mousemove",
                            str(action.x),
                            str(action.y),
                            "click",
                            btn,
                            env=env,
                            timeout=5,
                        )
                    await asyncio.sleep(0.05)

                case KeystrokeAction():
                    await run_command(
                        "xdotool",
                        "key",
                        action.key,
                        env=env,
                        timeout=5,
                    )
                    await asyncio.sleep(0.05)

                case KeyboardShortcutAction():
                    await run_command(
                        "xdotool",
                        "key",
                        action.keys,
                        env=env,
                        timeout=5,
                    )
                    await asyncio.sleep(0.05)

                case TypeTextAction():
                    delay_ms = str(action.delay)
                    await run_command(
                        "xdotool",
                        "type",
                        "--delay",
                        delay_ms,
                        action.text,
                        env=env,
                        timeout=30,
                    )

                case WaitAction():
                    await asyncio.sleep(action.ms / 1000.0)

                case WaitForAction():
                    # Wait for a window with matching title
                    deadline = asyncio.get_event_loop().time() + action.timeout
                    while asyncio.get_event_loop().time() < deadline:
                        result = await run_command(
                            "xdotool",
                            "search",
                            "--name",
                            action.selector,
                            env=env,
                            timeout=2,
                        )
                        if result.returncode == 0 and result.stdout.strip():
                            break
                        await asyncio.sleep(0.2)

                case XdotoolAction():
                    # Raw xdotool command
                    await run_shell(
                        f"xdotool {action.action}",
                        env=env,
                        timeout=10,
                    )

                case _:
                    ctx.logger.warning(
                        "desktop_action_unsupported",
                        type=getattr(action, "type", "unknown"),
                    )

    async def teardown(self, ctx: RunnerContext) -> None:
        """Kill the application and stop Xvfb."""
        # Kill app process
        if self._app_proc is not None:
            with contextlib.suppress(Exception):
                self._app_proc.terminate()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._app_proc.wait(), timeout=5.0)
            if self._app_proc.returncode is None:
                with contextlib.suppress(Exception):
                    self._app_proc.kill()
                with contextlib.suppress(Exception):
                    await self._app_proc.wait()
            self._app_proc = None

        # Kill Xvfb
        if self._xvfb_proc is not None:
            with contextlib.suppress(Exception):
                self._xvfb_proc.terminate()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._xvfb_proc.wait(), timeout=3.0)
            if self._xvfb_proc.returncode is None:
                with contextlib.suppress(Exception):
                    self._xvfb_proc.kill()
                with contextlib.suppress(Exception):
                    await self._xvfb_proc.wait()
            self._xvfb_proc = None

        # Run teardown commands
        teardown_cmds = ctx.manifest.setup.teardown or []
        for cmd in teardown_cmds:
            try:
                await run_shell(cmd, cwd=ctx.project_dir, timeout=10)
            except Exception as e:
                ctx.logger.warning("teardown_command_failed", command=cmd, error=str(e))

        self._window_id = None
        self._desktop_config = None

        ctx.logger.info("teardown_complete")
