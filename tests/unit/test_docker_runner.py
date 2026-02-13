"""Unit tests for the Docker runner.

All docker/compose commands are mocked — no Docker daemon required.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from phantom.exceptions import RunnerLaunchError, RunnerSetupError
from phantom.models import load_manifest
from phantom.runners.base import RunnerContext
from phantom.runners.docker import DockerRunner
from phantom.utils.process import ProcessResult

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "test-docker-app"
MANIFEST_PATH = FIXTURE_DIR / ".phantom.yml"


@pytest.fixture
def manifest():
    return load_manifest(str(MANIFEST_PATH))


@pytest.fixture
def ctx(manifest, tmp_path: Path) -> RunnerContext:
    raw = tmp_path / "raw"
    raw.mkdir()
    return RunnerContext(
        project_dir=FIXTURE_DIR,
        raw_output_dir=raw,
        manifest=manifest,
    )


@pytest.fixture
def runner() -> DockerRunner:
    return DockerRunner()


# ── Setup ────────────────────────────────────────────


class TestSetup:
    async def test_setup_checks_compose_v2(self, runner: DockerRunner, ctx: RunnerContext) -> None:
        """setup() should call 'docker compose version' and succeed."""
        ok = ProcessResult(returncode=0, stdout="Docker Compose version v2.24.0", stderr="")
        with patch("phantom.runners.docker.run_command", new_callable=AsyncMock, return_value=ok):
            await runner.setup(ctx)

        assert runner._compose_args == [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
        ]

    async def test_setup_fails_without_compose_v2(
        self, runner: DockerRunner, ctx: RunnerContext
    ) -> None:
        """setup() should raise RunnerSetupError if compose v2 is unavailable."""
        fail = ProcessResult(returncode=1, stdout="", stderr="unknown command")
        with (
            patch("phantom.runners.docker.run_command", new_callable=AsyncMock, return_value=fail),
            pytest.raises(RunnerSetupError, match="Docker Compose v2"),
        ):
            await runner.setup(ctx)

    async def test_setup_runs_build_commands(self, ctx: RunnerContext) -> None:
        """Build commands from the manifest should be executed during setup."""
        ctx.manifest.setup.build = ["docker compose build"]
        runner = DockerRunner()

        compose_ok = ProcessResult(returncode=0, stdout="v2.24.0", stderr="")
        build_ok = ProcessResult(returncode=0, stdout="", stderr="")

        with (
            patch(
                "phantom.runners.docker.run_command",
                new_callable=AsyncMock,
                return_value=compose_ok,
            ),
            patch(
                "phantom.runners.docker.run_shell", new_callable=AsyncMock, return_value=build_ok
            ) as mock_shell,
        ):
            await runner.setup(ctx)

        mock_shell.assert_called_once()
        call_args = mock_shell.call_args
        assert call_args[0][0] == "docker compose build"

    async def test_setup_build_command_failure(self, ctx: RunnerContext) -> None:
        """A failing build command should raise RunnerSetupError."""
        ctx.manifest.setup.build = ["docker compose build"]
        runner = DockerRunner()

        compose_ok = ProcessResult(returncode=0, stdout="v2.24.0", stderr="")
        build_fail = ProcessResult(returncode=1, stdout="", stderr="build failed")

        with (
            patch(
                "phantom.runners.docker.run_command",
                new_callable=AsyncMock,
                return_value=compose_ok,
            ),
            patch(
                "phantom.runners.docker.run_shell", new_callable=AsyncMock, return_value=build_fail
            ),
            pytest.raises(RunnerSetupError, match="Build command failed"),
        ):
            await runner.setup(ctx)

    async def test_setup_with_profiles(self, ctx: RunnerContext) -> None:
        """Compose profiles should be included in _compose_args."""
        ctx.manifest.setup.compose_profiles = ["dev", "debug"]
        runner = DockerRunner()

        ok = ProcessResult(returncode=0, stdout="v2.24.0", stderr="")
        with patch("phantom.runners.docker.run_command", new_callable=AsyncMock, return_value=ok):
            await runner.setup(ctx)

        assert runner._compose_args == [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "--profile",
            "dev",
            "--profile",
            "debug",
        ]


# ── Launch ───────────────────────────────────────────


class TestLaunch:
    async def _setup_runner(self, runner: DockerRunner, ctx: RunnerContext) -> None:
        """Helper to run setup with mocked compose check."""
        ok = ProcessResult(returncode=0, stdout="v2.24.0", stderr="")
        with patch("phantom.runners.docker.run_command", new_callable=AsyncMock, return_value=ok):
            await runner.setup(ctx)

    async def test_launch_constructs_up_command(
        self, runner: DockerRunner, ctx: RunnerContext
    ) -> None:
        """launch() should run 'docker compose -f <file> up -d'."""
        await self._setup_runner(runner, ctx)

        up_ok = ProcessResult(returncode=0, stdout="", stderr="")
        calls: list[tuple[str, ...]] = []

        async def track_run_command(*args: str, **kwargs: object) -> ProcessResult:
            calls.append(args)
            return up_ok

        with (
            patch("phantom.runners.docker.run_command", side_effect=track_run_command),
            patch.object(runner, "_wait_for_ready", new_callable=AsyncMock, return_value=True),
            patch.object(runner, "_launch_browser", new_callable=AsyncMock),
        ):
            await runner.launch(ctx)

        # First call should be the up command
        assert calls[0] == ("docker", "compose", "-f", "docker-compose.yml", "up", "-d")

    async def test_launch_with_services(self, runner: DockerRunner, ctx: RunnerContext) -> None:
        """Specified services should be appended to the up command."""
        ctx.manifest.setup.services = ["web", "api"]
        await self._setup_runner(runner, ctx)

        up_ok = ProcessResult(returncode=0, stdout="", stderr="")
        calls: list[tuple[str, ...]] = []

        async def track_run_command(*args: str, **kwargs: object) -> ProcessResult:
            calls.append(args)
            return up_ok

        with (
            patch("phantom.runners.docker.run_command", side_effect=track_run_command),
            patch.object(runner, "_wait_for_ready", new_callable=AsyncMock, return_value=True),
            patch.object(runner, "_launch_browser", new_callable=AsyncMock),
        ):
            await runner.launch(ctx)

        assert calls[0] == (
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "up",
            "-d",
            "web",
            "api",
        )

    async def test_launch_failure_captures_logs(
        self, runner: DockerRunner, ctx: RunnerContext
    ) -> None:
        """When 'up' fails, container logs should be included in the error."""
        await self._setup_runner(runner, ctx)

        up_fail = ProcessResult(returncode=1, stdout="", stderr="port conflict")
        logs_result = ProcessResult(returncode=0, stdout="container log output", stderr="")

        call_count = 0

        async def mock_run_command(*args: str, **kwargs: object) -> ProcessResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return up_fail
            return logs_result

        with (
            patch("phantom.runners.docker.run_command", side_effect=mock_run_command),
            pytest.raises(RunnerLaunchError, match="container log output"),
        ):
            await runner.launch(ctx)

    async def test_ready_check_timeout_captures_logs(
        self, runner: DockerRunner, ctx: RunnerContext
    ) -> None:
        """When ready check times out, container logs should be in the error."""
        await self._setup_runner(runner, ctx)

        up_ok = ProcessResult(returncode=0, stdout="", stderr="")
        logs_result = ProcessResult(returncode=0, stdout="timeout logs here", stderr="")

        call_count = 0

        async def mock_run_command(*args: str, **kwargs: object) -> ProcessResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return up_ok
            return logs_result

        with (
            patch("phantom.runners.docker.run_command", side_effect=mock_run_command),
            patch.object(runner, "_wait_for_ready", new_callable=AsyncMock, return_value=False),
            pytest.raises(RunnerLaunchError, match="timeout logs here"),
        ):
            await runner.launch(ctx)

    async def test_base_url_from_http_ready_check(
        self, runner: DockerRunner, ctx: RunnerContext
    ) -> None:
        """base_url should be set from the HTTP ready check URL."""
        await self._setup_runner(runner, ctx)

        up_ok = ProcessResult(returncode=0, stdout="", stderr="")
        with (
            patch("phantom.runners.docker.run_command", new_callable=AsyncMock, return_value=up_ok),
            patch.object(runner, "_wait_for_ready", new_callable=AsyncMock, return_value=True),
            patch.object(runner, "_launch_browser", new_callable=AsyncMock),
        ):
            await runner.launch(ctx)

        assert runner._base_url == "http://localhost:9754"

    async def test_base_url_from_tcp_ready_check(self, ctx: RunnerContext) -> None:
        """base_url should be http://localhost:<port> for TCP ready checks."""
        ctx.manifest.setup.run.ready_check.type = "tcp"
        ctx.manifest.setup.run.ready_check.port = 8080
        ctx.manifest.setup.run.ready_check.url = None
        runner = DockerRunner()

        ok = ProcessResult(returncode=0, stdout="v2.24.0", stderr="")
        with patch("phantom.runners.docker.run_command", new_callable=AsyncMock, return_value=ok):
            await runner.setup(ctx)

        up_ok = ProcessResult(returncode=0, stdout="", stderr="")
        with (
            patch("phantom.runners.docker.run_command", new_callable=AsyncMock, return_value=up_ok),
            patch.object(runner, "_wait_for_ready", new_callable=AsyncMock, return_value=True),
            patch.object(runner, "_launch_browser", new_callable=AsyncMock),
        ):
            await runner.launch(ctx)

        assert runner._base_url == "http://localhost:8080"


