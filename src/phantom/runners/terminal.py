"""Terminal runner for capturing TUI application screenshots.

Allocates a pseudo-terminal, launches the TUI app, interacts via keystrokes,
reads the screen buffer with pyte, and renders ANSI → PNG via silicon.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import os
import pty
import select
import signal
import struct
import termios
import time
import zlib
from typing import TYPE_CHECKING

import pyte
import structlog

from phantom.conductor.requirements import check_requirements
from phantom.exceptions import RunnerLaunchError, RunnerSetupError
from phantom.runners.base import BaseRunner, CaptureResult, RunnerContext
from phantom.utils.process import run_command, run_shell

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from phantom.models import (
        ReadyCheck,
        RendererConfig,
        ResolvedCapture,
        TUIConfig,
    )

logger = structlog.get_logger()

# Map human-readable key names to terminal escape sequences.
_KEY_MAP: dict[str, str] = {
    "enter": "\r",
    "return": "\r",
    "tab": "\t",
    "escape": "\x1b",
    "esc": "\x1b",
    "backspace": "\x7f",
    "delete": "\x1b[3~",
    "up": "\x1b[A",
    "down": "\x1b[B",
    "right": "\x1b[C",
    "left": "\x1b[D",
    "home": "\x1b[H",
    "end": "\x1b[F",
    "page_up": "\x1b[5~",
    "pageup": "\x1b[5~",
    "page_down": "\x1b[6~",
    "pagedown": "\x1b[6~",
    "f1": "\x1bOP",
    "f2": "\x1bOQ",
    "f3": "\x1bOR",
    "f4": "\x1bOS",
    "f5": "\x1b[15~",
    "f6": "\x1b[17~",
    "f7": "\x1b[18~",
    "f8": "\x1b[19~",
    "f9": "\x1b[20~",
    "f10": "\x1b[21~",
    "f11": "\x1b[23~",
    "f12": "\x1b[24~",
    "space": " ",
    "ctrl+c": "\x03",
    "ctrl+d": "\x04",
    "ctrl+z": "\x1a",
    "ctrl+l": "\x0c",
}


def _key_to_bytes(key: str) -> bytes:
    """Convert a key name or literal character to bytes for pty write."""
    mapped = _KEY_MAP.get(key.lower())
    if mapped is not None:
        return mapped.encode("utf-8")
    # Single character — send as-is
    if len(key) == 1:
        return key.encode("utf-8")
    # ctrl+<char> pattern
    if key.lower().startswith("ctrl+") and len(key) == 6:
        char = key[-1].lower()
        code = ord(char) - ord("a") + 1
        return bytes([code])
    # Unknown — send as-is
    return key.encode("utf-8")


def _dump_screen_ansi(screen: pyte.Screen) -> str:
    """Dump the pyte screen buffer as plain text (no ANSI — silicon uses plain text)."""
    lines: list[str] = []
    for row in range(screen.lines):
        chars: list[str] = []
        for col in range(screen.columns):
            char = screen.buffer[row][col]
            chars.append(char.data if char.data else " ")
        lines.append("".join(chars).rstrip())
    # Remove trailing empty lines
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _screen_hash(screen: pyte.Screen) -> int:
    """CRC32 hash of the screen buffer for stability detection."""
    content = _dump_screen_ansi(screen)
    return zlib.crc32(content.encode("utf-8"))


def _build_silicon_args(
    input_path: Path,
    output_path: Path,
    renderer_config: RendererConfig,
) -> list[str]:
    """Build the silicon command-line arguments from renderer config."""
    args = [
        "silicon",
        str(input_path),
        "--output",
        str(output_path),
        "--font",
        renderer_config.font,
        "--theme",
        renderer_config.theme,
        "--pad-horiz",
        str(renderer_config.padding),
        "--pad-vert",
        str(renderer_config.padding),
        "--background",
        renderer_config.background,
    ]
    if not renderer_config.line_numbers:
        args.append("--no-line-number")
    if not renderer_config.window_controls:
        args.append("--no-window-controls")
    if renderer_config.corner_radius > 0:
        args.extend(["--shadow-blur-radius", str(renderer_config.corner_radius)])
    return args


class TerminalRunner(BaseRunner):
    """Runner for TUI applications using pyte + silicon."""

    def __init__(self) -> None:
        self._master_fd: int | None = None
        self._child_pid: int | None = None
        self._screen: pyte.Screen | None = None
        self._stream: pyte.Stream | None = None
        self._tui_config: TUIConfig | None = None
        self._output_lines: list[str] = []
        self._reader_task: asyncio.Task[None] | None = None

    async def setup(self, ctx: RunnerContext) -> None:
        """Check requirements and run build commands."""
        setup = ctx.manifest.setup

        if setup.requires:
            await check_requirements(setup.requires)

        # Verify silicon is available
        result = await run_command("which", "silicon", timeout=5)
        if result.returncode != 0:
            raise RunnerSetupError(
                "silicon is required for TUI captures but was not found on PATH.\n"
                "Install it: https://github.com/Aloxaf/silicon\n"
                "  brew install silicon  (macOS)\n"
                "  cargo install silicon (from source)"
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
        """Allocate PTY, launch TUI app, and wait for readiness."""
        from phantom.models import TUIConfig

        setup = ctx.manifest.setup
        run_config = setup.run
        ready = run_config.ready_check

        tui_config = ctx.manifest.tui or TUIConfig()
        self._tui_config = tui_config
        term_width = tui_config.terminal.width
        term_height = tui_config.terminal.height

        # Set up pyte screen + stream
        screen = pyte.Screen(term_width, term_height)
        stream = pyte.Stream(screen)
        self._screen = screen
        self._stream = stream

        # Fork with pty
        env = {**os.environ, **(run_config.env or {})}
        env["TERM"] = "xterm-256color"
        env["COLUMNS"] = str(term_width)
        env["LINES"] = str(term_height)

        pid, master_fd = pty.fork()
        if pid == 0:
            # Child process — exec the TUI app
            os.chdir(str(ctx.project_dir))
            os.execvpe("/bin/sh", ["/bin/sh", "-c", run_config.command], env)
            # unreachable

        self._master_fd = master_fd
        self._child_pid = pid

        # Set terminal size
        winsize = struct.pack("HHHH", term_height, term_width, 0, 0)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)

        # Set fd to non-blocking
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        # Start background reader task
        self._reader_task = asyncio.create_task(self._pty_reader_loop())

        ctx.logger.info(
            "launch_pty",
            pid=pid,
            width=term_width,
            height=term_height,
            command=run_config.command,
        )

        # Wait for readiness
        ctx.logger.info(
            "launch_ready_check",
            type=ready.type,
            timeout=ready.timeout,
        )

        success = await self._wait_for_ready(ready, ctx)
        if not success:
            output = "\n".join(self._output_lines[-20:])
            screen_dump = _dump_screen_ansi(self._screen) if self._screen else ""
            raise RunnerLaunchError(
                f"TUI application failed ready check after {ready.timeout}s. "
                f"Type: {ready.type}\n"
                f"Output (last 20 lines):\n{output}\n"
                f"Screen:\n{screen_dump}"
            )

        ctx.logger.info("launch_complete")

    async def _pty_reader_loop(self) -> None:
        """Background task that reads from the PTY fd and feeds pyte."""
        while self._master_fd is not None:
            try:
                # Use select to check if data is available
                readable, _, _ = select.select([self._master_fd], [], [], 0)
                if readable:
                    data = os.read(self._master_fd, 65536)
                    if not data:
                        break
                    text = data.decode("utf-8", errors="replace")
                    if self._stream is not None:
                        self._stream.feed(text)
                    for line in text.splitlines():
                        stripped = line.strip()
                        if stripped:
                            self._output_lines.append(stripped)
                else:
                    # Yield to event loop
                    await asyncio.sleep(0.02)
            except OSError:
                break
            except asyncio.CancelledError:
                break

    async def _wait_for_ready(self, ready_check: ReadyCheck, ctx: RunnerContext) -> bool:
        """Poll until the TUI app is ready or timeout is reached."""
        deadline = asyncio.get_event_loop().time() + ready_check.timeout

        match ready_check.type:
            case "stdout_match":
                assert ready_check.pattern is not None
                while asyncio.get_event_loop().time() < deadline:
                    if self._child_died():
                        return False
                    for line in self._output_lines:
                        if ready_check.pattern in line:
                            return True
                    await asyncio.sleep(0.1)
                return False

            case "screen_stable":
                check_ms = ready_check.check_interval
                window_ms = ready_check.stability_window
                samples_needed = max(1, window_ms // check_ms)
                last_hash: int | None = None
                stable_count = 0

                while asyncio.get_event_loop().time() < deadline:
                    if self._child_died():
                        return False
                    await asyncio.sleep(check_ms / 1000.0)
                    if self._screen is None:
                        continue
                    h = _screen_hash(self._screen)
                    if h == last_hash:
                        stable_count += 1
                        if stable_count >= samples_needed:
                            return True
                    else:
                        stable_count = 1
                        last_hash = h
                return False

            case "delay":
                assert ready_check.seconds is not None
                await asyncio.sleep(ready_check.seconds)
                return True

            case _:
                # http/tcp not meaningful for TUI — just wait the timeout
                await asyncio.sleep(ready_check.timeout)
                return False

    def _child_died(self) -> bool:
        """Check if the child process has exited."""
        if self._child_pid is None:
            return True
        try:
            pid, _ = os.waitpid(self._child_pid, os.WNOHANG)
            return pid != 0
        except ChildProcessError:
            return True

    async def capture(self, ctx: RunnerContext, capture_def: ResolvedCapture) -> CaptureResult:
        """Execute TUI actions and render screen to PNG via silicon."""
        start = time.monotonic()
        capture_id = capture_def.id

        try:
            assert self._screen is not None
            assert self._master_fd is not None
            assert self._tui_config is not None

            # Execute actions
            if capture_def.actions:
                await self._execute_tui_actions(capture_def.actions, ctx)

            # Wait after actions
            if capture_def.wait_after_actions > 0:
                await asyncio.sleep(capture_def.wait_after_actions / 1000.0)

            # Drain any pending PTY output
            await asyncio.sleep(0.1)

            # Dump screen to text file
            screen_text = _dump_screen_ansi(self._screen)
            text_path = ctx.raw_output_dir / f"{capture_id}.txt"
            text_path.write_text(screen_text, encoding="utf-8")

            # Render via silicon
            output_path = ctx.raw_output_dir / f"{capture_id}.png"
            silicon_args = _build_silicon_args(
                text_path, output_path, self._tui_config.renderer_config
            )

            ctx.logger.debug("silicon_render", args=" ".join(silicon_args))
            result = await run_command(*silicon_args, timeout=30)
            if result.returncode != 0:
                raise RuntimeError(
                    f"silicon failed (exit {result.returncode}): {result.stderr[:500]}"
                )

            if not output_path.exists():
                raise RuntimeError(f"silicon did not produce output file: {output_path}")

            elapsed = int((time.monotonic() - start) * 1000)
            return CaptureResult(
                capture_id=capture_id,
                success=True,
                output_path=output_path,
                duration_ms=elapsed,
            )

        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            ctx.logger.error(
                "capture_failed",
                capture_id=capture_id,
                error=str(e),
            )

            # Dump screen state for diagnostics
            try:
                if self._screen is not None:
                    diag_text = _dump_screen_ansi(self._screen)
                    diag_path = ctx.raw_output_dir / f"{capture_id}_diagnostic.txt"
                    diag_path.write_text(diag_text, encoding="utf-8")
                    ctx.logger.info("diagnostic_dump", path=str(diag_path))
            except Exception:
                pass

            return CaptureResult(
                capture_id=capture_id,
                success=False,
                error=str(e),
                duration_ms=elapsed,
            )

    async def _execute_tui_actions(
        self,
        actions: Sequence[object],
        ctx: RunnerContext,
    ) -> None:
        """Execute TUI-relevant actions against the PTY."""
        from phantom.models import KeystrokeAction, TypeTextAction, WaitAction, WaitForAction

        for action in actions:
            match action:
                case KeystrokeAction():
                    self._send_key(action.key)
                    await asyncio.sleep(0.05)

                case TypeTextAction():
                    for char in action.text:
                        self._send_key(char)
                        await asyncio.sleep(action.delay / 1000.0)

                case WaitAction():
                    await asyncio.sleep(action.ms / 1000.0)

                case WaitForAction():
                    # For TUI: wait for text pattern on screen
                    deadline = asyncio.get_event_loop().time() + action.timeout
                    while asyncio.get_event_loop().time() < deadline:
                        if self._screen is not None:
                            screen_text = _dump_screen_ansi(self._screen)
                            if action.selector in screen_text:
                                break
                        await asyncio.sleep(0.1)

                case _:
                    ctx.logger.warning(
                        "tui_action_unsupported",
                        type=getattr(action, "type", "unknown"),
                    )

    def _send_key(self, key: str) -> None:
        """Send a keystroke to the PTY."""
        if self._master_fd is None:
            return
        data = _key_to_bytes(key)
        with contextlib.suppress(OSError):
            os.write(self._master_fd, data)

    async def teardown(self, ctx: RunnerContext) -> None:
        """Kill the TUI process and clean up the PTY."""
        # Kill child process FIRST, while reader task still drains the PTY.
        # Curses apps write terminal-restore sequences on exit — if nobody
        # reads the master fd the child blocks and never terminates.
        if self._child_pid is not None:
            with contextlib.suppress(Exception):
                os.kill(self._child_pid, signal.SIGTERM)
            try:
                for _ in range(50):  # 5 seconds
                    pid, _ = os.waitpid(self._child_pid, os.WNOHANG)
                    if pid != 0:
                        break
                    await asyncio.sleep(0.1)
                else:
                    with contextlib.suppress(Exception):
                        os.kill(self._child_pid, signal.SIGKILL)
                    with contextlib.suppress(Exception):
                        os.waitpid(self._child_pid, 0)
            except ChildProcessError:
                pass
            self._child_pid = None

        # Now cancel reader task (child is dead, no more PTY output)
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(Exception):
                await self._reader_task
            self._reader_task = None

        # Close master fd
        if self._master_fd is not None:
            with contextlib.suppress(Exception):
                os.close(self._master_fd)
            self._master_fd = None

        # Run teardown commands
        teardown_cmds = ctx.manifest.setup.teardown or []
        for cmd in teardown_cmds:
            try:
                await run_shell(cmd, cwd=ctx.project_dir, timeout=10)
            except Exception as e:
                ctx.logger.warning("teardown_command_failed", command=cmd, error=str(e))

        self._screen = None
        self._stream = None
        self._tui_config = None
        self._output_lines = []

        ctx.logger.info("teardown_complete")
