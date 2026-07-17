"""Integration tests for file selector against real project structures."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from phantom.analyst.file_selector import FileSelector

# Optional real-project fixture: set PHANTOM_TEST_REAL_PROJECT=/path/to/a/project to
# exercise the selector against a real codebase. Skips when unset or missing.
_real = os.environ.get("PHANTOM_TEST_REAL_PROJECT")
_REAL_PROJECT = Path(_real) if _real else Path("/nonexistent-phantom-test-project")


@pytest.mark.integration
class TestFileSelectorRealProject:
    @pytest.mark.skipif(
        not _REAL_PROJECT.exists(),
        reason="real-project fixture not configured (set PHANTOM_TEST_REAL_PROJECT)",
    )
    async def test_selects_key_files(self) -> None:
        selector = FileSelector()
        files = await selector.select_files(_REAL_PROJECT, "tui")

        paths = [f.path for f in files]
        # Should pick up the key project files
        assert "pyproject.toml" in paths
        assert "README.md" in paths

    @pytest.mark.skipif(
        not _REAL_PROJECT.exists(),
        reason="real-project fixture not configured (set PHANTOM_TEST_REAL_PROJECT)",
    )
    async def test_respects_token_budget(self) -> None:
        selector = FileSelector(token_budget=25_000)
        files = await selector.select_files(_REAL_PROJECT, "tui")

        total = sum(f.token_estimate for f in files)
        # Allow small overflow from char/token rounding on last file
        assert total <= 25_100

    @pytest.mark.skipif(
        not _REAL_PROJECT.exists(),
        reason="real-project fixture not configured (set PHANTOM_TEST_REAL_PROJECT)",
    )
    async def test_skips_excluded_dirs(self) -> None:
        selector = FileSelector()
        files = await selector.select_files(_REAL_PROJECT, "tui")

        paths = [f.path for f in files]
        assert not any("node_modules" in p for p in paths)
        assert not any("__pycache__" in p for p in paths)
        assert not any(".git/" in p for p in paths)
        assert not any("venv/" in p for p in paths)

    @pytest.mark.skipif(
        not _REAL_PROJECT.exists(),
        reason="real-project fixture not configured (set PHANTOM_TEST_REAL_PROJECT)",
    )
    async def test_skips_binary_files(self) -> None:
        selector = FileSelector()
        files = await selector.select_files(_REAL_PROJECT, "tui")

        paths = [f.path for f in files]
        assert not any(p.endswith(".png") for p in paths)
        assert not any(p.endswith(".db") for p in paths)
        assert not any(p.endswith(".sqlite") for p in paths)
