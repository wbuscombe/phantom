"""Playwright-based web runner for capturing web application screenshots.

Implements ADR-012: one browser instance per job, fresh context per capture.
"""

from __future__ import annotations

import structlog

from phantom.conductor.requirements import check_requirements
from phantom.contract import app_env
from phantom.exceptions import RunnerLaunchError, RunnerSetupError
from phantom.runners.base import BaseRunner, RunnerContext
from phantom.runners.playwright_capture import PlaywrightCaptureMixin
from phantom.utils.process import ManagedProcess, run_shell, start_process

logger = structlog.get_logger()


class WebRunner(PlaywrightCaptureMixin, BaseRunner):
    """Runner for web applications using Playwright + headless Chromium."""

    def __init__(self) -> None:
        self._init_playwright_state()
        self._app_process: ManagedProcess | None = None

    async def setup(self, ctx: RunnerContext) -> None:
        """Build the project: check requirements, run build commands."""
        setup = ctx.manifest.setup

        # Check system requirements
        if setup.requires:
            await check_requirements(setup.requires)

        # Run build commands
        if setup.build:
            # Contract v1.0.0 §1: PHANTOM_MODE=1 is guaranteed for the whole
            # launch lifecycle, including build steps.
            env = app_env(setup.run.env)
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
        """Start the dev server and wait for readiness."""
        setup = ctx.manifest.setup
        run_config = setup.run
        # Contract v1.0.0 §1: guarantee PHANTOM_MODE=1 in the app environment.
        env = app_env(run_config.env)

        # Start the application process
        self._app_process = await start_process(
            run_config.command,
            cwd=ctx.project_dir,
            env=env,
        )

        # Wait for ready check
        ready = run_config.ready_check
        ctx.logger.info(
            "launch_ready_check",
            type=ready.type,
            timeout=ready.timeout,
        )

        success = await self._wait_for_ready(
            ready,
            ctx,
            process_died_check=lambda: (
                self._app_process is not None and self._app_process.process.returncode is not None
            ),
        )
        if not success:
            # Capture process output for diagnostics
            stdout = "\n".join(self._app_process.stdout_lines[-20:])
            stderr = "\n".join(self._app_process.stderr_lines[-20:])
            raise RunnerLaunchError(
                f"Application failed ready check after {ready.timeout}s. "
                f"Type: {ready.type}\n"
                f"stdout (last 20 lines):\n{stdout}\n"
                f"stderr (last 20 lines):\n{stderr}"
            )

        # Determine base URL
        if ready.type == "http" and ready.url:
            self._base_url = ready.url.rstrip("/")
        elif ready.type == "tcp" and ready.port:
            self._base_url = f"http://localhost:{ready.port}"
        else:
            self._base_url = "http://localhost:3000"

        # Launch browser (ADR-012: one instance, reused across captures)
        await self._launch_browser()

        ctx.logger.info("launch_complete", base_url=self._base_url)

    async def teardown(self, ctx: RunnerContext) -> None:
        """Stop browser, kill app process, run teardown commands."""
        # Close browser
        await self._close_browser()

        # Kill app process
        if self._app_process is not None:
            await self._app_process.kill()
            self._app_process = None

        # Run teardown commands
        teardown_cmds = ctx.manifest.setup.teardown or []
        for cmd in teardown_cmds:
            try:
                await run_shell(cmd, cwd=ctx.project_dir, timeout=10)
            except Exception as e:
                ctx.logger.warning("teardown_command_failed", command=cmd, error=str(e))

        ctx.logger.info("teardown_complete")
