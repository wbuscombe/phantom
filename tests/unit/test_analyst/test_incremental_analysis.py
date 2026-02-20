"""Tests for incremental analysis flow."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from phantom.analyst.analyzer import ProjectAnalyzer
from phantom.analyst.models import AnalysisPlan
from phantom.analyst.state import AnalystStateManager

if TYPE_CHECKING:
    from pathlib import Path


def _make_plan() -> AnalysisPlan:
    """Create a minimal valid AnalysisPlan."""
    from phantom.analyst.models import CaptureSpec

    return AnalysisPlan(
        project_type="web",
        project_name="Test Project",
        project_description="A test project",
        captures=[
            CaptureSpec(
                id="dashboard",
                name="Dashboard",
                description="Main dashboard view",
                alt_text="Dashboard screenshot",
                importance=5,
            ),
            CaptureSpec(
                id="settings",
                name="Settings",
                description="Settings page",
                alt_text="Settings screenshot",
                importance=3,
            ),
        ],
    )


def _setup_state(project_dir: Path, manifest_yaml: str) -> None:
    """Write a state file with a previous analysis."""
    mgr = AnalystStateManager(project_dir)
    mgr.load()
    mgr.update_after_analysis(
        commit_sha="abc123def456",
        manifest_yaml=manifest_yaml,
        cost_usd=0.10,
        input_tokens=5000,
        output_tokens=2000,
        recommendation="full",
    )


class TestAnalyzeIncremental:
    @pytest.mark.asyncio
    @patch("phantom.analyst.diff.subprocess.run")
    @patch("phantom.analyst.analyzer._get_anthropic_client")
    async def test_no_state_runs_full(
        self, mock_client: MagicMock, mock_git: MagicMock, tmp_path: Path
    ) -> None:
        """Without prior state, should run full analysis."""
        plan = _make_plan()
        plan_json = plan.model_dump_json()

        # Mock git
        mock_git.return_value = MagicMock(returncode=0, stdout="def456\n")

        # Mock API response
        client = MagicMock()
        mock_client.return_value = client
        response = MagicMock()
        response.content = [MagicMock(text=plan_json)]
        response.usage = MagicMock(input_tokens=3000, output_tokens=1500)
        client.messages.create.return_value = response

        analyzer = ProjectAnalyzer()

        # Create a pyproject.toml so detect_project_type works
        (tmp_path / "package.json").write_text("{}")

        _plan, diff_result = await analyzer.analyze_incremental(tmp_path)

        assert diff_result.recommendation == "full"
        assert "No prior analysis state" in diff_result.reason

    @pytest.mark.asyncio
    @patch("phantom.analyst.diff.subprocess.run")
    async def test_no_changes_skip(self, mock_git: MagicMock, tmp_path: Path) -> None:
        """No changes since last analysis → skip."""
        (tmp_path / "package.json").write_text("{}")

        # Set up state with a known commit
        manifest_yaml = "phantom: '1'\nproject: test\nname: Test\nsetup:\n  type: web\ncaptures:\n  - id: dashboard\n    name: Dashboard\n    alt_text: Dashboard screenshot\n    output: docs/screenshots/dashboard.png\n  - id: settings\n    name: Settings\n    alt_text: Settings screenshot\n    output: docs/screenshots/settings.png\n"
        _setup_state(tmp_path, manifest_yaml)

        # Mock git returning same SHA
        mock_git.return_value = MagicMock(returncode=0, stdout="abc123def456\n")

        analyzer = ProjectAnalyzer()
        plan, diff_result = await analyzer.analyze_incremental(tmp_path)

        assert diff_result.recommendation == "skip"
        assert plan is not None
        assert len(plan.captures) > 0

    @pytest.mark.asyncio
    @patch("phantom.analyst.diff.subprocess.run")
    async def test_force_full_overrides(self, mock_git: MagicMock, tmp_path: Path) -> None:
        """force_full=True should always run full analysis."""
        (tmp_path / "package.json").write_text("{}")

        plan = _make_plan()
        manifest_yaml = (
            "phantom: '1'\nproject: test\nname: Test\nsetup:\n  type: web\ncaptures: []\n"
        )
        _setup_state(tmp_path, manifest_yaml)

        # Mock git
        mock_git.side_effect = [
            MagicMock(returncode=0, stdout="abc123def456\n"),  # head_sha in analyze_incremental
            MagicMock(returncode=0, stdout="abc123def456\n"),  # head_sha in analyze
        ]

        # Need to mock API for full analysis
        with patch("phantom.analyst.analyzer._get_anthropic_client") as mock_client:
            client = MagicMock()
            mock_client.return_value = client
            response = MagicMock()
            response.content = [MagicMock(text=plan.model_dump_json())]
            response.usage = MagicMock(input_tokens=3000, output_tokens=1500)
            client.messages.create.return_value = response

            analyzer = ProjectAnalyzer()
            _plan, diff_result = await analyzer.analyze_incremental(tmp_path, force_full=True)

        assert diff_result.recommendation == "full"
        assert "Forced" in diff_result.reason

    @pytest.mark.asyncio
    @patch("phantom.analyst.diff.subprocess.run")
    async def test_css_change_triggers_full(self, mock_git: MagicMock, tmp_path: Path) -> None:
        """CSS changes should trigger full re-analysis."""
        (tmp_path / "package.json").write_text("{}")

        plan_obj = _make_plan()
        manifest_yaml = "phantom: '1'\nproject: test\nname: Test\nsetup:\n  type: web\ncaptures:\n  - id: dashboard\n    name: Dashboard\n    alt_text: Dashboard\n    output: docs/screenshots/dashboard.png\n"
        _setup_state(tmp_path, manifest_yaml)

        # Mock git: different SHA, CSS file changed
        mock_git.side_effect = [
            MagicMock(returncode=0, stdout="new_sha_456\n"),  # head_sha
            MagicMock(returncode=0, stdout="styles/main.css\n"),  # changed files
            MagicMock(returncode=0, stdout="new_sha_456\n"),  # head_sha in full analyze
        ]

        with patch("phantom.analyst.analyzer._get_anthropic_client") as mock_client:
            client = MagicMock()
            mock_client.return_value = client
            response = MagicMock()
            response.content = [MagicMock(text=plan_obj.model_dump_json())]
            response.usage = MagicMock(input_tokens=3000, output_tokens=1500)
            client.messages.create.return_value = response

            analyzer = ProjectAnalyzer()
            _plan, diff_result = await analyzer.analyze_incremental(tmp_path)

        assert diff_result.recommendation == "full"

    @pytest.mark.asyncio
    @patch("phantom.analyst.diff.subprocess.run")
    async def test_state_updated_after_analysis(self, mock_git: MagicMock, tmp_path: Path) -> None:
        """State should be updated with new commit SHA after analysis."""
        (tmp_path / "package.json").write_text("{}")

        # Mock git for skip case (same SHA)
        mock_git.return_value = MagicMock(returncode=0, stdout="abc123def456\n")

        manifest_yaml = "phantom: '1'\nproject: test\nname: Test\nsetup:\n  type: web\ncaptures:\n  - id: dashboard\n    name: Dashboard\n    alt_text: Dashboard\n    output: docs/screenshots/dashboard.png\n"
        _setup_state(tmp_path, manifest_yaml)

        analyzer = ProjectAnalyzer()
        await analyzer.analyze_incremental(tmp_path)

        # Verify state was updated
        mgr = AnalystStateManager(tmp_path)
        state = mgr.load()
        assert state.total_analyses == 2  # Original + skip
        assert state.skipped_analyses == 1
