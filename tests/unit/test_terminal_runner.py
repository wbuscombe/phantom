"""Unit tests for the Terminal runner.

All system commands (silicon, pty fork) are mocked — no external tools required.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pyte
import pytest

from phantom.exceptions import RunnerSetupError
from phantom.models import (
    KeystrokeAction,
    RendererConfig,
    TypeTextAction,
    WaitAction,
    WaitForAction,
    load_manifest,
)
from phantom.runners.base import RunnerContext
from phantom.runners.terminal import (
    TerminalRunner,
    _build_silicon_args,
    _dump_screen_ansi,
    _key_to_bytes,
    _screen_hash,
)
from phantom.utils.process import ProcessResult

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "test-tui-app"
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
def runner() -> TerminalRunner:
    return TerminalRunner()


# ── Key mapping ──────────────────────────────────────


class TestKeyMapping:
    def test_single_char(self) -> None:
        assert _key_to_bytes("a") == b"a"
        assert _key_to_bytes("Z") == b"Z"
        assert _key_to_bytes("/") == b"/"

    def test_named_keys(self) -> None:
        assert _key_to_bytes("enter") == b"\r"
        assert _key_to_bytes("Enter") == b"\r"
        assert _key_to_bytes("escape") == b"\x1b"
        assert _key_to_bytes("tab") == b"\t"
        assert _key_to_bytes("backspace") == b"\x7f"
        assert _key_to_bytes("space") == b" "

    def test_arrow_keys(self) -> None:
        assert _key_to_bytes("up") == b"\x1b[A"
        assert _key_to_bytes("down") == b"\x1b[B"
        assert _key_to_bytes("left") == b"\x1b[D"
        assert _key_to_bytes("right") == b"\x1b[C"

    def test_ctrl_keys(self) -> None:
        assert _key_to_bytes("ctrl+c") == b"\x03"
        assert _key_to_bytes("ctrl+d") == b"\x04"
        assert _key_to_bytes("ctrl+z") == b"\x1a"

    def test_function_keys(self) -> None:
        assert _key_to_bytes("f1") == b"\x1bOP"
        assert _key_to_bytes("f12") == b"\x1b[24~"


# ── Screen buffer helpers ────────────────────────────


class TestScreenBuffer:
    def test_dump_empty_screen(self) -> None:
        screen = pyte.Screen(10, 3)
        result = _dump_screen_ansi(screen)
        assert result == ""

    def test_dump_with_content(self) -> None:
        screen = pyte.Screen(20, 3)
        stream = pyte.Stream(screen)
        stream.feed("Hello World\r\nLine 2")
        result = _dump_screen_ansi(screen)
        lines = result.split("\n")
        assert lines[0] == "Hello World"
        assert lines[1] == "Line 2"

    def test_trailing_empty_lines_stripped(self) -> None:
        screen = pyte.Screen(20, 10)
        stream = pyte.Stream(screen)
        stream.feed("Only first line")
        result = _dump_screen_ansi(screen)
        assert result == "Only first line"
        assert "\n" not in result

    def test_screen_hash_changes_with_content(self) -> None:
        screen = pyte.Screen(20, 5)
        h1 = _screen_hash(screen)

        stream = pyte.Stream(screen)
        stream.feed("content")
        h2 = _screen_hash(screen)

        assert h1 != h2

    def test_screen_hash_stable_for_same_content(self) -> None:
        s1 = pyte.Screen(20, 5)
        s2 = pyte.Screen(20, 5)
        pyte.Stream(s1).feed("same")
        pyte.Stream(s2).feed("same")

        assert _screen_hash(s1) == _screen_hash(s2)


# ── Silicon command construction ─────────────────────


class TestSiliconArgs:
    def test_default_config(self, tmp_path: Path) -> None:
        config = RendererConfig()
        args = _build_silicon_args(tmp_path / "in.txt", tmp_path / "out.png", config)

        assert args[0] == "silicon"
        assert str(tmp_path / "in.txt") in args
        assert "--output" in args
        assert str(tmp_path / "out.png") in args
        assert "--font" in args
        assert "JetBrains Mono" in args
        assert "--theme" in args
        assert "Catppuccin Mocha" in args
        assert "--no-line-number" in args
        assert "--no-window-controls" not in args
        assert "--pad-horiz" in args
        assert "20" in args
        assert "--background" in args
        assert "#1e1e2e" in args

    def test_custom_config(self, tmp_path: Path) -> None:
        config = RendererConfig(
            font="Fira Code",
            theme="Dracula",
            line_numbers=True,
            padding=30,
            background="#000000",
            window_controls=False,
            corner_radius=0,
        )
        args = _build_silicon_args(tmp_path / "in.txt", tmp_path / "out.png", config)

        assert "Fira Code" in args
        assert "Dracula" in args
        assert "--no-line-number" not in args
        assert "--no-window-controls" in args
        assert "30" in args
        assert "#000000" in args
        # corner_radius=0 means no shadow blur
        assert "--shadow-blur-radius" not in args

    def test_corner_radius_becomes_shadow_blur(self, tmp_path: Path) -> None:
        config = RendererConfig(corner_radius=12)
        args = _build_silicon_args(tmp_path / "in.txt", tmp_path / "out.png", config)
        idx = args.index("--shadow-blur-radius")
        assert args[idx + 1] == "12"


# ── Setup ────────────────────────────────────────────


class TestSetup:
    async def test_setup_checks_silicon(self, runner: TerminalRunner, ctx: RunnerContext) -> None:
        """setup() should verify silicon is available."""
        ok = ProcessResult(returncode=0, stdout="/usr/local/bin/silicon", stderr="")
        with patch("phantom.runners.terminal.run_command", new_callable=AsyncMock, return_value=ok):
            await runner.setup(ctx)

    async def test_setup_fails_without_silicon(
        self, runner: TerminalRunner, ctx: RunnerContext
    ) -> None:
        """setup() should raise RunnerSetupError if silicon is not found."""
        fail = ProcessResult(returncode=1, stdout="", stderr="")
        with (
            patch(
                "phantom.runners.terminal.run_command", new_callable=AsyncMock, return_value=fail
            ),
            pytest.raises(RunnerSetupError, match="silicon is required"),
        ):
            await runner.setup(ctx)

    async def test_setup_runs_build_commands(self, ctx: RunnerContext) -> None:
        """Build commands from the manifest should be executed during setup."""
        ctx.manifest.setup.build = ["make build"]
        runner = TerminalRunner()

        silicon_ok = ProcessResult(returncode=0, stdout="/usr/local/bin/silicon", stderr="")
        build_ok = ProcessResult(returncode=0, stdout="", stderr="")

        with (
            patch(
                "phantom.runners.terminal.run_command",
                new_callable=AsyncMock,
                return_value=silicon_ok,
            ),
            patch(
                "phantom.runners.terminal.run_shell", new_callable=AsyncMock, return_value=build_ok
            ) as mock_shell,
        ):
            await runner.setup(ctx)

        mock_shell.assert_called_once()
        assert mock_shell.call_args[0][0] == "make build"

    async def test_setup_build_failure(self, ctx: RunnerContext) -> None:
        """A failing build command should raise RunnerSetupError."""
        ctx.manifest.setup.build = ["make build"]
        runner = TerminalRunner()

        silicon_ok = ProcessResult(returncode=0, stdout="/usr/local/bin/silicon", stderr="")
        build_fail = ProcessResult(returncode=1, stdout="", stderr="compilation failed")

        with (
            patch(
                "phantom.runners.terminal.run_command",
                new_callable=AsyncMock,
                return_value=silicon_ok,
            ),
            patch(
                "phantom.runners.terminal.run_shell",
                new_callable=AsyncMock,
                return_value=build_fail,
            ),
            pytest.raises(RunnerSetupError, match="Build command failed"),
        ):
            await runner.setup(ctx)


# ── Readiness detection ──────────────────────────────


class TestReadiness:
    async def test_stdout_match_succeeds(self, ctx: RunnerContext) -> None:
        """stdout_match should return True when pattern appears in output."""
        from phantom.models import ReadyCheck

        runner = TerminalRunner()
        runner._output_lines = ["Starting...", "Ready", "Listening"]
        runner._child_pid = 12345

        ready = ReadyCheck(type="stdout_match", pattern="Ready", timeout=1)
        with patch.object(runner, "_child_died", return_value=False):
            result = await runner._wait_for_ready(ready, ctx)
        assert result is True

    async def test_stdout_match_timeout(self, ctx: RunnerContext) -> None:
        """stdout_match should return False on timeout."""
        from phantom.models import ReadyCheck

        runner = TerminalRunner()
        runner._output_lines = ["Starting..."]
        runner._child_pid = 12345

        # Use timeout=1 and interval=1 — the loop checks once then times out
        ready = ReadyCheck(type="stdout_match", pattern="NeverAppears", timeout=1, interval=1)

        # Patch event loop time so deadline is already passed
        fake_time = [0.0]

        def advancing_time() -> float:
            val = fake_time[0]
            fake_time[0] += 2.0  # Jump past deadline on second call
            return val

        loop_mock = MagicMock()
        loop_mock.time = advancing_time
        with (
            patch.object(runner, "_child_died", return_value=False),
            patch("asyncio.get_event_loop", return_value=loop_mock),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await runner._wait_for_ready(ready, ctx)
        assert result is False

    async def test_stdout_match_child_died(self, ctx: RunnerContext) -> None:
        """stdout_match should return False if child process died."""
        from phantom.models import ReadyCheck

        runner = TerminalRunner()
        runner._output_lines = []
        runner._child_pid = 12345

        ready = ReadyCheck(type="stdout_match", pattern="Ready", timeout=5, interval=1)
        with patch.object(runner, "_child_died", return_value=True):
            result = await runner._wait_for_ready(ready, ctx)
        assert result is False

    async def test_screen_stable_succeeds(self, ctx: RunnerContext) -> None:
        """screen_stable should return True when screen stops changing."""
        from phantom.models import ReadyCheck

        runner = TerminalRunner()
        screen = pyte.Screen(80, 24)
        pyte.Stream(screen).feed("Stable content")
        runner._screen = screen
        runner._child_pid = 12345

        ready = ReadyCheck(
            type="screen_stable",
            timeout=2,
            stability_window=200,
            check_interval=50,
        )
        with patch.object(runner, "_child_died", return_value=False):
            result = await runner._wait_for_ready(ready, ctx)
        assert result is True

    async def test_delay_ready_check(self, ctx: RunnerContext) -> None:
        """delay should return True after waiting."""
        from phantom.models import ReadyCheck

        runner = TerminalRunner()
        ready = ReadyCheck(type="delay", seconds=0)
        result = await runner._wait_for_ready(ready, ctx)
        assert result is True


# ── TUI action execution ────────────────────────────


class TestTUIActions:
    async def test_keystroke_action(self, ctx: RunnerContext) -> None:
        """keystroke action should call _send_key."""
        runner = TerminalRunner()
        runner._master_fd = 999
        runner._screen = pyte.Screen(80, 24)

        actions: list[object] = [KeystrokeAction(type="keystroke", key="j")]

        with patch.object(runner, "_send_key") as mock_send:
            await runner._execute_tui_actions(actions, ctx)

        mock_send.assert_called_once_with("j")

    async def test_type_text_action(self, ctx: RunnerContext) -> None:
        """type_text action should send each character with delay."""
        runner = TerminalRunner()
        runner._master_fd = 999
        runner._screen = pyte.Screen(80, 24)

        actions: list[object] = [TypeTextAction(type="type_text", text="hi", delay=10)]

        calls: list[str] = []
        with patch.object(runner, "_send_key", side_effect=lambda k: calls.append(k)):
            await runner._execute_tui_actions(actions, ctx)

        assert calls == ["h", "i"]

    async def test_wait_action(self, ctx: RunnerContext) -> None:
        """wait action should sleep for the specified duration."""
        runner = TerminalRunner()
        runner._master_fd = 999
        runner._screen = pyte.Screen(80, 24)

        actions: list[object] = [WaitAction(type="wait", ms=50)]

        start = asyncio.get_event_loop().time()
        await runner._execute_tui_actions(actions, ctx)
        elapsed = asyncio.get_event_loop().time() - start
        assert elapsed >= 0.04  # at least ~40ms (allowing for scheduling jitter)

    async def test_wait_for_action_screen_pattern(self, ctx: RunnerContext) -> None:
        """wait_for action should check screen content for pattern."""
        runner = TerminalRunner()
        runner._master_fd = 999
        screen = pyte.Screen(80, 24)
        pyte.Stream(screen).feed("Loading...")
        runner._screen = screen

        actions: list[object] = [WaitForAction(type="wait_for", selector="Loading", timeout=1)]

        await runner._execute_tui_actions(actions, ctx)
        # Should return immediately since pattern is on screen


# ── Teardown ─────────────────────────────────────────


class TestTeardown:
    async def test_teardown_kills_process(self, ctx: RunnerContext) -> None:
        """teardown() should send SIGTERM then clean up."""
        runner = TerminalRunner()
        runner._child_pid = 99999
        runner._master_fd = 99

        with (
            patch("os.kill") as mock_kill,
            patch("os.waitpid", return_value=(99999, 0)),
            patch("os.close") as mock_close,
        ):
            await runner.teardown(ctx)

        mock_kill.assert_any_call(99999, __import__("signal").SIGTERM)
        mock_close.assert_called_once_with(99)
        assert runner._child_pid is None
        assert runner._master_fd is None

    async def test_teardown_runs_teardown_commands(self, ctx: RunnerContext) -> None:
        """User-defined teardown commands should be executed."""
        ctx.manifest.setup.teardown = ["echo cleanup"]
        runner = TerminalRunner()

        shell_ok = ProcessResult(returncode=0, stdout="", stderr="")

        with (
            patch(
                "phantom.runners.terminal.run_shell", new_callable=AsyncMock, return_value=shell_ok
            ) as mock_shell,
        ):
            await runner.teardown(ctx)

        mock_shell.assert_called_once()
        assert mock_shell.call_args[0][0] == "echo cleanup"

    async def test_teardown_suppresses_errors(self, ctx: RunnerContext) -> None:
        """Teardown should not raise even if kill/close fails."""
        runner = TerminalRunner()
        runner._child_pid = 99999
        runner._master_fd = 99

        with (
            patch("os.kill", side_effect=ProcessLookupError),
            patch("os.waitpid", side_effect=ChildProcessError),
            patch("os.close", side_effect=OSError),
        ):
            # Should not raise
            await runner.teardown(ctx)


# ── Capture ──────────────────────────────────────────


class TestCapture:
    async def test_capture_writes_text_and_calls_silicon(self, ctx: RunnerContext) -> None:
        """capture() should dump screen to file and invoke silicon."""
        from phantom.models import TUIConfig

        runner = TerminalRunner()
        runner._screen = pyte.Screen(80, 24)
        pyte.Stream(runner._screen).feed("Test Content Here")
        runner._master_fd = 999
        runner._tui_config = TUIConfig()

        resolved = ctx.manifest.resolve_captures()
        target = next(r for r in resolved if r.id == "main-view")

        silicon_ok = ProcessResult(returncode=0, stdout="", stderr="")

        async def fake_run_command(*args: str, **kwargs: object) -> ProcessResult:
            # Create fake output file
            for i, a in enumerate(args):
                if a == "--output" and i + 1 < len(args):
                    Path(args[i + 1]).write_bytes(b"\x89PNG fake image data")
            return silicon_ok

        with (
            patch("phantom.runners.terminal.run_command", side_effect=fake_run_command),
            patch.object(runner, "_send_key"),
        ):
            result = await runner.capture(ctx, target)

        assert result.success
        assert result.output_path is not None
        assert result.output_path.exists()
        assert result.duration_ms > 0

        # Verify text file was created
        text_path = ctx.raw_output_dir / "main-view.txt"
        assert text_path.exists()
        assert "Test Content Here" in text_path.read_text()

    async def test_capture_failure_produces_diagnostic(self, ctx: RunnerContext) -> None:
        """On capture failure, a diagnostic text dump should be saved."""
        from phantom.models import TUIConfig

        runner = TerminalRunner()
        runner._screen = pyte.Screen(80, 24)
        pyte.Stream(runner._screen).feed("Diagnostic content")
        runner._master_fd = 999
        runner._tui_config = TUIConfig()

        resolved = ctx.manifest.resolve_captures()
        target = next(r for r in resolved if r.id == "main-view")

        silicon_fail = ProcessResult(returncode=1, stdout="", stderr="silicon error")

        with (
            patch(
                "phantom.runners.terminal.run_command",
                new_callable=AsyncMock,
                return_value=silicon_fail,
            ),
            patch.object(runner, "_send_key"),
        ):
            result = await runner.capture(ctx, target)

        assert not result.success
        assert result.error is not None
        assert "silicon failed" in result.error

        diag_path = ctx.raw_output_dir / "main-view_diagnostic.txt"
        assert diag_path.exists()
        assert "Diagnostic content" in diag_path.read_text()
