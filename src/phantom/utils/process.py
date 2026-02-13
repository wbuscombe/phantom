"""Async subprocess helpers with timeout, output capture, and logging."""

from __future__ import annotations

import asyncio
import signal
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from pathlib import Path

logger = structlog.get_logger()


@dataclass
class ProcessResult:
    """Result of an async subprocess execution."""

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    duration_ms: int = 0


@dataclass
class ManagedProcess:
    """A long-running process managed by Phantom (e.g., dev server)."""

    process: asyncio.subprocess.Process
    command: str
    stdout_lines: list[str] = field(default_factory=list)
    stderr_lines: list[str] = field(default_factory=list)
    _reader_tasks: list[asyncio.Task[None]] = field(default_factory=list)

    async def _read_stream(
        self,
        stream: asyncio.StreamReader | None,
        target: list[str],
        label: str,
    ) -> None:
        if stream is None:
            return
        while True:
            line_bytes = await stream.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="replace").rstrip()
            target.append(line)
            logger.debug("process_output", stream=label, line=line)

    def start_readers(self) -> None:
        self._reader_tasks = [
            asyncio.create_task(
                self._read_stream(self.process.stdout, self.stdout_lines, "stdout")
            ),
            asyncio.create_task(
                self._read_stream(self.process.stderr, self.stderr_lines, "stderr")
            ),
        ]

    async def wait_for_output(self, pattern: str, timeout: float) -> bool:
        """Wait until a line matching `pattern` appears in stdout or stderr."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            for line in self.stdout_lines + self.stderr_lines:
                if pattern in line:
                    return True
            await asyncio.sleep(0.1)
        return False

    async def kill(self) -> None:
        """Terminate the managed process and all children."""
        if self.process.returncode is not None:
            return
        try:
            self.process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        except ProcessLookupError:
            pass
        for task in self._reader_tasks:
            task.cancel()


async def run_command(
    *args: str,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 120,
) -> ProcessResult:
    """Run a command and return its result.

    Args:
        *args: Command and arguments.
        cwd: Working directory.
        env: Environment variables (merged with current env).
        timeout: Maximum seconds to wait.

    Returns:
        ProcessResult with stdout, stderr, return code, and timing.
    """
    import os
    import time

    merged_env = {**os.environ, **(env or {})}
    cmd_str = " ".join(args)
    logger.debug("run_command", command=cmd_str, cwd=str(cwd))

    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=merged_env,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            elapsed = int((time.monotonic() - start) * 1000)
            logger.warning("command_timeout", command=cmd_str, timeout=timeout)
            return ProcessResult(
                returncode=-1,
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                timed_out=True,
                duration_ms=elapsed,
            )

        elapsed = int((time.monotonic() - start) * 1000)
        result = ProcessResult(
            returncode=proc.returncode or 0,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            duration_ms=elapsed,
        )

        if result.returncode != 0:
            logger.warning(
                "command_failed",
                command=cmd_str,
                returncode=result.returncode,
                stderr=result.stderr[:500],
            )

        return result

    except FileNotFoundError:
        elapsed = int((time.monotonic() - start) * 1000)
        return ProcessResult(
            returncode=-1,
            stdout="",
            stderr=f"Command not found: {args[0]}",
            duration_ms=elapsed,
        )


async def run_shell(
    command: str,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 120,
) -> ProcessResult:
    """Run a shell command string (via /bin/sh -c)."""
    import os
    import time

    merged_env = {**os.environ, **(env or {})}
    logger.debug("run_shell", command=command, cwd=str(cwd))

    start = time.monotonic()
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=merged_env,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        elapsed = int((time.monotonic() - start) * 1000)
        return ProcessResult(
            returncode=-1,
            stdout="",
            stderr=f"Command timed out after {timeout}s",
            timed_out=True,
            duration_ms=elapsed,
        )

    elapsed = int((time.monotonic() - start) * 1000)
    return ProcessResult(
        returncode=proc.returncode or 0,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        duration_ms=elapsed,
    )


async def start_process(
    *args: str,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
) -> ManagedProcess:
    """Start a long-running process and return a handle for managing it.

    The process runs in the background. Use ManagedProcess.kill() to stop it.
    """
    import os

    merged_env = {**os.environ, **(env or {})}
    cmd_str = " ".join(args)
    logger.info("start_process", command=cmd_str, cwd=str(cwd))

    # Use shell for commands with pipes, env vars, etc.
    proc = await asyncio.create_subprocess_shell(
        cmd_str,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=merged_env,
        preexec_fn=os.setsid,  # Create process group for clean killAll
    )

    managed = ManagedProcess(process=proc, command=cmd_str)
    managed.start_readers()
    return managed
