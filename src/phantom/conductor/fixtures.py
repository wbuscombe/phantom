"""Fixture execution — seed demo data before captures.

Supports three fixture types:
- script: Run a shell command
- http: Make an HTTP request
- file_copy: Copy files into the project
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import httpx
import structlog

from phantom.exceptions import FixtureError
from phantom.utils.process import run_shell

if TYPE_CHECKING:
    from pathlib import Path

    from phantom.models import Fixture

logger = structlog.get_logger()


async def run_fixtures(
    fixtures: list[Fixture],
    project_dir: Path,
    env: dict[str, str] | None = None,
) -> None:
    """Execute fixtures sequentially.

    Args:
        fixtures: List of fixture definitions from the manifest.
        project_dir: Project root directory.
        env: Additional environment variables.

    Raises:
        FixtureError: If any fixture fails.
    """
    for i, fixture in enumerate(fixtures, 1):
        logger.info(
            "fixture_start",
            name=fixture.name,
            type=fixture.type,
            index=i,
            total=len(fixtures),
        )
        try:
            match fixture.type:
                case "script":
                    await _run_script(fixture, project_dir, env)
                case "http":
                    await _run_http(fixture)
                case "file_copy":
                    _run_file_copy(fixture, project_dir)
        except FixtureError:
            raise
        except Exception as e:
            raise FixtureError(f"Fixture '{fixture.name}' failed unexpectedly: {e}") from e

        logger.info("fixture_complete", name=fixture.name)


async def _run_script(
    fixture: Fixture,
    project_dir: Path,
    env: dict[str, str] | None,
) -> None:
    """Execute a script fixture."""
    assert fixture.run is not None
    result = await run_shell(
        fixture.run,
        cwd=project_dir,
        env=env,
        timeout=fixture.timeout,
    )
    if result.returncode != 0:
        raise FixtureError(
            f"Script fixture '{fixture.name}' failed (exit {result.returncode}): "
            f"{result.stderr[:500]}"
        )
    if result.timed_out:
        raise FixtureError(f"Script fixture '{fixture.name}' timed out after {fixture.timeout}s")


async def _run_http(fixture: Fixture) -> None:
    """Execute an HTTP fixture."""
    assert fixture.url is not None
    method = (fixture.method or "GET").upper()
    headers = fixture.headers or {}

    async with httpx.AsyncClient(timeout=fixture.timeout) as client:
        try:
            response = await client.request(
                method,
                fixture.url,
                headers=headers,
                content=fixture.body,
            )
        except httpx.TimeoutException as e:
            raise FixtureError(f"HTTP fixture '{fixture.name}' timed out: {e}") from e
        except httpx.ConnectError as e:
            raise FixtureError(f"HTTP fixture '{fixture.name}' connection failed: {e}") from e

    if fixture.expected_status and response.status_code != fixture.expected_status:
        raise FixtureError(
            f"HTTP fixture '{fixture.name}' returned {response.status_code}, "
            f"expected {fixture.expected_status}. Body: {response.text[:300]}"
        )

    logger.debug(
        "fixture_http_response",
        name=fixture.name,
        status=response.status_code,
    )


def _run_file_copy(fixture: Fixture, project_dir: Path) -> None:
    """Execute a file copy fixture."""
    assert fixture.source is not None
    assert fixture.destination is not None

    source = project_dir / fixture.source
    destination = project_dir / fixture.destination

    if not source.exists():
        raise FixtureError(f"File copy fixture '{fixture.name}' source not found: {source}")

    destination.mkdir(parents=True, exist_ok=True)

    if source.is_dir():
        shutil.copytree(source, destination / source.name, dirs_exist_ok=True)
    else:
        shutil.copy2(source, destination)

    logger.debug(
        "fixture_file_copy",
        name=fixture.name,
        source=str(source),
        destination=str(destination),
    )
