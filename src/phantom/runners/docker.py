"""Docker Compose runner for capturing containerised web applications.

Manages the docker-compose lifecycle (up/down) while reusing the shared
Playwright capture logic from PlaywrightCaptureMixin.
"""

from __future__ import annotations

import contextlib

import structlog

from phantom.conductor.requirements import check_requirements
from phantom.contract import app_env
from phantom.exceptions import RunnerLaunchError, RunnerSetupError
from phantom.runners.base import BaseRunner, RunnerContext
from phantom.runners.playwright_capture import PlaywrightCaptureMixin
from phantom.utils.process import run_command, run_shell

logger = structlog.get_logger()


class DockerRunner(PlaywrightCaptureMixin, BaseRunner):
    """Runner for docker-compose applications using Playwright + headless Chromium."""

    def __init__(self) -> None:
        self._init_playwright_state()
        self._compose_args: list[str] = []

    async def setup(self, ctx: RunnerContext) -> None:
        """Verify Docker is available, check compose v2, run build commands."""
        setup = ctx.manifest.setup

        # Check that docker CLI is present
        if setup.requires:
            await check_requirements(setup.requires)

        # Always verify docker compose v2 works
        result = await run_command("docker", "compose", "version", timeout=10)
        if result.returncode != 0:
            raise RunnerSetupError(
                "Docker Compose v2 is required but 'docker compose version' failed.\n"
                f"{result.stderr[:500]}"
            )

        # Build the reusable compose base args
        assert setup.compose_file is not None
        self._compose_args = ["docker", "compose", "-f", setup.compose_file]
        if setup.compose_profiles:
            for profile in setup.compose_profiles:
                self._compose_args.extend(["--profile", profile])

        # Run build commands (e.g. docker compose build)
        if setup.build:
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
        """Start containers with docker compose up and wait for readiness."""
        setup = ctx.manifest.setup
        run_config = setup.run
        ready = run_config.ready_check

        # Build the up command
        up_cmd = [*self._compose_args, "up", "-d"]
        if setup.services:
            up_cmd.extend(setup.services)

        # Contract v1.0.0 §1: PHANTOM_MODE=1 is set in the environment used to
        # invoke `docker compose up` so Compose interpolation can forward it to
        # the app service. The consumer's compose file MUST propagate it (e.g.
        # `environment: [PHANTOM_MODE]`) — see CONTRACT.md §1 and the smoke-job
        # spec's "what a consumer repo must provide".
        ctx.logger.info("docker_compose_up", command=" ".join(up_cmd))
        result = await run_command(
            *up_cmd,
            cwd=ctx.project_dir,
            env=app_env(run_config.env),
            timeout=setup.runner_timeout,
        )
        if result.returncode != 0:
            # Capture container logs for diagnostics
            logs = await self._capture_compose_logs(ctx)
            raise RunnerLaunchError(
                f"docker compose up failed (exit {result.returncode}).\n"
                f"stderr: {result.stderr[:500]}\n"
                f"Container logs:\n{logs}"
            )

        # Wait for ready check
        ctx.logger.info(
            "launch_ready_check",
            type=ready.type,
            timeout=ready.timeout,
        )

        success = await self._wait_for_ready(ready, ctx, process_died_check=None)
        if not success:
            logs = await self._capture_compose_logs(ctx)
            raise RunnerLaunchError(
                f"Application failed ready check after {ready.timeout}s. "
                f"Type: {ready.type}\n"
                f"Container logs:\n{logs}"
            )

        # Determine base URL
        if ready.type == "http" and ready.url:
            self._base_url = ready.url.rstrip("/")
        elif ready.type == "tcp" and ready.port:
            self._base_url = f"http://localhost:{ready.port}"
        else:
            self._base_url = "http://localhost:3000"

        # Launch browser
        await self._launch_browser()

        ctx.logger.info("launch_complete", base_url=self._base_url)

    async def teardown(self, ctx: RunnerContext) -> None:
        """Stop browser, tear down containers, run teardown commands."""
        # Close browser
        await self._close_browser()

        # Tear down containers
        if self._compose_args:
            down_cmd = [*self._compose_args, "down", "-v", "--remove-orphans"]
            with contextlib.suppress(Exception):
                await run_command(*down_cmd, cwd=ctx.project_dir, timeout=30)

        # Run teardown commands
        teardown_cmds = ctx.manifest.setup.teardown or []
        for cmd in teardown_cmds:
            try:
                await run_shell(cmd, cwd=ctx.project_dir, timeout=10)
            except Exception as e:
                ctx.logger.warning("teardown_command_failed", command=cmd, error=str(e))

        ctx.logger.info("teardown_complete")

    async def _capture_compose_logs(self, ctx: RunnerContext) -> str:
        """Capture docker compose logs for diagnostics."""
        if not self._compose_args:
            return "<no compose args available>"
        logs_cmd = [*self._compose_args, "logs", "--tail=50"]
        try:
            result = await run_command(*logs_cmd, cwd=ctx.project_dir, timeout=10)
            return result.stdout[-2000:] if result.stdout else result.stderr[-2000:]
        except Exception:
            return "<failed to capture logs>"
