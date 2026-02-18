"""Integration tests for file selector against real project structures."""

from __future__ import annotations

from pathlib import Path

import pytest

from phantom.analyst.file_selector import FileSelector

# Path to the youtube-playlist-manager project (used as a real-world fixture)
_YTPM_PATH = Path.home() / "Dropbox" / "workspace" / "youtube-playlist-manager"


@pytest.mark.integration
class TestFileSelectorRealProject:
    @pytest.mark.skipif(not _YTPM_PATH.exists(), reason="ytpm project not found")
    async def test_selects_key_files(self) -> None:
        selector = FileSelector()
        files = await selector.select_files(_YTPM_PATH, "tui")

        paths = [f.path for f in files]
        # Should pick up the key project files
        assert "pyproject.toml" in paths
        assert "README.md" in paths

    @pytest.mark.skipif(not _YTPM_PATH.exists(), reason="ytpm project not found")
    async def test_respects_token_budget(self) -> None:
        selector = FileSelector(token_budget=25_000)
        files = await selector.select_files(_YTPM_PATH, "tui")

        total = sum(f.token_estimate for f in files)
        # Allow small overflow from char/token rounding on last file
        assert total <= 25_100

    @pytest.mark.skipif(not _YTPM_PATH.exists(), reason="ytpm project not found")
    async def test_skips_excluded_dirs(self) -> None:
        selector = FileSelector()
        files = await selector.select_files(_YTPM_PATH, "tui")

        paths = [f.path for f in files]
        assert not any("node_modules" in p for p in paths)
        assert not any("__pycache__" in p for p in paths)
        assert not any(".git/" in p for p in paths)
        assert not any("venv/" in p for p in paths)

    @pytest.mark.skipif(not _YTPM_PATH.exists(), reason="ytpm project not found")
    async def test_skips_binary_files(self) -> None:
        selector = FileSelector()
        files = await selector.select_files(_YTPM_PATH, "tui")

        paths = [f.path for f in files]
        assert not any(p.endswith(".png") for p in paths)
        assert not any(p.endswith(".db") for p in paths)
        assert not any(p.endswith(".sqlite") for p in paths)
