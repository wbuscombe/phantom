"""Shared fixtures for the Phantom consumer-contract conformance suite.

These tests mechanically verify Phantom's side of every promise in
``CONTRACT.md`` (contract-version 1.0.0). They must not depend on external
tools (docker, Xvfb, a browser): all runner spawn primitives are mocked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from phantom.models import PhantomManifest, load_manifest

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"

# The shipped fixture manifests, one per runner type. They double as the
# reference examples the contract is written against.
SHIPPED_MANIFESTS = {
    "web": FIXTURES_DIR / "test-web-app" / ".phantom.yml",
    "docker": FIXTURES_DIR / "test-docker-app" / ".phantom.yml",
    "tui": FIXTURES_DIR / "test-tui-app" / ".phantom.yml",
}


@pytest.fixture(params=sorted(SHIPPED_MANIFESTS), ids=sorted(SHIPPED_MANIFESTS))
def shipped_manifest(request: pytest.FixtureRequest) -> PhantomManifest:
    """Every shipped fixture manifest, parametrized by runner type."""
    return load_manifest(str(SHIPPED_MANIFESTS[request.param]))


@pytest.fixture
def web_manifest() -> PhantomManifest:
    return load_manifest(str(SHIPPED_MANIFESTS["web"]))


@pytest.fixture
def docker_manifest() -> PhantomManifest:
    return load_manifest(str(SHIPPED_MANIFESTS["docker"]))


@pytest.fixture
def tui_manifest() -> PhantomManifest:
    return load_manifest(str(SHIPPED_MANIFESTS["tui"]))
