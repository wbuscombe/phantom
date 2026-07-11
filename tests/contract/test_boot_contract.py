"""CONTRACT.md §1 — Boot contract.

Phantom GUARANTEES ``PHANTOM_MODE=1`` in a launched consumer app's environment
for every capture, regardless of the shell that invoked Phantom. These tests
verify the guarantee at the helper level and mechanically at each runner's
spawn point (web, docker-compose, tui, desktop) with all system tools mocked.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from phantom import contract
from phantom.models import load_manifest
from phantom.runners.base import RunnerContext

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


# ── is_phantom_mode() ─────────────────────────────────


class TestModeDetection:
    def test_value_1_is_on(self) -> None:
        assert contract.is_phantom_mode({"PHANTOM_MODE": "1"}) is True

    @pytest.mark.parametrize("value", ["0", "true", "yes", "", "01", " 1"])
    def test_other_values_are_off(self, value: str) -> None:
        assert contract.is_phantom_mode({"PHANTOM_MODE": value}) is False

    def test_unset_is_off(self) -> None:
        assert contract.is_phantom_mode({}) is False


# ── app_env() precedence ──────────────────────────────


class TestAppEnvGuarantee:
    def test_injects_phantom_mode_when_absent(self) -> None:
        assert contract.app_env()["PHANTOM_MODE"] == "1"
        assert contract.app_env(None)["PHANTOM_MODE"] == "1"
        assert contract.app_env({})["PHANTOM_MODE"] == "1"

    def test_preserves_other_manifest_env(self) -> None:
        env = contract.app_env({"API_URL": "http://localhost:9"})
        assert env["PHANTOM_MODE"] == "1"
        assert env["API_URL"] == "http://localhost:9"

    def test_default_overrides_inherited_base(self) -> None:
        # Even if the invoking shell set PHANTOM_MODE=0, Phantom forces it on.
        env = contract.app_env(base={"PHANTOM_MODE": "0", "HOME": "/home/x"})
        assert env["PHANTOM_MODE"] == "1"
        assert env["HOME"] == "/home/x"

    def test_manifest_run_env_may_override(self) -> None:
        # Explicit manifest run.env is the documented escape hatch (highest
        # precedence) — CONTRACT.md §1.
        env = contract.app_env({"PHANTOM_MODE": "0"})
        assert env["PHANTOM_MODE"] == "0"

    def test_does_not_mutate_inputs(self) -> None:
        run_env = {"A": "1"}
        base = {"B": "2"}
        contract.app_env(run_env, base)
        assert run_env == {"A": "1"}
        assert base == {"B": "2"}


# ── Runner spawn-point injection ──────────────────────


def _web_ctx(tmp_path: Path) -> RunnerContext:
    manifest = load_manifest(str(FIXTURES_DIR / "test-web-app" / ".phantom.yml"))
    # The shipped web manifest declares no run.env, so any PHANTOM_MODE seen by
    # the child proves Phantom injected it.
    assert manifest.setup.run.env is None
    raw = tmp_path / "raw"
    raw.mkdir()
    return RunnerContext(project_dir=tmp_path, raw_output_dir=raw, manifest=manifest)


class TestWebRunnerInjection:
    @pytest.mark.asyncio
    async def test_web_launch_sets_phantom_mode(self, tmp_path: Path) -> None:
        from phantom.runners.web import WebRunner

        runner = WebRunner()
        ctx = _web_ctx(tmp_path)

        fake_proc = MagicMock()
        fake_proc.process.returncode = None
        fake_proc.stdout_lines = []
        fake_proc.stderr_lines = []

        with (
            patch(
                "phantom.runners.web.start_process",
                new_callable=AsyncMock,
                return_value=fake_proc,
            ) as mock_start,
            patch.object(WebRunner, "_wait_for_ready", new_callable=AsyncMock, return_value=True),
            patch.object(WebRunner, "_launch_browser", new_callable=AsyncMock),
        ):
            await runner.launch(ctx)

        env = mock_start.call_args.kwargs["env"]
        assert env["PHANTOM_MODE"] == "1"


class TestDockerRunnerInjection:
    @pytest.mark.asyncio
    async def test_docker_up_env_sets_phantom_mode(self, tmp_path: Path) -> None:
        from phantom.runners.docker import DockerRunner

        manifest = load_manifest(str(FIXTURES_DIR / "test-docker-app" / ".phantom.yml"))
        raw = tmp_path / "raw"
        raw.mkdir()
        ctx = RunnerContext(project_dir=tmp_path, raw_output_dir=raw, manifest=manifest)

        runner = DockerRunner()
        runner._compose_args = ["docker", "compose", "-f", "docker-compose.yml"]

        up_calls: list[dict[str, object]] = []

        async def fake_run_command(*args: str, **kwargs: object):
            if "up" in args:
                up_calls.append(kwargs)
            return MagicMock(returncode=0)

        with (
            patch("phantom.runners.docker.run_command", side_effect=fake_run_command),
            patch.object(
                DockerRunner, "_wait_for_ready", new_callable=AsyncMock, return_value=True
            ),
            patch.object(DockerRunner, "_launch_browser", new_callable=AsyncMock),
        ):
            await runner.launch(ctx)

        assert up_calls, "docker compose up was never invoked"
        env = up_calls[0]["env"]
        assert isinstance(env, dict)
        assert env["PHANTOM_MODE"] == "1"


class TestTerminalRunnerInjection:
    @pytest.mark.asyncio
    async def test_tui_exec_env_sets_phantom_mode(self, tmp_path: Path) -> None:
        from phantom.runners.terminal import TerminalRunner

        manifest = load_manifest(str(FIXTURES_DIR / "test-tui-app" / ".phantom.yml"))
        raw = tmp_path / "raw"
        raw.mkdir()
        ctx = RunnerContext(project_dir=tmp_path, raw_output_dir=raw, manifest=manifest)

        runner = TerminalRunner()
        captured: dict[str, object] = {}

        class _StopExecError(Exception):
            pass

        def fake_execvpe(file: str, argv: list[str], env: dict[str, str]) -> None:
            captured["env"] = env
            raise _StopExecError

        # pty.fork -> (0, fd) forces the child branch, which execs the app.
        with (
            patch("phantom.runners.terminal.pty.fork", return_value=(0, 7)),
            patch("phantom.runners.terminal.os.chdir"),
            patch("phantom.runners.terminal.os.execvpe", side_effect=fake_execvpe),
            pytest.raises(_StopExecError),
        ):
            await runner.launch(ctx)

        env = captured["env"]
        assert isinstance(env, dict)
        assert env["PHANTOM_MODE"] == "1"


class TestDesktopRunnerInjection:
    @pytest.mark.asyncio
    async def test_desktop_app_env_sets_phantom_mode(self, tmp_path: Path) -> None:
        from phantom.runners.desktop import DesktopRunner

        # No desktop fixture manifest ships, so build a minimal mock ctx with no
        # run.env (proving injection) — mirrors tests/unit/test_desktop_runner.
        manifest = MagicMock()
        manifest.setup.type = "desktop"
        manifest.setup.run.command = "./myapp"
        manifest.setup.run.env = None
        manifest.setup.run.ready_check.type = "delay"
        manifest.setup.run.ready_check.seconds = 0
        manifest.setup.run.ready_check.timeout = 5
        manifest.desktop = None

        ctx = MagicMock(spec=RunnerContext)
        ctx.project_dir = tmp_path
        ctx.raw_output_dir = tmp_path
        ctx.manifest = manifest
        ctx.logger = MagicMock()

        runner = DesktopRunner()
        xvfb_proc = MagicMock(returncode=None)  # Xvfb "still running"
        app_proc = MagicMock()

        with (
            patch(
                "phantom.runners.desktop.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=xvfb_proc,
            ),
            patch("phantom.runners.desktop.asyncio.sleep", new_callable=AsyncMock),
            patch(
                "phantom.runners.desktop.asyncio.create_subprocess_shell",
                new_callable=AsyncMock,
                return_value=app_proc,
            ) as mock_shell,
            patch.object(
                DesktopRunner, "_wait_for_ready", new_callable=AsyncMock, return_value=True
            ),
        ):
            await runner.launch(ctx)

        env = mock_shell.call_args.kwargs["env"]
        assert env["PHANTOM_MODE"] == "1"
