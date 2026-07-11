"""Phantom Consumer Contract — the frozen interface consumer apps and CI smoke
jobs depend on.

The *contract* is versioned INDEPENDENTLY of the ``phantom-docs`` package (see
``CONTRACT.md`` at the repository root for the full prose contract). This module
is Phantom's machine-checkable side of that contract: the constants and helpers
that consumers, the CI smoke job, and the conformance test-suite
(``tests/contract/``) all import from a single source of truth.

Nothing in this module may change in a contract-breaking way without bumping
both the package MAJOR version and ``CONTRACT_VERSION`` (see CONTRACT.md §5).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from collections.abc import Mapping

    from phantom.models import PhantomManifest

# ── Contract version ──────────────────────────────────
# Bumped independently of the package version. See CONTRACT.md §5.
CONTRACT_VERSION = "1.0.0"

# ── Boot contract (CONTRACT.md §1) ────────────────────
# Phantom GUARANTEES this variable is present in the launched consumer app's
# environment for every capture run. A consumer app switches into demo mode
# when it observes ``PHANTOM_MODE == "1"``.
PHANTOM_MODE_ENV = "PHANTOM_MODE"
PHANTOM_MODE_ON = "1"

# ── Artifact contract (CONTRACT.md §4) ────────────────
# Default project-root-relative directory under which captures are written and
# from which the CI smoke job collects screenshots. Individual captures may
# target a different ``output:`` path, but it MUST remain relative to the
# project root (Phantom rejects absolute paths and ``..`` — see
# ``PhantomManifest.validate_manifest``).
DEFAULT_ARTIFACT_DIR = "docs/screenshots"

# ── Health contract (CONTRACT.md §3) ──────────────────
# The readiness timeout is DECLARED in the manifest at
# ``setup.run.ready_check.timeout`` (seconds). This is the default applied by
# the schema when the field is omitted (see ``models.ReadyCheck.timeout``).
DEFAULT_READY_TIMEOUT_SECONDS = 30

# ── Network contract (CONTRACT.md §1/§3) ──────────────
# Under PHANTOM_MODE the consumer app must reach a healthy state without any
# external network beyond this loopback allowlist plus hosts explicitly
# declared in the manifest (ready_check / fixtures). Phantom's own probes only
# ever contact hosts in ``manifest_allowlist()``.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1", ""})


def is_phantom_mode(environ: Mapping[str, str] | None = None) -> bool:
    """Return ``True`` when the environment signals demo mode.

    Demo mode is signalled by ``PHANTOM_MODE == "1"`` exactly; any other value
    (unset, ``"0"``, ``"true"``…) is treated as OFF. This is the same check a
    consumer app performs at boot.
    """
    import os

    env = os.environ if environ is None else environ
    return env.get(PHANTOM_MODE_ENV) == PHANTOM_MODE_ON


def app_env(
    run_env: Mapping[str, str] | None = None,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build the environment Phantom hands to a launched consumer app.

    Guarantees ``PHANTOM_MODE=1`` (contract v1.0.0, CONTRACT.md §1) so demo
    mode activates regardless of the shell that invoked Phantom. Precedence,
    lowest to highest:

    1. ``base`` (typically the inherited process environment),
    2. ``PHANTOM_MODE=1`` (the contract guarantee),
    3. the manifest's explicit ``setup.run.env`` (``run_env``).

    A manifest may therefore override ``PHANTOM_MODE`` for a specific launch,
    but the default for every runner is demo mode ON.
    """
    env: dict[str, str] = dict(base or {})
    env[PHANTOM_MODE_ENV] = PHANTOM_MODE_ON
    if run_env:
        env.update(run_env)
    return env


def _host_of(url_or_host: str) -> str:
    """Extract a lowercased hostname from a URL or bare ``host[:port]`` string.

    Handles scheme URLs, bracketed IPv6 (``[::1]:8080``) and bare IPv6 (``::1``).
    """
    s = url_or_host.strip()
    if "://" in s:
        return (urlparse(s).hostname or "").lower()
    if s.startswith("["):  # bracketed IPv6, optionally with :port
        return s[1:].split("]", 1)[0].lower()
    if s.count(":") >= 2:  # bare IPv6 literal (no port)
        return s.lower()
    # Bare "host" or "host:port" (no scheme).
    return s.split("/")[0].rsplit(":", 1)[0].lower()


def manifest_allowlist(manifest: PhantomManifest) -> set[str]:
    """Hosts Phantom's own probes may contact for ``manifest``.

    This is the loopback allowlist plus every host explicitly declared in the
    manifest's ``ready_check`` and ``fixtures``. It is the concrete network
    surface a PHANTOM_MODE capture is permitted to touch (CONTRACT.md §1).
    """
    hosts: set[str] = set(LOOPBACK_HOSTS)
    ready_check = manifest.setup.run.ready_check
    if ready_check.url:
        hosts.add(_host_of(ready_check.url))
    for fixture in manifest.fixtures:
        if fixture.url:
            hosts.add(_host_of(fixture.url))
    return hosts


def is_host_allowed(host_or_url: str, manifest: PhantomManifest) -> bool:
    """Return ``True`` if ``host_or_url`` is within the manifest's allowlist."""
    return _host_of(host_or_url) in manifest_allowlist(manifest)
