"""System dependency checker.

Validates that required tools (node, npm, cargo, etc.) are installed
and meet version constraints before attempting a build.
"""

from __future__ import annotations

import platform
import re
from dataclasses import dataclass

import structlog

from phantom.exceptions import RequirementError
from phantom.utils.process import run_command

logger = structlog.get_logger()


# ── Runner → tool requirements ────────────────────────

RUNNER_REQUIREMENTS: dict[str, list[str]] = {
    "common": ["git"],
    "web": ["node", "npm"],
    "tui": ["silicon"],
    "docker-compose": ["docker"],
}

# ── Tool → OS-specific install hints ─────────────────

TOOL_HINTS: dict[str, dict[str, str]] = {
    "git": {
        "Darwin": "brew install git",
        "Linux": "sudo apt-get install git",
        "default": "https://git-scm.com/downloads",
    },
    "node": {
        "Darwin": "brew install node",
        "Linux": "curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - && sudo apt-get install -y nodejs",
        "default": "https://nodejs.org/",
    },
    "npm": {
        "Darwin": "brew install node  (npm ships with node)",
        "Linux": "Installed with node",
        "default": "https://nodejs.org/",
    },
    "silicon": {
        "Darwin": "brew install silicon",
        "Linux": "cargo install silicon",
        "default": "cargo install silicon",
    },
    "docker": {
        "Darwin": "brew install --cask docker",
        "Linux": "https://docs.docker.com/engine/install/",
        "default": "https://docs.docker.com/get-docker/",
    },
    "playwright": {
        "default": "pip install playwright && playwright install",
    },
}


def get_install_hint(tool: str) -> str:
    """Return an OS-appropriate install hint for *tool*."""
    hints = TOOL_HINTS.get(tool, {})
    system = platform.system()
    return hints.get(system, hints.get("default", f"Install '{tool}' and ensure it's on your PATH"))


@dataclass
class DoctorCheckResult:
    """Result of checking a single system tool."""

    tool: str
    found: bool
    version: str | None
    required_by: str
    install_hint: str


async def check_all_dependencies() -> list[DoctorCheckResult]:
    """Probe all known tools across all runner types.

    Returns a list of check results without raising on missing tools.
    """
    results: list[DoctorCheckResult] = []
    seen: set[str] = set()

    for runner_type, tools in RUNNER_REQUIREMENTS.items():
        for tool in tools:
            if tool in seen:
                continue
            seen.add(tool)

            found = False
            version = None

            which_result = await run_command("which", tool, timeout=5)
            if which_result.returncode == 0:
                found = True
                version = await _get_version(tool)

            results.append(
                DoctorCheckResult(
                    tool=tool,
                    found=found,
                    version=version,
                    required_by=runner_type,
                    install_hint=get_install_hint(tool),
                )
            )

    return results


# ── Existing requirement checking (raises on failure) ─


async def check_requirements(requirements: list[str]) -> None:
    """Check that all system requirements are met.

    Args:
        requirements: List of requirement strings like "node >= 18", "npm", "cargo".

    Raises:
        RequirementError: If any requirement is not met.
    """
    for req in requirements:
        await _check_single(req)


async def _check_single(req: str) -> None:
    """Check a single requirement string."""
    # Parse "tool >= version" or just "tool"
    match = re.match(r"^(\S+)\s*(>=?)\s*(\S+)$", req)
    if match:
        tool, operator, required_version = match.groups()
    else:
        tool = req.strip()
        operator = None
        required_version = None

    # Check tool exists
    result = await run_command("which", tool, timeout=5)
    if result.returncode != 0:
        hint = get_install_hint(tool)
        raise RequirementError(f"Required tool '{tool}' is not installed. {hint}")

    # Check version if specified
    if operator and required_version:
        version = await _get_version(tool)
        if version is None:
            logger.warning(
                "version_check_skipped",
                tool=tool,
                reason="Could not determine version",
            )
            return

        if not _version_satisfies(version, operator, required_version):
            raise RequirementError(
                f"Tool '{tool}' version {version} does not satisfy "
                f"'{operator} {required_version}'. Please upgrade."
            )

    logger.debug("requirement_met", tool=tool, version=required_version)


async def _get_version(tool: str) -> str | None:
    """Attempt to get a tool's version string."""
    for flag in ["--version", "-V", "version"]:
        result = await run_command(tool, flag, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            return _extract_version(result.stdout.strip())
        if result.returncode == 0 and result.stderr.strip():
            return _extract_version(result.stderr.strip())
    return None


def _extract_version(text: str) -> str | None:
    """Extract a semver-like version from a version string.

    Handles outputs like:
        "node v20.11.0"
        "npm 10.2.4"
        "rustc 1.75.0 (82e1608df 2023-12-21)"
        "Python 3.12.2"
    """
    match = re.search(r"v?(\d+(?:\.\d+)*)", text)
    return match.group(1) if match else None


def _version_satisfies(actual: str, operator: str, required: str) -> bool:
    """Compare version strings with the given operator."""
    actual_parts = _parse_version(actual)
    required_parts = _parse_version(required)

    if operator == ">=":
        return actual_parts >= required_parts
    if operator == ">":
        return actual_parts > required_parts
    return False


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse a dotted version string into a comparable tuple."""
    parts: list[int] = []
    for segment in v.split("."):
        try:
            parts.append(int(segment))
        except ValueError:
            break
    return tuple(parts) or (0,)
