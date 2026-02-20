"""Integration tests for diff analysis with real git repos."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from phantom.analyst.diff import DiffAnalyzer
from phantom.analyst.models import CaptureSpec

if TYPE_CHECKING:
    from pathlib import Path


def _git(cwd: Path, *args: str) -> str:
    """Run a git command in the given directory."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result.stdout.strip()


def _init_repo(path: Path) -> str:
    """Initialize a git repo with an initial commit. Returns initial SHA."""
    _git(path, "init")
    _git(path, "config", "user.email", "test@test.com")
    _git(path, "config", "user.name", "Test")

    (path / "README.md").write_text("# Test Project\n")
    (path / "src").mkdir()
    (path / "src" / "app.tsx").write_text(
        "export default function App() { return <div>Hello</div>; }"
    )
    (path / "styles").mkdir()
    (path / "styles" / "main.css").write_text("body { color: black; }")

    _git(path, "add", ".")
    _git(path, "commit", "-m", "Initial commit")
    return _git(path, "rev-parse", "HEAD")


class TestDiffAnalyzerReal:
    def test_head_sha(self, tmp_path: Path) -> None:
        initial_sha = _init_repo(tmp_path)
        analyzer = DiffAnalyzer(tmp_path)
        assert analyzer.get_head_sha() == initial_sha

    def test_no_changes(self, tmp_path: Path) -> None:
        initial_sha = _init_repo(tmp_path)
        analyzer = DiffAnalyzer(tmp_path)
        files = analyzer.get_changed_files(initial_sha)
        assert files == []

    def test_detect_changed_files(self, tmp_path: Path) -> None:
        initial_sha = _init_repo(tmp_path)

        # Make a change
        (tmp_path / "src" / "app.tsx").write_text(
            "export default function App() { return <div>Updated</div>; }"
        )
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "-m", "Update app")

        analyzer = DiffAnalyzer(tmp_path)
        files = analyzer.get_changed_files(initial_sha)
        assert "src/app.tsx" in files

    def test_classify_real_changes(self, tmp_path: Path) -> None:
        initial_sha = _init_repo(tmp_path)

        # Change visual and non-visual files
        (tmp_path / "src" / "app.tsx").write_text("updated")
        (tmp_path / "README.md").write_text("# Updated README\n")
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "-m", "Mixed changes")

        analyzer = DiffAnalyzer(tmp_path)
        files = analyzer.get_changed_files(initial_sha)
        classified = analyzer.classify_changes(files, "web")

        assert "src/app.tsx" in classified["visual"]
        assert "README.md" in classified["non_visual"]

    def test_full_analysis_flow(self, tmp_path: Path) -> None:
        initial_sha = _init_repo(tmp_path)

        captures = [
            CaptureSpec(
                id="app-view",
                name="App View",
                description="Main app",
                alt_text="App screenshot",
                importance=5,
                navigation_actions=[{"type": "navigate", "url": "/app"}],
            ),
        ]

        # No changes
        analyzer = DiffAnalyzer(tmp_path)
        result = analyzer.analyze(last_sha=initial_sha, captures=captures, project_type="web")
        assert result.recommendation == "skip"

        # Make a visual change
        (tmp_path / "src" / "app.tsx").write_text("updated content")
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "-m", "Update app")

        result = analyzer.analyze(last_sha=initial_sha, captures=captures, project_type="web")
        assert result.recommendation in ("incremental", "full")
        assert len(result.changed_files) > 0

    def test_only_non_visual_changes(self, tmp_path: Path) -> None:
        initial_sha = _init_repo(tmp_path)

        (tmp_path / "README.md").write_text("# Updated\n")
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "-m", "Docs update")

        analyzer = DiffAnalyzer(tmp_path)
        result = analyzer.analyze(last_sha=initial_sha, captures=[], project_type="web")
        assert result.recommendation == "skip"
        assert "non-visual" in result.reason.lower()

    def test_css_triggers_full(self, tmp_path: Path) -> None:
        initial_sha = _init_repo(tmp_path)

        (tmp_path / "styles" / "main.css").write_text("body { color: red; }")
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "-m", "Style update")

        captures = [
            CaptureSpec(
                id="test-view",
                name="Test",
                description="Test",
                alt_text="Test",
                importance=3,
            ),
        ]

        analyzer = DiffAnalyzer(tmp_path)
        result = analyzer.analyze(last_sha=initial_sha, captures=captures, project_type="web")
        assert result.recommendation == "full"
        assert "style" in result.reason.lower()


class TestNonGitDirectory:
    def test_non_git_dir_returns_none(self, tmp_path: Path) -> None:
        analyzer = DiffAnalyzer(tmp_path)
        assert analyzer.get_head_sha() is None

    def test_non_git_dir_full_recommendation(self, tmp_path: Path) -> None:
        analyzer = DiffAnalyzer(tmp_path)
        result = analyzer.analyze(last_sha="abc123", captures=[])
        assert result.recommendation == "full"
