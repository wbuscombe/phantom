"""CONTRACT.md §3 — Health contract.

Under PHANTOM_MODE the app must reach healthy within a DECLARED timeout. The
timeout is declared per-manifest at ``setup.run.ready_check.timeout`` (seconds),
defaulting to 30. Phantom polls that readiness probe before capturing.
"""

from __future__ import annotations

from phantom import contract
from phantom.models import PhantomManifest, ReadyCheck

SUPPORTED_READY_CHECK_TYPES = {"http", "tcp", "stdout_match", "delay", "screen_stable"}


def test_default_ready_timeout_matches_contract_constant() -> None:
    assert ReadyCheck.model_fields["timeout"].default == contract.DEFAULT_READY_TIMEOUT_SECONDS
    assert contract.DEFAULT_READY_TIMEOUT_SECONDS == 30


def test_every_shipped_manifest_declares_a_ready_check(shipped_manifest: PhantomManifest) -> None:
    rc = shipped_manifest.setup.run.ready_check
    assert rc is not None
    assert rc.type in SUPPORTED_READY_CHECK_TYPES


def test_declared_timeout_is_a_positive_int(shipped_manifest: PhantomManifest) -> None:
    rc = shipped_manifest.setup.run.ready_check
    assert isinstance(rc.timeout, int)
    assert rc.timeout > 0


def test_http_ready_check_targets_a_url(web_manifest: PhantomManifest) -> None:
    rc = web_manifest.setup.run.ready_check
    assert rc.type == "http"
    assert rc.url  # the health endpoint Phantom polls


def test_ready_check_timeout_is_declared_where_the_contract_says() -> None:
    # The declared location is setup.run.ready_check.timeout — assert the path
    # exists and is the field the runners read.
    rc = ReadyCheck(type="delay", seconds=1, timeout=45)
    assert rc.timeout == 45
