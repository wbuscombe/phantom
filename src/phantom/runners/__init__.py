"""Runner plugin registry.

Built-in runners are registered at import time. External plugins
are discovered via the ``phantom.runners`` entry-point group.
"""

from __future__ import annotations

import importlib.metadata
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from phantom.runners.base import BaseRunner

logger = logging.getLogger(__name__)

_registry: dict[str, type[BaseRunner]] = {}


def register_runner(type_name: str, runner_class: type[BaseRunner]) -> None:
    """Register a runner class under *type_name*."""
    _registry[type_name] = runner_class
    logger.debug("runner_registered: %s -> %s", type_name, runner_class.__name__)


def get_runner(type_name: str) -> BaseRunner:
    """Instantiate and return a runner for *type_name*.

    Raises ``ConductorError`` with the list of available types
    if *type_name* is not registered.
    """
    cls = _registry.get(type_name)
    if cls is None:
        from phantom.exceptions import ConductorError

        available = ", ".join(available_runners())
        raise ConductorError(f"Unknown runner type '{type_name}'. Available types: {available}")
    return cls()


def available_runners() -> list[str]:
    """Return a sorted list of registered runner type names."""
    return sorted(_registry)


def _register_builtins() -> None:
    """Register the built-in runners (lazy imports to avoid circular deps)."""
    from phantom.runners.web import WebRunner

    register_runner("web", WebRunner)

    from phantom.runners.terminal import TerminalRunner

    register_runner("tui", TerminalRunner)

    from phantom.runners.docker import DockerRunner

    register_runner("docker-compose", DockerRunner)


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


_register_builtins()
_discover_plugins()
