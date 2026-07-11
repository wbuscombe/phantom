"""CONTRACT.md §5 — Versioning rules.

The contract version is frozen at 1.0.0 for this release and is exposed on the
package so consumers can assert against it independently of the package version.
"""

from __future__ import annotations

import phantom
from phantom import contract


def test_contract_version_is_frozen_at_1_0_0() -> None:
    assert contract.CONTRACT_VERSION == "1.0.0"


def test_contract_version_is_semver() -> None:
    parts = contract.CONTRACT_VERSION.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)


def test_package_exposes_contract_version() -> None:
    # Consumers pin `phantom-docs==0.4.*` but assert on the contract version.
    assert phantom.__contract_version__ == contract.CONTRACT_VERSION
    assert phantom.CONTRACT_VERSION == contract.CONTRACT_VERSION


def test_package_version_is_independent_of_contract_version() -> None:
    # The two version lines move independently (CONTRACT.md §5); this simply
    # asserts both exist and are non-empty strings.
    assert isinstance(phantom.__version__, str) and phantom.__version__
    assert isinstance(phantom.__contract_version__, str) and phantom.__contract_version__
