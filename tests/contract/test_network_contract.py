"""CONTRACT.md §1 — Network allowlist.

Under PHANTOM_MODE the consumer app must reach healthy with no external network
beyond a loopback allowlist plus hosts explicitly declared in the manifest
(ready_check / fixtures). Phantom's own probes only ever contact hosts in
``manifest_allowlist()``.
"""

from __future__ import annotations

from typing import Any

from phantom import contract
from phantom.models import PhantomManifest


def _manifest_with(ready_url: str, fixture_url: str | None = None) -> PhantomManifest:
    data: dict[str, Any] = {
        "phantom": "1",
        "project": "demo-app",
        "name": "Demo App",
        "setup": {
            "type": "web",
            "run": {
                "command": "python server.py",
                "ready_check": {"type": "http", "url": ready_url},
            },
        },
        "captures": [{"id": "home", "name": "Home", "output": "docs/screenshots/home.png"}],
    }
    if fixture_url is not None:
        data["fixtures"] = [{"name": "seed", "type": "http", "url": fixture_url, "method": "POST"}]
    return PhantomManifest.model_validate(data)


def test_loopback_hosts_always_allowed() -> None:
    m = _manifest_with("http://localhost:3000")
    for host in ["localhost", "127.0.0.1", "::1", "0.0.0.0"]:
        assert contract.is_host_allowed(host, m)


def test_declared_ready_check_host_is_allowed() -> None:
    m = _manifest_with("http://app.internal:8080")
    assert "app.internal" in contract.manifest_allowlist(m)
    assert contract.is_host_allowed("http://app.internal:8080/health", m)


def test_declared_fixture_host_is_allowed() -> None:
    m = _manifest_with("http://localhost:3000", fixture_url="http://seed.internal/api")
    assert "seed.internal" in contract.manifest_allowlist(m)


def test_undeclared_external_host_is_not_allowed() -> None:
    m = _manifest_with("http://localhost:3000")
    assert not contract.is_host_allowed("https://api.stripe.com", m)
    assert not contract.is_host_allowed("evil.example.com", m)


def test_shipped_fixtures_only_touch_loopback(shipped_manifest: PhantomManifest) -> None:
    # Every host Phantom would contact for a shipped fixture is loopback — the
    # reference manifests are fully self-contained.
    allow = contract.manifest_allowlist(shipped_manifest)
    non_loopback = allow - set(contract.LOOPBACK_HOSTS)
    assert non_loopback == set(), f"shipped manifest reaches non-loopback host(s): {non_loopback}"
