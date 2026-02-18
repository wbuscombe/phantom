"""Tests for analyst file selector."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from phantom.analyst.file_selector import _SKIP_DIRS, _SKIP_EXTENSIONS, FileSelector

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """Create a minimal project structure for testing."""
    # Create project files
    (tmp_path / "package.json").write_text('{"name": "test-app", "dependencies": {}}')
    (tmp_path / "README.md").write_text("# Test App\n\nA test application.")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.ts").write_text("import { App } from './app'\nApp.start()")
    (tmp_path / "src" / "app.tsx").write_text("export function App() { return <div>Hello</div> }")
    (tmp_path / "src" / "pages").mkdir()
    (tmp_path / "src" / "pages" / "home.tsx").write_text(
        "export function Home() { return <h1>Home</h1> }"
    )
    (tmp_path / "src" / "pages" / "settings.tsx").write_text(
        "export function Settings() { return <h1>Settings</h1> }"
    )

    # Files that should be skipped
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "react.js").write_text("module.exports = {}")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n")
    (tmp_path / "package-lock.json").write_text("{}")

    return tmp_path


@pytest.fixture()
def tui_project(tmp_path: Path) -> Path:
    """Create a TUI project structure."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "my-tui"\ndependencies = ["textual"]'
    )
    (tmp_path / "README.md").write_text("# My TUI")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("from textual.app import App\nclass MyApp(App): pass")
    (tmp_path / "src" / "screens").mkdir()
    (tmp_path / "src" / "screens" / "main.py").write_text("class MainScreen: pass")
    (tmp_path / "src" / "screens" / "inbox.py").write_text("class InboxScreen: pass")
    return tmp_path


class TestFileSelector:
    async def test_web_project_selection(self, tmp_project: Path) -> None:
        selector = FileSelector()
        files = await selector.select_files(tmp_project, "web")

        paths = [f.path for f in files]
        assert "package.json" in paths
        assert "README.md" in paths
        assert "src/app.tsx" in paths or "src/index.ts" in paths

    async def test_skips_node_modules(self, tmp_project: Path) -> None:
        selector = FileSelector()
        files = await selector.select_files(tmp_project, "web")
        paths = [f.path for f in files]
        assert not any("node_modules" in p for p in paths)

    async def test_skips_binary_files(self, tmp_project: Path) -> None:
        selector = FileSelector()
        files = await selector.select_files(tmp_project, "web")
        paths = [f.path for f in files]
        assert not any(p.endswith(".png") for p in paths)

    async def test_skips_lock_files(self, tmp_project: Path) -> None:
        selector = FileSelector()
        files = await selector.select_files(tmp_project, "web")
        paths = [f.path for f in files]
        assert "package-lock.json" not in paths

    async def test_tui_project_selection(self, tui_project: Path) -> None:
        selector = FileSelector()
        files = await selector.select_files(tui_project, "tui")
        paths = [f.path for f in files]
        assert "pyproject.toml" in paths
        assert "README.md" in paths

    async def test_token_budget_respected(self, tmp_path: Path) -> None:
        """File selector should stay roughly within the token budget."""
        # Create a project with many large files
        (tmp_path / "package.json").write_text('{"name": "big"}')
        (tmp_path / "src").mkdir()
        for i in range(20):
            (tmp_path / "src" / f"file{i}.ts").write_text("x" * 10_000)

        selector = FileSelector(token_budget=5_000)
        files = await selector.select_files(tmp_path, "web")

        total_tokens = sum(f.token_estimate for f in files)
        # Allow small overflow from truncation rounding (char/token estimate)
        assert total_tokens <= 5_100

    async def test_file_truncation(self, tmp_path: Path) -> None:
        """Long files should be truncated."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / "big.ts").write_text("\n".join(f"line {i}" for i in range(1000)))

        selector = FileSelector()
        files = await selector.select_files(tmp_path, "web")

        big_files = [f for f in files if f.path == "big.ts"]
        if big_files:
            assert "truncated" in big_files[0].content

    async def test_token_estimate_populated(self, tmp_project: Path) -> None:
        selector = FileSelector()
        files = await selector.select_files(tmp_project, "web")
        for f in files:
            assert f.token_estimate > 0

    def test_skip_dirs_comprehensive(self) -> None:
        assert "node_modules" in _SKIP_DIRS
        assert "__pycache__" in _SKIP_DIRS
        assert ".git" in _SKIP_DIRS
        assert "dist" in _SKIP_DIRS

    def test_skip_extensions_comprehensive(self) -> None:
        assert ".png" in _SKIP_EXTENSIONS
        assert ".lock" in _SKIP_EXTENSIONS
        assert ".pyc" in _SKIP_EXTENSIONS
