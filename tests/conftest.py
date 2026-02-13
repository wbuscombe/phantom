"""Shared test fixtures for Phantom."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MANIFESTS_DIR = FIXTURES_DIR / "manifests"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def manifests_dir() -> Path:
    return MANIFESTS_DIR


@pytest.fixture
def valid_web_manifest(manifests_dir: Path) -> Path:
    return manifests_dir / "valid-web.yml"


@pytest.fixture
def minimal_manifest(manifests_dir: Path) -> Path:
    return manifests_dir / "minimal.yml"
