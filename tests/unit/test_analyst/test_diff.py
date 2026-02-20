"""Tests for git diff analysis."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from phantom.analyst.diff import DiffAnalyzer
from phantom.analyst.models import CaptureSpec


def _make_capture(
    capture_id: str,
    name: str = "Test",
    actions: list[dict[str, object]] | None = None,
) -> CaptureSpec:
    return CaptureSpec(
        id=capture_id,
        name=name,
        description=f"Capture for {name}",
        alt_text=f"Screenshot of {name}",
        importance=3,
        navigation_actions=actions or [],
    )


class TestGetHeadSha:
    @patch("phantom.analyst.diff.subprocess.run")
    def test_returns_sha(self, mock_run: MagicMock, tmp_path: object) -> None:
        from pathlib import Path

        mock_run.return_value = MagicMock(returncode=0, stdout="abc123def456\n")
        analyzer = DiffAnalyzer(Path(str(tmp_path)))
        assert analyzer.get_head_sha() == "abc123def456"

    @patch("phantom.analyst.diff.subprocess.run")
    def test_returns_none_on_failure(self, mock_run: MagicMock, tmp_path: object) -> None:
        from pathlib import Path

        mock_run.return_value = MagicMock(returncode=1, stdout="")
        analyzer = DiffAnalyzer(Path(str(tmp_path)))
        assert analyzer.get_head_sha() is None

    @patch("phantom.analyst.diff.subprocess.run", side_effect=FileNotFoundError)
    def test_returns_none_no_git(self, mock_run: MagicMock, tmp_path: object) -> None:
        from pathlib import Path

        analyzer = DiffAnalyzer(Path(str(tmp_path)))
        assert analyzer.get_head_sha() is None


class TestGetChangedFiles:
    @patch("phantom.analyst.diff.subprocess.run")
    def test_returns_files(self, mock_run: MagicMock, tmp_path: object) -> None:
        from pathlib import Path

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="src/app.tsx\nstyles/main.css\nREADME.md\n",
        )
        analyzer = DiffAnalyzer(Path(str(tmp_path)))
        files = analyzer.get_changed_files("abc123")
        assert files == ["src/app.tsx", "styles/main.css", "README.md"]

    @patch("phantom.analyst.diff.subprocess.run")
    def test_empty_diff(self, mock_run: MagicMock, tmp_path: object) -> None:
        from pathlib import Path

        mock_run.return_value = MagicMock(returncode=0, stdout="")
        analyzer = DiffAnalyzer(Path(str(tmp_path)))
        assert analyzer.get_changed_files("abc123") == []


class TestClassifyChanges:
    def test_web_visual_files(self, tmp_path: object) -> None:
        from pathlib import Path

        analyzer = DiffAnalyzer(Path(str(tmp_path)))
        result = analyzer.classify_changes(["src/App.tsx", "styles/main.css", "README.md"], "web")
        assert "src/App.tsx" in result["visual"]
        assert "styles/main.css" in result["visual"]
        assert "README.md" in result["non_visual"]

    def test_tui_visual_files(self, tmp_path: object) -> None:
        from pathlib import Path

        analyzer = DiffAnalyzer(Path(str(tmp_path)))
        result = analyzer.classify_changes(["src/main.py", "README.md", "tests/test_app.py"], "tui")
        assert "src/main.py" in result["visual"]
        assert "README.md" in result["non_visual"]
        assert "tests/test_app.py" in result["non_visual"]

    def test_skip_patterns(self, tmp_path: object) -> None:
        from pathlib import Path

        analyzer = DiffAnalyzer(Path(str(tmp_path)))
        result = analyzer.classify_changes(
            ["README.md", "CHANGELOG.md", ".github/workflows/ci.yml", "docs/screenshots/test.png"],
            "web",
        )
        assert all(f in result["non_visual"] for f in result["non_visual"])
        assert len(result["visual"]) == 0

    def test_unknown_files_treated_as_visual(self, tmp_path: object) -> None:
        from pathlib import Path

        analyzer = DiffAnalyzer(Path(str(tmp_path)))
        result = analyzer.classify_changes(["some_random_file.bin"], "web")
        assert "some_random_file.bin" in result["visual"]


class TestMapFilesToCaptures:
    def test_maps_by_id_terms(self, tmp_path: object) -> None:
        from pathlib import Path

        analyzer = DiffAnalyzer(Path(str(tmp_path)))
        captures = [
            _make_capture("dashboard-view", "Dashboard"),
            _make_capture("settings-page", "Settings"),
        ]
        result = analyzer.map_files_to_captures(["src/dashboard.tsx"], captures)
        assert "dashboard-view" in result

    def test_maps_by_navigation_url(self, tmp_path: object) -> None:
        from pathlib import Path

        analyzer = DiffAnalyzer(Path(str(tmp_path)))
        captures = [
            _make_capture(
                "login-page",
                "Login",
                [{"type": "navigate", "url": "/login"}],
            ),
        ]
        result = analyzer.map_files_to_captures(["src/login.tsx"], captures)
        assert "login-page" in result


class TestAnalyze:
    @patch("phantom.analyst.diff.subprocess.run")
    def test_no_prior_state_full(self, mock_run: MagicMock, tmp_path: object) -> None:
        from pathlib import Path

        mock_run.return_value = MagicMock(returncode=0, stdout="abc123\n")
        analyzer = DiffAnalyzer(Path(str(tmp_path)))
        result = analyzer.analyze(last_sha=None, captures=[])
        assert result.recommendation == "full"

    @patch("phantom.analyst.diff.subprocess.run")
    def test_no_changes_skip(self, mock_run: MagicMock, tmp_path: object) -> None:
        from pathlib import Path

        mock_run.return_value = MagicMock(returncode=0, stdout="abc123\n")
        analyzer = DiffAnalyzer(Path(str(tmp_path)))
        result = analyzer.analyze(last_sha="abc123", captures=[])
        assert result.recommendation == "skip"

    @patch("phantom.analyst.diff.subprocess.run")
    def test_only_non_visual_skip(self, mock_run: MagicMock, tmp_path: object) -> None:
        from pathlib import Path

        # First call: get_head_sha, second call: get_changed_files
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="def456\n"),
            MagicMock(returncode=0, stdout="README.md\nCHANGELOG.md\n"),
        ]
        analyzer = DiffAnalyzer(Path(str(tmp_path)))
        result = analyzer.analyze(last_sha="abc123", captures=[])
        assert result.recommendation == "skip"

    @patch("phantom.analyst.diff.subprocess.run")
    def test_css_change_full(self, mock_run: MagicMock, tmp_path: object) -> None:
        from pathlib import Path

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="def456\n"),
            MagicMock(returncode=0, stdout="styles/global.css\n"),
        ]
        captures = [_make_capture("dashboard"), _make_capture("settings")]
        analyzer = DiffAnalyzer(Path(str(tmp_path)))
        result = analyzer.analyze(last_sha="abc123", captures=captures, project_type="web")
        assert result.recommendation == "full"
        assert "style" in result.reason.lower()

    @patch("phantom.analyst.diff.subprocess.run")
    def test_incremental_recommendation(self, mock_run: MagicMock, tmp_path: object) -> None:
        from pathlib import Path

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="def456\n"),
            MagicMock(returncode=0, stdout="src/dashboard.tsx\n"),
        ]
        captures = [
            _make_capture("dashboard-view", "Dashboard"),
            _make_capture("settings-page", "Settings"),
            _make_capture("login-page", "Login"),
            _make_capture("profile-view", "Profile"),
        ]
        analyzer = DiffAnalyzer(Path(str(tmp_path)))
        result = analyzer.analyze(last_sha="abc123", captures=captures, project_type="web")
        assert result.recommendation == "incremental"
        assert "dashboard-view" in result.affected_capture_ids

    @patch("phantom.analyst.diff.subprocess.run")
    def test_many_captures_affected_full(self, mock_run: MagicMock, tmp_path: object) -> None:
        """When >75% captures are affected, recommend full."""
        from pathlib import Path

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="def456\n"),
            MagicMock(
                returncode=0,
                stdout="src/dashboard.tsx\nsrc/settings.tsx\nsrc/login.tsx\n",
            ),
        ]
        captures = [
            _make_capture("dashboard-view", "Dashboard"),
            _make_capture("settings-view", "Settings"),
            _make_capture("login-view", "Login"),
        ]
        analyzer = DiffAnalyzer(Path(str(tmp_path)))
        result = analyzer.analyze(last_sha="abc123", captures=captures, project_type="web")
        assert result.recommendation == "full"
        assert ">75%" in result.reason

    @patch("phantom.analyst.diff.subprocess.run")
    def test_git_not_available_full(self, mock_run: MagicMock, tmp_path: object) -> None:
        from pathlib import Path

        mock_run.side_effect = FileNotFoundError
        analyzer = DiffAnalyzer(Path(str(tmp_path)))
        result = analyzer.analyze(last_sha="abc123", captures=[])
        assert result.recommendation == "full"


class TestMatchesAny:
    def test_glob_match(self) -> None:
        assert DiffAnalyzer._matches_any("styles/main.css", ["*.css"])
        assert DiffAnalyzer._matches_any("src/App.tsx", ["*.tsx"])

    def test_path_match(self) -> None:
        assert DiffAnalyzer._matches_any("tests/test_foo.py", ["tests/**"])

    def test_no_match(self) -> None:
        assert not DiffAnalyzer._matches_any("binary.wasm", ["*.py", "*.tsx"])
