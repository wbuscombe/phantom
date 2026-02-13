# Writing Phantom Runner Plugins

This guide covers everything you need to build a custom Phantom runner -- from
understanding the base interface, to packaging your plugin so Phantom discovers
it automatically at runtime.

A **runner** is the component that knows how to build, launch, interact with,
and screenshot a specific kind of application. Phantom ships three built-in
runners (`web`, `tui`, `docker-compose`), but the system is designed to be
extended. If your application does not fit one of those categories, you write a
runner plugin.

---

## Table of Contents

1. [BaseRunner Interface](#1-baserunner-interface)
2. [RunnerContext](#2-runnercontext)
3. [CaptureResult](#3-captureresult)
4. [Step-by-Step Plugin Creation](#4-step-by-step-plugin-creation)
5. [Entry-Point Registration](#5-entry-point-registration)
6. [Testing Your Runner](#6-testing-your-runner)
7. [Complete Skeleton Example](#7-complete-skeleton-example)

---

## 1. BaseRunner Interface

Every runner subclasses `phantom.runners.base.BaseRunner`. There are four
abstract methods you must implement, plus one hook you can optionally override:

```python
from phantom.runners.base import BaseRunner, CaptureResult, RunnerContext
from phantom.models import ResolvedCapture


class MyRunner(BaseRunner):

    async def setup(self, ctx: RunnerContext) -> None:
        """Build the project and prepare the environment.

        Raises RunnerSetupError on failure.
        """
        ...

    async def launch(self, ctx: RunnerContext) -> None:
        """Start the application and wait for it to be ready.

        Raises RunnerLaunchError on failure (including timeout).
        """
        ...

    async def capture(self, ctx: RunnerContext, capture_def: ResolvedCapture) -> CaptureResult:
        """Execute a single capture.

        Performs actions, waits, and takes a screenshot.
        Must not raise -- returns CaptureResult with success=False on error.
        """
        ...

    async def teardown(self, ctx: RunnerContext) -> None:
        """Stop the application and clean up.

        Must not raise. Always runs, even after failures.
        """
        ...
```

### Method Contracts

| Method     | May raise?          | Called when                         |
|------------|---------------------|-------------------------------------|
| `setup`    | Yes (`RunnerSetupError`) | Before anything else. Build steps, requirement checks. |
| `launch`   | Yes (`RunnerLaunchError`) | After setup succeeds. Start the app, wait for readiness. |
| `capture`  | **No** -- return a failure `CaptureResult` instead | Once per capture definition. |
| `teardown` | **No** -- suppress all exceptions | Always, even after setup/launch failures. |

### `run_all` (optional override)

The base class provides a default `run_all` implementation that iterates
captures sequentially in manifest order, with automatic retry logic:

```python
async def run_all(self, ctx: RunnerContext) -> list[CaptureResult]:
    resolved = ctx.manifest.resolve_captures()
    results: list[CaptureResult] = []

    for capture_def in resolved:
        if capture_def.skip:
            ctx.logger.info("capture_skipped", capture_id=capture_def.id)
            continue

        result = await self._capture_with_retry(ctx, capture_def)
        results.append(result)

        ctx.logger.info(
            "capture_complete",
            capture_id=capture_def.id,
            success=result.success,
            duration_ms=result.duration_ms,
            attempt=result.attempt,
        )

    return results
```

Override `run_all` if you need custom sequencing -- for example,
dependency-aware ordering, parallel capture execution, or batching captures by
route.

Retry logic is built into `_capture_with_retry` using exponential backoff based
on each capture's `RetryConfig` (default: 3 attempts, 1000 ms initial backoff).
You get this for free as long as you use the default `run_all`.

---

## 2. RunnerContext

The `RunnerContext` dataclass is passed to every method. It contains everything
a runner needs to operate:

```python
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from phantom.models import PhantomManifest


@dataclass
class RunnerContext:
    project_dir: Path
    raw_output_dir: Path
    manifest: PhantomManifest
    logger: structlog.stdlib.BoundLogger = field(
        default_factory=lambda: structlog.get_logger()
    )
```

### Fields

| Field            | Type                | Description |
|------------------|---------------------|-------------|
| `project_dir`    | `Path`              | Absolute path to the project root. Use as `cwd` when running shell commands. |
| `raw_output_dir` | `Path`              | Directory where raw capture files (PNG, etc.) should be written. Always exists before your runner is called. |
| `manifest`       | `PhantomManifest`   | The fully-parsed and validated `.phantom.yml` manifest. Access `manifest.setup` for build/run/teardown config, `manifest.captures` for capture definitions, `manifest.resolve_captures()` for resolved captures with defaults applied. |
| `logger`         | `BoundLogger`       | A structured logger. Use for all logging so output is consistent with the rest of Phantom. |

### Accessing Manifest Data

The manifest gives you everything the user configured:

```python
async def setup(self, ctx: RunnerContext) -> None:
    setup = ctx.manifest.setup

    # Build commands to run
    build_cmds: list[str] | None = setup.build

    # The run command and its environment
    run_command: str = setup.run.command
    env: dict[str, str] | None = setup.run.env

    # Ready check configuration
    ready_check = setup.run.ready_check  # ReadyCheck model

    # Teardown commands
    teardown_cmds: list[str] | None = setup.teardown

    # Timeout budget for the runner
    timeout: int = setup.runner_timeout

    # Resolved captures (defaults merged in)
    captures: list[ResolvedCapture] = ctx.manifest.resolve_captures()
```

---

## 3. CaptureResult

Every call to `capture()` returns a `CaptureResult`. This dataclass tells the
orchestrator what happened:

```python
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CaptureResult:
    capture_id: str
    success: bool
    output_path: Path | None = None
    error: str | None = None
    duration_ms: int = 0
    attempt: int = 1
    metadata: dict[str, object] = field(default_factory=dict)
```

### Fields

| Field         | Type                | Description |
|---------------|---------------------|-------------|
| `capture_id`  | `str`               | Must match the `id` from the `ResolvedCapture`. |
| `success`     | `bool`              | `True` if a valid screenshot was produced. |
| `output_path` | `Path \| None`      | Path to the captured image file inside `ctx.raw_output_dir`. `None` on failure. |
| `error`       | `str \| None`       | Human-readable error message on failure. `None` on success. |
| `duration_ms` | `int`               | Elapsed wall-clock time for this capture in milliseconds. |
| `attempt`     | `int`               | Which attempt produced this result (set automatically by retry logic). |
| `metadata`    | `dict[str, object]` | Arbitrary extra data. Use for runner-specific diagnostics, performance counters, etc. |

### Constructing Results

**Success:**

```python
import time
from pathlib import Path

from phantom.runners.base import CaptureResult

start = time.monotonic()

# ... do the capture work ...
output_path = ctx.raw_output_dir / f"{capture_def.id}.png"

elapsed = int((time.monotonic() - start) * 1000)

return CaptureResult(
    capture_id=capture_def.id,
    success=True,
    output_path=output_path,
    duration_ms=elapsed,
)
```

**Failure:**

```python
return CaptureResult(
    capture_id=capture_def.id,
    success=False,
    error=f"Screenshot command failed: {stderr[:500]}",
    duration_ms=elapsed,
)
```

**With metadata:**

```python
return CaptureResult(
    capture_id=capture_def.id,
    success=True,
    output_path=output_path,
    duration_ms=elapsed,
    metadata={
        "viewport": f"{capture_def.viewport.width}x{capture_def.viewport.height}",
        "api_version": self._api_version,
        "response_time_ms": api_response_time,
    },
)
```

---

## 4. Step-by-Step Plugin Creation

### Step 1: Create a Python package

```
phantom-runner-myapp/
    src/
        phantom_runner_myapp/
            __init__.py
            runner.py
    tests/
        fixtures/
            test-myapp/
                .phantom.yml
        test_runner.py
    pyproject.toml
```

### Step 2: Implement BaseRunner

In `src/phantom_runner_myapp/runner.py`:

```python
"""Phantom runner for MyApp desktop application."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import structlog

from phantom.exceptions import RunnerLaunchError, RunnerSetupError
from phantom.runners.base import BaseRunner, CaptureResult, RunnerContext

if TYPE_CHECKING:
    from phantom.models import ResolvedCapture

logger = structlog.get_logger()


class MyAppRunner(BaseRunner):
    """Runner for MyApp -- launches the app, drives it via its API, takes screenshots."""

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._base_url: str = ""

    async def setup(self, ctx: RunnerContext) -> None:
        setup = ctx.manifest.setup

        # Run build commands from the manifest
        if setup.build:
            env = setup.run.env or {}
            for cmd in setup.build:
                ctx.logger.info("build_step", command=cmd)
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    cwd=ctx.project_dir,
                    env={**dict(__import__("os").environ), **env},
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()
                if proc.returncode != 0:
                    raise RunnerSetupError(
                        f"Build command failed: {cmd}\n{stderr.decode()[:1000]}"
                    )

        ctx.logger.info("setup_complete")

    async def launch(self, ctx: RunnerContext) -> None:
        run_config = ctx.manifest.setup.run
        env = {**dict(__import__("os").environ, **(run_config.env or {}))}

        # Start the application
        self._process = await asyncio.create_subprocess_shell(
            run_config.command,
            cwd=ctx.project_dir,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Determine base URL from the ready check
        ready = run_config.ready_check
        if ready.type == "http" and ready.url:
            self._base_url = ready.url.rstrip("/")
        elif ready.type == "tcp" and ready.port:
            self._base_url = f"http://localhost:{ready.port}"
        else:
            self._base_url = "http://localhost:8080"

        # Wait for readiness (simplified -- real runners should
        # implement full polling with timeout)
        if not await self._poll_ready(ready, ctx):
            raise RunnerLaunchError(
                f"MyApp failed ready check after {ready.timeout}s"
            )

        ctx.logger.info("launch_complete", base_url=self._base_url)

    async def capture(
        self, ctx: RunnerContext, capture_def: ResolvedCapture
    ) -> CaptureResult:
        start = time.monotonic()
        capture_id = capture_def.id

        try:
            # --- Your capture logic here ---
            # 1. Perform actions (navigate, click, type, etc.)
            # 2. Wait for the UI to settle
            # 3. Take a screenshot and save to raw_output_dir

            output_path = ctx.raw_output_dir / f"{capture_id}.png"

            # Example: call an internal screenshot API
            # await self._take_screenshot(capture_def, output_path)

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

    async def teardown(self, ctx: RunnerContext) -> None:
        # Kill the application process
        if self._process is not None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

        # Run any teardown commands from the manifest
        teardown_cmds = ctx.manifest.setup.teardown or []
        for cmd in teardown_cmds:
            try:
                proc = await asyncio.create_subprocess_shell(
                    cmd, cwd=ctx.project_dir
                )
                await asyncio.wait_for(proc.wait(), timeout=10)
            except Exception as e:
                ctx.logger.warning(
                    "teardown_command_failed", command=cmd, error=str(e)
                )

        ctx.logger.info("teardown_complete")

    async def _poll_ready(self, ready_check, ctx: RunnerContext) -> bool:
        """Poll until ready or timeout. Returns True if ready."""
        import httpx

        deadline = asyncio.get_event_loop().time() + ready_check.timeout

        while asyncio.get_event_loop().time() < deadline:
            if ready_check.type == "http" and ready_check.url:
                try:
                    async with httpx.AsyncClient(timeout=2) as client:
                        resp = await client.get(ready_check.url)
                        if resp.status_code == ready_check.status_code:
                            return True
                except (httpx.ConnectError, httpx.TimeoutException):
                    pass
            elif ready_check.type == "delay" and ready_check.seconds:
                await asyncio.sleep(ready_check.seconds)
                return True

            await asyncio.sleep(ready_check.interval)

        return False
```

### Step 3: Handle Actions

The `ResolvedCapture.actions` field contains a list of `Action` objects (a
discriminated union on the `type` field). Your runner should handle the action
types that make sense for it. Common action types include:

- `NavigateAction` -- go to a URL
- `ClickAction` -- click a selector or coordinates
- `TypeAction` -- type text into an input
- `WaitAction` -- wait a fixed duration (milliseconds)
- `WaitForAction` -- wait for a selector to reach a state
- `ScrollToAction` -- scroll an element into view
- `PressAction` -- press a keyboard key
- `SetViewportAction` -- resize the viewport

For TUI runners there are also `KeystrokeAction` and `TypeTextAction`.

Handle actions using pattern matching:

```python
from phantom.models import (
    ClickAction,
    NavigateAction,
    WaitAction,
    WaitForAction,
    TypeAction,
)


async def _execute_actions(self, actions, ctx):
    for action in actions:
        match action:
            case NavigateAction():
                await self._navigate(action.url)

            case ClickAction():
                if action.selector:
                    await self._click_selector(action.selector)
                else:
                    await self._click_coords(action.x, action.y)

            case TypeAction():
                await self._type_text(action.text, action.selector)

            case WaitAction():
                await asyncio.sleep(action.ms / 1000.0)

            case WaitForAction():
                await self._wait_for_element(
                    action.selector, action.state, action.timeout
                )

            case _:
                ctx.logger.warning(
                    "action_unsupported",
                    type=getattr(action, "type", "unknown"),
                )
```

It is perfectly fine to warn and skip action types your runner does not support.
The built-in `TerminalRunner`, for example, ignores browser-specific actions
like `NavigateAction` and only handles `KeystrokeAction`, `TypeTextAction`,
`WaitAction`, and `WaitForAction`.

---

## 5. Entry-Point Registration

Phantom discovers external runner plugins via the standard Python
`importlib.metadata` entry-point mechanism. The entry-point group is
`phantom.runners`.

In your plugin's `pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "phantom-runner-myapp"
version = "0.1.0"
description = "Phantom runner for MyApp desktop application"
requires-python = ">=3.12"
dependencies = [
    "phantom-docs>=0.1.0",
]

[project.entry-points."phantom.runners"]
myapp = "phantom_runner_myapp.runner:MyAppRunner"
```

The key (`myapp`) becomes the runner **type name** that users reference in
their `.phantom.yml` manifest:

```yaml
phantom: "1"
project: my-project
name: My Project

setup:
  type: myapp          # <-- matches the entry-point key
  run:
    command: "myapp serve"
    ready_check:
      type: http
      url: http://localhost:8080/health
      timeout: 30
  runner_timeout: 120

captures:
  - id: dashboard
    name: Dashboard View
    output: docs/images/dashboard.png
    route: /dashboard
```

### How Discovery Works

When Phantom starts, the runner registry in
`phantom/runners/__init__.py` calls `_discover_plugins()`:

```python
def _discover_plugins() -> None:
    """Discover external runner plugins via entry points."""
    try:
        eps = importlib.metadata.entry_points(group="phantom.runners")
    except Exception:
        return

    for ep in eps:
        try:
            runner_class = ep.load()
            register_runner(ep.name, runner_class)
        except Exception as exc:
            logger.warning(
                "Failed to load runner plugin '%s': %s",
                ep.name,
                exc,
            )
```

This means:

1. Your package must be installed in the same environment as Phantom (e.g. `pip install phantom-runner-myapp`).
2. The entry-point value must be a dotted path to a class that subclasses `BaseRunner`.
3. If your plugin fails to import, Phantom logs a warning but continues -- it does not crash.

You can verify registration with:

```python
from phantom.runners import available_runners

print(available_runners())
# ['docker-compose', 'myapp', 'tui', 'web']
```

---

## 6. Testing Your Runner

Phantom's test suite uses `pytest` with `pytest-asyncio` in auto mode. Follow
the existing patterns from the built-in runners.

### Test Fixtures

Create a minimal `.phantom.yml` in your test fixtures directory:

```
tests/
    fixtures/
        test-myapp/
            .phantom.yml
    test_runner.py
```

**`tests/fixtures/test-myapp/.phantom.yml`:**

```yaml
phantom: "1"
project: test-myapp
name: Test MyApp

setup:
  type: myapp
  run:
    command: "echo running"
    ready_check:
      type: delay
      seconds: 0
  runner_timeout: 10

captures:
  - id: main-view
    name: Main View
    output: docs/images/main.png
    route: /
```

### Writing Tests

Follow the pattern used by the Docker and Terminal runner tests -- group by
lifecycle phase, mock external dependencies, and construct `RunnerContext`
using `tmp_path`:

```python
"""Unit tests for the MyApp runner.

All external commands are mocked -- no real MyApp process required.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from phantom.exceptions import RunnerLaunchError, RunnerSetupError
from phantom.models import load_manifest
from phantom.runners.base import CaptureResult, RunnerContext

from phantom_runner_myapp.runner import MyAppRunner

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "test-myapp"
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
def runner() -> MyAppRunner:
    return MyAppRunner()


# -- Setup ---------------------------------------------------------


class TestSetup:
    async def test_setup_runs_build_commands(
        self, runner: MyAppRunner, ctx: RunnerContext
    ) -> None:
        """Build commands from the manifest should be executed."""
        ctx.manifest.setup.build = ["make build"]

        with patch(
            "asyncio.create_subprocess_shell",
            new_callable=AsyncMock,
        ) as mock_proc:
            mock_proc.return_value.communicate = AsyncMock(
                return_value=(b"", b"")
            )
            mock_proc.return_value.returncode = 0
            await runner.setup(ctx)

        mock_proc.assert_called_once()

    async def test_setup_raises_on_build_failure(
        self, runner: MyAppRunner, ctx: RunnerContext
    ) -> None:
        """A failing build command should raise RunnerSetupError."""
        ctx.manifest.setup.build = ["make build"]

        with patch(
            "asyncio.create_subprocess_shell",
            new_callable=AsyncMock,
        ) as mock_proc:
            mock_proc.return_value.communicate = AsyncMock(
                return_value=(b"", b"compilation failed")
            )
            mock_proc.return_value.returncode = 1

            with pytest.raises(RunnerSetupError, match="Build command failed"):
                await runner.setup(ctx)


# -- Launch --------------------------------------------------------


class TestLaunch:
    async def test_launch_starts_process(
        self, runner: MyAppRunner, ctx: RunnerContext
    ) -> None:
        """launch() should start the app and wait for readiness."""
        with (
            patch(
                "asyncio.create_subprocess_shell",
                new_callable=AsyncMock,
            ),
            patch.object(
                runner, "_poll_ready", new_callable=AsyncMock, return_value=True
            ),
        ):
            await runner.launch(ctx)

        assert runner._process is not None

    async def test_launch_raises_on_ready_timeout(
        self, runner: MyAppRunner, ctx: RunnerContext
    ) -> None:
        """launch() should raise RunnerLaunchError on ready check timeout."""
        with (
            patch(
                "asyncio.create_subprocess_shell",
                new_callable=AsyncMock,
            ),
            patch.object(
                runner, "_poll_ready", new_callable=AsyncMock, return_value=False
            ),
            pytest.raises(RunnerLaunchError, match="failed ready check"),
        ):
            await runner.launch(ctx)


# -- Capture -------------------------------------------------------


class TestCapture:
    async def test_capture_success(
        self, runner: MyAppRunner, ctx: RunnerContext
    ) -> None:
        """A successful capture should return success=True with output_path."""
        resolved = ctx.manifest.resolve_captures()
        target = resolved[0]

        # Create a fake output file to simulate the screenshot
        output_path = ctx.raw_output_dir / f"{target.id}.png"
        output_path.write_bytes(b"\x89PNG fake image data")

        result = await runner.capture(ctx, target)

        assert result.success
        assert result.capture_id == target.id
        assert result.output_path is not None
        assert result.duration_ms >= 0

    async def test_capture_failure_returns_error(
        self, runner: MyAppRunner, ctx: RunnerContext
    ) -> None:
        """A failed capture should return success=False with error message."""
        resolved = ctx.manifest.resolve_captures()
        target = resolved[0]

        # Patch internal method to raise
        with patch.object(
            runner, "_take_screenshot", side_effect=RuntimeError("connection lost")
        ):
            result = await runner.capture(ctx, target)

        assert not result.success
        assert "connection lost" in result.error


# -- Teardown ------------------------------------------------------


class TestTeardown:
    async def test_teardown_kills_process(
        self, runner: MyAppRunner, ctx: RunnerContext
    ) -> None:
        """teardown() should terminate the app process."""
        mock_proc = AsyncMock()
        mock_proc.terminate = lambda: None
        mock_proc.kill = lambda: None
        mock_proc.wait = AsyncMock()
        runner._process = mock_proc

        await runner.teardown(ctx)

        assert runner._process is None

    async def test_teardown_suppresses_errors(
        self, runner: MyAppRunner, ctx: RunnerContext
    ) -> None:
        """Teardown must not raise, even if cleanup fails."""
        mock_proc = AsyncMock()
        mock_proc.terminate = lambda: (_ for _ in ()).throw(ProcessLookupError)
        mock_proc.kill = lambda: None
        mock_proc.wait = AsyncMock(side_effect=ProcessLookupError)
        runner._process = mock_proc

        # Should not raise
        await runner.teardown(ctx)

    async def test_teardown_runs_commands(
        self, runner: MyAppRunner, ctx: RunnerContext
    ) -> None:
        """User-defined teardown commands should be executed."""
        ctx.manifest.setup.teardown = ["echo cleanup"]

        with patch(
            "asyncio.create_subprocess_shell",
            new_callable=AsyncMock,
        ) as mock_proc:
            mock_proc.return_value.wait = AsyncMock()
            await runner.teardown(ctx)

        mock_proc.assert_called_once()
```

### Key Testing Patterns

1. **Always mock external processes.** Unit tests should never start real
   applications, call Docker, or hit the network.

2. **Use `tmp_path`** for `raw_output_dir`. pytest cleans it up automatically.

3. **Load real manifests from fixtures** rather than constructing `PhantomManifest`
   objects by hand. This ensures your test fixtures stay in sync with the schema.

4. **Group tests by lifecycle phase** (`TestSetup`, `TestLaunch`, `TestCapture`,
   `TestTeardown`) for readability.

5. **Test the error paths.** Verify that `setup` raises `RunnerSetupError`,
   `launch` raises `RunnerLaunchError`, `capture` returns `success=False`
   (never raises), and `teardown` never raises.

6. **Use `pytest.ini_options`** with `asyncio_mode = "auto"` so async test
   methods work without decorators.

### Running Tests

```bash
# Run your plugin's tests
pytest tests/test_runner.py -v

# Run with coverage
pytest tests/test_runner.py --cov=phantom_runner_myapp --cov-report=term-missing
```

---

## 7. Complete Skeleton Example

Below is a complete, working runner plugin that captures screenshots from a
hypothetical desktop application called **SketchPad**. SketchPad exposes an
HTTP API for automation:

- `POST /api/open?file=<path>` -- open a document
- `POST /api/action` -- execute a UI action (JSON body)
- `GET /api/screenshot` -- returns a PNG of the current window

### Project Structure

```
phantom-runner-sketchpad/
    src/
        phantom_runner_sketchpad/
            __init__.py
            runner.py
    tests/
        fixtures/
            test-sketchpad/
                .phantom.yml
        test_runner.py
    pyproject.toml
```

### `pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "phantom-runner-sketchpad"
version = "0.1.0"
description = "Phantom runner plugin for SketchPad application"
requires-python = ">=3.12"
dependencies = [
    "phantom-docs>=0.1.0",
    "httpx>=0.26",
]

[project.entry-points."phantom.runners"]
sketchpad = "phantom_runner_sketchpad.runner:SketchPadRunner"

[tool.hatch.build.targets.wheel]
packages = ["src/phantom_runner_sketchpad"]
```

### `src/phantom_runner_sketchpad/__init__.py`

```python
"""Phantom runner plugin for SketchPad."""
```

### `src/phantom_runner_sketchpad/runner.py`

```python
"""Phantom runner for the SketchPad desktop application.

SketchPad exposes an HTTP automation API on a configurable port.
This runner starts the application, drives it via HTTP, and captures
screenshots through the API.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING

import httpx
import structlog

from phantom.exceptions import RunnerLaunchError, RunnerSetupError
from phantom.models import (
    ClickAction,
    NavigateAction,
    ScrollAction,
    TypeAction,
    WaitAction,
    WaitForAction,
)
from phantom.runners.base import BaseRunner, CaptureResult, RunnerContext

if TYPE_CHECKING:
    from phantom.models import Action, ReadyCheck, ResolvedCapture

logger = structlog.get_logger()


class SketchPadRunner(BaseRunner):
    """Runner for SketchPad -- launches the app, drives it via HTTP API,
    captures screenshots through the API's screenshot endpoint.
    """

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._base_url: str = ""
        self._api_client: httpx.AsyncClient | None = None

    # -- Lifecycle -------------------------------------------------

    async def setup(self, ctx: RunnerContext) -> None:
        """Verify SketchPad is installed and run build commands."""
        setup = ctx.manifest.setup

        # Check that sketchpad binary exists
        proc = await asyncio.create_subprocess_exec(
            "which", "sketchpad",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        if proc.returncode != 0:
            raise RunnerSetupError(
                "sketchpad is required but was not found on PATH.\n"
                "Install it: https://sketchpad.example.com/install"
            )

        # Run build commands (e.g., compile plugins, generate assets)
        if setup.build:
            env = {**os.environ, **(setup.run.env or {})}
            for cmd in setup.build:
                ctx.logger.info("build_step", command=cmd)
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    cwd=ctx.project_dir,
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()
                if proc.returncode != 0:
                    raise RunnerSetupError(
                        f"Build command failed: {cmd}\n"
                        f"{stderr.decode('utf-8', errors='replace')[:1000]}"
                    )

        ctx.logger.info("setup_complete")

    async def launch(self, ctx: RunnerContext) -> None:
        """Start SketchPad and wait for its API to become available."""
        run_config = ctx.manifest.setup.run
        env = {**os.environ, **(run_config.env or {})}

        # Start the application
        self._process = await asyncio.create_subprocess_shell(
            run_config.command,
            cwd=ctx.project_dir,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Determine the base URL from the ready check
        ready = run_config.ready_check
        if ready.type == "http" and ready.url:
            self._base_url = ready.url.rstrip("/").rsplit("/", 1)[0]
        elif ready.type == "tcp" and ready.port:
            self._base_url = f"http://localhost:{ready.port}"
        else:
            self._base_url = "http://localhost:9900"

        # Wait for the API to respond
        ctx.logger.info(
            "launch_ready_check",
            type=ready.type,
            timeout=ready.timeout,
        )

        if not await self._wait_for_ready(ready, ctx):
            # Gather diagnostic output
            stderr_data = b""
            if self._process.stderr:
                try:
                    stderr_data = await asyncio.wait_for(
                        self._process.stderr.read(4096), timeout=1
                    )
                except (asyncio.TimeoutError, Exception):
                    pass

            raise RunnerLaunchError(
                f"SketchPad failed ready check after {ready.timeout}s. "
                f"Type: {ready.type}\n"
                f"stderr: {stderr_data.decode('utf-8', errors='replace')[:500]}"
            )

        # Create a persistent HTTP client for the API
        self._api_client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=30,
        )

        ctx.logger.info("launch_complete", base_url=self._base_url)

    async def capture(
        self, ctx: RunnerContext, capture_def: ResolvedCapture
    ) -> CaptureResult:
        """Navigate to a document/view, execute actions, and take a screenshot."""
        start = time.monotonic()
        capture_id = capture_def.id

        try:
            assert self._api_client is not None

            # Navigate to the route (interpreted as a document path for SketchPad)
            if capture_def.route:
                resp = await self._api_client.post(
                    "/api/open",
                    params={"file": capture_def.route},
                )
                resp.raise_for_status()

            # Wait for initial element if specified
            if capture_def.wait_for:
                await self._poll_for_element(
                    capture_def.wait_for,
                    capture_def.wait_for_state,
                    capture_def.timeout,
                )

            # Execute manifest actions
            if capture_def.actions:
                await self._execute_actions(capture_def.actions, ctx)

            # Wait after actions
            if capture_def.wait_after_actions > 0:
                await asyncio.sleep(capture_def.wait_after_actions / 1000.0)

            # Take screenshot via the API
            output_path = ctx.raw_output_dir / f"{capture_id}.png"
            resp = await self._api_client.get(
                "/api/screenshot",
                params={
                    "width": capture_def.viewport.width,
                    "height": capture_def.viewport.height,
                    "scale": capture_def.device_scale,
                    "theme": capture_def.theme,
                },
            )
            resp.raise_for_status()
            output_path.write_bytes(resp.content)

            elapsed = int((time.monotonic() - start) * 1000)
            return CaptureResult(
                capture_id=capture_id,
                success=True,
                output_path=output_path,
                duration_ms=elapsed,
                metadata={
                    "content_length": len(resp.content),
                    "viewport": (
                        f"{capture_def.viewport.width}x"
                        f"{capture_def.viewport.height}"
                    ),
                },
            )

        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            ctx.logger.error(
                "capture_failed",
                capture_id=capture_id,
                error=str(e),
            )

            # Attempt a diagnostic screenshot
            try:
                if self._api_client is not None:
                    diag_resp = await self._api_client.get("/api/screenshot")
                    if diag_resp.status_code == 200:
                        diag_path = (
                            ctx.raw_output_dir / f"{capture_id}_diagnostic.png"
                        )
                        diag_path.write_bytes(diag_resp.content)
                        ctx.logger.info("diagnostic_screenshot", path=str(diag_path))
            except Exception:
                pass

            return CaptureResult(
                capture_id=capture_id,
                success=False,
                error=str(e),
                duration_ms=elapsed,
            )

    async def teardown(self, ctx: RunnerContext) -> None:
        """Close the API client, kill the app, run teardown commands."""
        # Close HTTP client
        if self._api_client is not None:
            try:
                await self._api_client.aclose()
            except Exception:
                pass
            self._api_client = None

        # Kill the application process
        if self._process is not None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                try:
                    self._process.kill()
                    await self._process.wait()
                except Exception:
                    pass
            except Exception:
                pass
            self._process = None

        # Run user-defined teardown commands
        teardown_cmds = ctx.manifest.setup.teardown or []
        for cmd in teardown_cmds:
            try:
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    cwd=ctx.project_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc.wait(), timeout=10)
            except Exception as e:
                ctx.logger.warning(
                    "teardown_command_failed", command=cmd, error=str(e)
                )

        ctx.logger.info("teardown_complete")

    # -- Internal helpers ------------------------------------------

    async def _wait_for_ready(
        self, ready_check: ReadyCheck, ctx: RunnerContext
    ) -> bool:
        """Poll until the application API is responsive."""
        deadline = asyncio.get_event_loop().time() + ready_check.timeout

        while asyncio.get_event_loop().time() < deadline:
            # Check if the process died
            if self._process is not None and self._process.returncode is not None:
                return False

            match ready_check.type:
                case "http":
                    assert ready_check.url is not None
                    try:
                        async with httpx.AsyncClient(timeout=2) as client:
                            resp = await client.get(ready_check.url)
                            if resp.status_code == ready_check.status_code:
                                return True
                    except (httpx.ConnectError, httpx.TimeoutException):
                        pass

                case "tcp":
                    assert ready_check.port is not None
                    try:
                        _, writer = await asyncio.wait_for(
                            asyncio.open_connection("localhost", ready_check.port),
                            timeout=2,
                        )
                        writer.close()
                        await writer.wait_closed()
                        return True
                    except (ConnectionRefusedError, TimeoutError, OSError):
                        pass

                case "delay":
                    assert ready_check.seconds is not None
                    await asyncio.sleep(ready_check.seconds)
                    return True

            await asyncio.sleep(ready_check.interval)

        return False

    async def _execute_actions(
        self, actions: list[Action], ctx: RunnerContext
    ) -> None:
        """Translate manifest actions to SketchPad API calls."""
        assert self._api_client is not None

        for action in actions:
            match action:
                case NavigateAction():
                    await self._api_client.post(
                        "/api/open", params={"file": action.url}
                    )

                case ClickAction():
                    body: dict[str, object] = {"type": "click"}
                    if action.selector:
                        body["selector"] = action.selector
                    else:
                        body["x"] = action.x
                        body["y"] = action.y
                    body["button"] = action.button
                    await self._api_client.post("/api/action", json=body)

                case TypeAction():
                    body = {"type": "type", "text": action.text}
                    if action.selector:
                        body["selector"] = action.selector
                    await self._api_client.post("/api/action", json=body)

                case ScrollAction():
                    await self._api_client.post(
                        "/api/action",
                        json={"type": "scroll", "x": action.x, "y": action.y},
                    )

                case WaitAction():
                    await asyncio.sleep(action.ms / 1000.0)

                case WaitForAction():
                    await self._poll_for_element(
                        action.selector, action.state, action.timeout
                    )

                case _:
                    ctx.logger.warning(
                        "action_unsupported",
                        type=getattr(action, "type", "unknown"),
                    )

    async def _poll_for_element(
        self, selector: str, state: str, timeout: int
    ) -> None:
        """Poll the SketchPad API until an element reaches the desired state."""
        assert self._api_client is not None
        deadline = asyncio.get_event_loop().time() + timeout

        while asyncio.get_event_loop().time() < deadline:
            resp = await self._api_client.get(
                "/api/query",
                params={"selector": selector},
            )
            if resp.status_code == 200:
                data = resp.json()
                if state == "visible" and data.get("visible"):
                    return
                if state == "hidden" and not data.get("visible"):
                    return
                if state == "attached" and data.get("exists"):
                    return
                if state == "detached" and not data.get("exists"):
                    return
            await asyncio.sleep(0.25)

        raise TimeoutError(
            f"Element '{selector}' did not reach state '{state}' "
            f"within {timeout}s"
        )
```

### `tests/fixtures/test-sketchpad/.phantom.yml`

```yaml
phantom: "1"
project: test-sketchpad
name: Test SketchPad

setup:
  type: sketchpad
  run:
    command: "sketchpad --headless --api-port 9900"
    ready_check:
      type: http
      url: http://localhost:9900/health
      timeout: 15
  runner_timeout: 60

captures:
  - id: blank-canvas
    name: Blank Canvas
    output: docs/images/blank-canvas.png
    route: /templates/blank.sketch

  - id: toolbar-hover
    name: Toolbar with Hover
    output: docs/images/toolbar-hover.png
    route: /templates/blank.sketch
    actions:
      - type: click
        selector: "#brush-tool"
      - type: wait
        ms: 200
```

### `tests/test_runner.py`

```python
"""Unit tests for the SketchPad runner plugin.

All HTTP calls and subprocess launches are mocked.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from phantom.exceptions import RunnerLaunchError, RunnerSetupError
from phantom.models import load_manifest
from phantom.runners.base import RunnerContext

from phantom_runner_sketchpad.runner import SketchPadRunner

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "test-sketchpad"
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
def runner() -> SketchPadRunner:
    return SketchPadRunner()


class TestSetup:
    async def test_setup_checks_sketchpad_binary(
        self, runner: SketchPadRunner, ctx: RunnerContext
    ) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"/usr/bin/sketchpad", b""))
        mock_proc.returncode = 0

        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ):
            await runner.setup(ctx)

    async def test_setup_fails_without_binary(
        self, runner: SketchPadRunner, ctx: RunnerContext
    ) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 1

        with (
            patch(
                "asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=mock_proc,
            ),
            pytest.raises(RunnerSetupError, match="sketchpad is required"),
        ):
            await runner.setup(ctx)


class TestLaunch:
    async def test_launch_waits_for_ready(
        self, runner: SketchPadRunner, ctx: RunnerContext
    ) -> None:
        with (
            patch("asyncio.create_subprocess_shell", new_callable=AsyncMock),
            patch.object(
                runner, "_wait_for_ready", new_callable=AsyncMock, return_value=True
            ),
        ):
            await runner.launch(ctx)

        assert runner._api_client is not None
        assert runner._base_url == "http://localhost:9900"

        # Clean up the client
        await runner._api_client.aclose()

    async def test_launch_raises_on_timeout(
        self, runner: SketchPadRunner, ctx: RunnerContext
    ) -> None:
        mock_proc = AsyncMock()
        mock_proc.stderr = None
        mock_proc.returncode = None

        with (
            patch(
                "asyncio.create_subprocess_shell",
                new_callable=AsyncMock,
                return_value=mock_proc,
            ),
            patch.object(
                runner, "_wait_for_ready", new_callable=AsyncMock, return_value=False
            ),
            pytest.raises(RunnerLaunchError, match="failed ready check"),
        ):
            await runner.launch(ctx)


class TestCapture:
    async def test_capture_returns_screenshot(
        self, runner: SketchPadRunner, ctx: RunnerContext
    ) -> None:
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            return_value=MagicMock(status_code=200, raise_for_status=lambda: None)
        )
        mock_client.get = AsyncMock(
            return_value=MagicMock(
                status_code=200,
                content=fake_png,
                raise_for_status=lambda: None,
            )
        )
        runner._api_client = mock_client

        resolved = ctx.manifest.resolve_captures()
        target = next(r for r in resolved if r.id == "blank-canvas")

        result = await runner.capture(ctx, target)

        assert result.success
        assert result.capture_id == "blank-canvas"
        assert result.output_path is not None
        assert result.output_path.exists()
        assert result.output_path.read_bytes() == fake_png
        assert result.duration_ms >= 0

    async def test_capture_failure_returns_error_result(
        self, runner: SketchPadRunner, ctx: RunnerContext
    ) -> None:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )
        # Diagnostic screenshot should also fail gracefully
        mock_client.get = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )
        runner._api_client = mock_client

        resolved = ctx.manifest.resolve_captures()
        target = resolved[0]

        result = await runner.capture(ctx, target)

        assert not result.success
        assert result.error is not None
        assert "connection refused" in result.error


class TestTeardown:
    async def test_teardown_cleans_up_everything(
        self, runner: SketchPadRunner, ctx: RunnerContext
    ) -> None:
        mock_client = AsyncMock()
        runner._api_client = mock_client

        mock_proc = AsyncMock()
        mock_proc.terminate = lambda: None
        mock_proc.wait = AsyncMock()
        mock_proc.kill = lambda: None
        runner._process = mock_proc

        await runner.teardown(ctx)

        assert runner._api_client is None
        assert runner._process is None
        mock_client.aclose.assert_called_once()

    async def test_teardown_never_raises(
        self, runner: SketchPadRunner, ctx: RunnerContext
    ) -> None:
        mock_client = AsyncMock()
        mock_client.aclose = AsyncMock(side_effect=RuntimeError("boom"))
        runner._api_client = mock_client

        mock_proc = AsyncMock()
        mock_proc.terminate = MagicMock(side_effect=ProcessLookupError)
        mock_proc.kill = MagicMock(side_effect=ProcessLookupError)
        mock_proc.wait = AsyncMock(side_effect=ProcessLookupError)
        runner._process = mock_proc

        # Must not raise
        await runner.teardown(ctx)
```

---

## Summary

To write a Phantom runner plugin:

1. **Subclass `BaseRunner`** and implement `setup`, `launch`, `capture`, and `teardown`.
2. **Use `RunnerContext`** for project paths, output directories, manifest data, and logging.
3. **Return `CaptureResult`** from `capture()` -- never raise exceptions from that method.
4. **Handle actions** from `ResolvedCapture.actions` using pattern matching; warn and skip unsupported types.
5. **Register via entry points** in `pyproject.toml` under `[project.entry-points."phantom.runners"]`.
6. **Test with mocks** following the `TestSetup`/`TestLaunch`/`TestCapture`/`TestTeardown` pattern.
7. **Install your package** (`pip install -e .`) and your runner type appears in `available_runners()`.