# ── Teardown ─────────────────────────────────────────


class TestTeardown:
    async def test_teardown_calls_compose_down(
        self, runner: DockerRunner, ctx: RunnerContext
    ) -> None:
        """teardown() should run 'docker compose down -v --remove-orphans'."""
        # Simulate a setup so _compose_args is populated
        runner._compose_args = ["docker", "compose", "-f", "docker-compose.yml"]

        calls: list[tuple[str, ...]] = []

        async def track_run_command(*args: str, **kwargs: object) -> ProcessResult:
            calls.append(args)
            return ProcessResult(returncode=0, stdout="", stderr="")

        with (
            patch("phantom.runners.docker.run_command", side_effect=track_run_command),
            patch.object(runner, "_close_browser", new_callable=AsyncMock),
        ):
            await runner.teardown(ctx)

        assert any(
            args
            == ("docker", "compose", "-f", "docker-compose.yml", "down", "-v", "--remove-orphans")
            for args in calls
        )

    async def test_teardown_runs_teardown_commands(self, ctx: RunnerContext) -> None:
        """User-defined teardown commands should be executed."""
        ctx.manifest.setup.teardown = ["echo cleanup"]
        runner = DockerRunner()
        runner._compose_args = ["docker", "compose", "-f", "docker-compose.yml"]

        down_ok = ProcessResult(returncode=0, stdout="", stderr="")
        shell_ok = ProcessResult(returncode=0, stdout="", stderr="")

        with (
            patch(
                "phantom.runners.docker.run_command", new_callable=AsyncMock, return_value=down_ok
            ),
            patch(
                "phantom.runners.docker.run_shell", new_callable=AsyncMock, return_value=shell_ok
            ) as mock_shell,
            patch.object(runner, "_close_browser", new_callable=AsyncMock),
        ):
            await runner.teardown(ctx)

        mock_shell.assert_called_once()
        assert mock_shell.call_args[0][0] == "echo cleanup"

    async def test_teardown_suppresses_errors(self, ctx: RunnerContext) -> None:
        """Teardown should not raise even if compose down fails."""
        runner = DockerRunner()
        runner._compose_args = ["docker", "compose", "-f", "docker-compose.yml"]

        async def failing_command(*args: str, **kwargs: object) -> ProcessResult:
            raise RuntimeError("docker daemon not responding")

        with (
            patch("phantom.runners.docker.run_command", side_effect=failing_command),
            patch.object(runner, "_close_browser", new_callable=AsyncMock),
        ):
            # Should not raise
            await runner.teardown(ctx)
