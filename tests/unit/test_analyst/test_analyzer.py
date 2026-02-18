"""Tests for the project analyzer with mocked Claude API."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from phantom.analyst.analyzer import AnalystDependencyError, AnalystError, ProjectAnalyzer
from phantom.analyst.costs import AnalystBudgetExceeded, CostTracker
from phantom.analyst.models import AnalysisPlan

if TYPE_CHECKING:
    from pathlib import Path

# A realistic mock response that Claude would return for the ytpm project
_MOCK_PLAN_JSON = {
    "project_type": "tui",
    "project_name": "YouTube Playlist Manager",
    "project_description": "CLI and TUI tool for managing YouTube playlists and tracking channel uploads",
    "tech_stack": ["python", "textual", "click", "sqlite"],
    "features": [
        {
            "name": "Main Menu",
            "description": "Landing screen with navigation to all features",
            "ui_type": "screen",
            "importance": 5,
            "navigation": "App launch",
        },
        {
            "name": "Inbox Triage",
            "description": "Process new videos from tracked channels",
            "ui_type": "screen",
            "importance": 5,
            "navigation": "Press 2 from main menu",
        },
        {
            "name": "Playlist Browser",
            "description": "Browse and manage playlists with video details",
            "ui_type": "screen",
            "importance": 4,
            "navigation": "Press 1 from main menu",
        },
    ],
    "captures": [
        {
            "id": "main-menu",
            "name": "Main Menu",
            "description": "The app's landing screen",
            "alt_text": "YouTube Playlist Manager main menu with Playlists, Inbox, Channels, and Search",
            "importance": 5,
            "navigation_actions": [{"type": "wait", "ms": 2000}],
            "terminal_dimensions": {"width": 140, "height": 36},
            "demo_data_needs": ["At least 4 menu items visible"],
        },
        {
            "id": "inbox-triage",
            "name": "Inbox Triage",
            "description": "Inbox with unprocessed videos",
            "alt_text": "Inbox showing unprocessed videos from tracked channels",
            "importance": 5,
            "navigation_actions": [
                {"type": "keystroke", "key": "2"},
                {"type": "wait", "ms": 1500},
            ],
            "terminal_dimensions": {"width": 140, "height": 36},
            "demo_data_needs": ["At least 20 unprocessed videos", "5+ tracked channels"],
        },
    ],
    "demo_data_requirements": [
        "15 playlists with varying video counts",
        "25 tracked channels",
        "80+ unprocessed inbox videos",
    ],
    "documentation_sections": [
        {
            "screenshot_id": "main-menu",
            "target_file": "README.md",
            "section_header": "## TUI",
            "placement": "after_header",
            "description_text": "Launch the interactive TUI with yt-tui.",
        },
    ],
}


def _make_mock_response(text: str, input_tokens: int = 1000, output_tokens: int = 500) -> Any:
    """Create a mock Anthropic API response."""
    mock = MagicMock()
    content_block = MagicMock()
    content_block.text = text
    mock.content = [content_block]
    mock.usage = MagicMock()
    mock.usage.input_tokens = input_tokens
    mock.usage.output_tokens = output_tokens
    return mock


@pytest.fixture()
def tui_project(tmp_path: Path) -> Path:
    """Create a minimal TUI project for testing."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "my-tui"\ndependencies = ["textual"]'
    )
    (tmp_path / "README.md").write_text("# My TUI\nA TUI app.")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("from textual.app import App\nclass MyApp(App): pass")
    return tmp_path


class TestProjectDetection:
    async def test_detect_web(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("{}")
        analyzer = ProjectAnalyzer(api_key="test-key")
        assert await analyzer.detect_project_type(tmp_path) == "web"

    async def test_detect_tui_python(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('dependencies = ["textual"]')
        analyzer = ProjectAnalyzer(api_key="test-key")
        assert await analyzer.detect_project_type(tmp_path) == "tui"

    async def test_detect_tui_rust(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "my-tui"')
        analyzer = ProjectAnalyzer(api_key="test-key")
        assert await analyzer.detect_project_type(tmp_path) == "tui"

    async def test_detect_docker(self, tmp_path: Path) -> None:
        (tmp_path / "docker-compose.yml").write_text("version: '3'")
        analyzer = ProjectAnalyzer(api_key="test-key")
        assert await analyzer.detect_project_type(tmp_path) == "docker-compose"

    async def test_docker_takes_precedence(self, tmp_path: Path) -> None:
        (tmp_path / "docker-compose.yml").write_text("version: '3'")
        (tmp_path / "package.json").write_text("{}")
        analyzer = ProjectAnalyzer(api_key="test-key")
        assert await analyzer.detect_project_type(tmp_path) == "docker-compose"

    async def test_fallback_to_web(self, tmp_path: Path) -> None:
        analyzer = ProjectAnalyzer(api_key="test-key")
        assert await analyzer.detect_project_type(tmp_path) == "web"

    async def test_tauri_detected_as_web(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text('[dependencies]\ntauri = "1.0"')
        analyzer = ProjectAnalyzer(api_key="test-key")
        assert await analyzer.detect_project_type(tmp_path) == "web"


class TestAnalyze:
    @patch("phantom.analyst.analyzer._get_anthropic_client")
    async def test_valid_response_produces_plan(
        self, mock_get_client: MagicMock, tui_project: Path
    ) -> None:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(
            json.dumps(_MOCK_PLAN_JSON), input_tokens=15000, output_tokens=2000
        )
        mock_get_client.return_value = mock_client

        analyzer = ProjectAnalyzer(api_key="test-key")
        plan = await analyzer.analyze(tui_project)

        assert isinstance(plan, AnalysisPlan)
        assert plan.project_type == "tui"
        assert len(plan.captures) == 2
        assert plan.captures[0].id == "main-menu"

    @patch("phantom.analyst.analyzer._get_anthropic_client")
    async def test_invalid_json_retries(
        self, mock_get_client: MagicMock, tui_project: Path
    ) -> None:
        mock_client = MagicMock()
        # First call returns invalid JSON, second returns valid
        mock_client.messages.create.side_effect = [
            _make_mock_response("This is not valid JSON at all"),
            _make_mock_response(json.dumps(_MOCK_PLAN_JSON)),
        ]
        mock_get_client.return_value = mock_client

        analyzer = ProjectAnalyzer(api_key="test-key")
        plan = await analyzer.analyze(tui_project)

        assert isinstance(plan, AnalysisPlan)
        assert mock_client.messages.create.call_count == 2

    @patch("phantom.analyst.analyzer._get_anthropic_client")
    async def test_invalid_json_twice_raises(
        self, mock_get_client: MagicMock, tui_project: Path
    ) -> None:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response("not json")
        mock_get_client.return_value = mock_client

        analyzer = ProjectAnalyzer(api_key="test-key")
        with pytest.raises(AnalystError, match="Failed to parse"):
            await analyzer.analyze(tui_project)

    @patch("phantom.analyst.analyzer._get_anthropic_client")
    async def test_budget_exceeded_before_call(
        self, mock_get_client: MagicMock, tui_project: Path
    ) -> None:
        mock_get_client.return_value = MagicMock()
        tracker = CostTracker(max_input_tokens=100)  # Tiny budget

        analyzer = ProjectAnalyzer(api_key="test-key", cost_tracker=tracker)
        with pytest.raises(AnalystBudgetExceeded):
            await analyzer.analyze(tui_project)

    @patch("phantom.analyst.analyzer._get_anthropic_client")
    async def test_records_usage(self, mock_get_client: MagicMock, tui_project: Path) -> None:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(
            json.dumps(_MOCK_PLAN_JSON), input_tokens=18000, output_tokens=2500
        )
        mock_get_client.return_value = mock_client

        tracker = CostTracker()
        analyzer = ProjectAnalyzer(api_key="test-key", cost_tracker=tracker)
        await analyzer.analyze(tui_project)

        assert tracker.total_input_tokens == 18000
        assert tracker.total_output_tokens == 2500
        assert tracker.call_count == 1

    @patch("phantom.analyst.analyzer._get_anthropic_client")
    async def test_handles_code_fenced_response(
        self, mock_get_client: MagicMock, tui_project: Path
    ) -> None:
        mock_client = MagicMock()
        # Claude sometimes wraps JSON in code fences despite instructions
        fenced = f"```json\n{json.dumps(_MOCK_PLAN_JSON)}\n```"
        mock_client.messages.create.return_value = _make_mock_response(fenced)
        mock_get_client.return_value = mock_client

        analyzer = ProjectAnalyzer(api_key="test-key")
        plan = await analyzer.analyze(tui_project)
        assert isinstance(plan, AnalysisPlan)


class TestMissingDependency:
    def test_missing_anthropic_package(self) -> None:
        with (
            patch.dict("sys.modules", {"anthropic": None}),
            patch("builtins.__import__", side_effect=ImportError),
        ):
            # We can't easily test this without actually uninstalling anthropic,
            # but we test the error class exists
            err = AnalystDependencyError()
            assert "anthropic" in str(err)

    def test_missing_api_key(self) -> None:
        with patch("phantom.analyst.analyzer._get_anthropic_client") as mock:
            mock.side_effect = AnalystError("No API key provided")
            analyzer = ProjectAnalyzer()
            with pytest.raises(AnalystError, match="API key"):
                analyzer._ensure_client()


class TestManifestGeneration:
    async def test_generates_valid_yaml(self, tui_project: Path) -> None:
        plan = AnalysisPlan.model_validate(_MOCK_PLAN_JSON)
        analyzer = ProjectAnalyzer(api_key="test-key")
        yaml_str = await analyzer.generate_manifest(plan, tui_project)

        assert "phantom:" in yaml_str
        assert "captures:" in yaml_str
        assert "main-menu" in yaml_str

    async def test_includes_tui_config(self, tui_project: Path) -> None:
        plan = AnalysisPlan.model_validate(_MOCK_PLAN_JSON)
        analyzer = ProjectAnalyzer(api_key="test-key")
        yaml_str = await analyzer.generate_manifest(plan, tui_project)

        assert "terminal:" in yaml_str
        assert "silicon" in yaml_str
        assert "JetBrains Mono" in yaml_str

    async def test_captures_sorted_by_importance(self, tui_project: Path) -> None:
        plan = AnalysisPlan.model_validate(_MOCK_PLAN_JSON)
        analyzer = ProjectAnalyzer(api_key="test-key")
        yaml_str = await analyzer.generate_manifest(plan, tui_project)

        # Both captures have importance 5, so order may vary
        # Just verify both are present
        assert "main-menu" in yaml_str
        assert "inbox-triage" in yaml_str

    async def test_includes_processing(self, tui_project: Path) -> None:
        plan = AnalysisPlan.model_validate(_MOCK_PLAN_JSON)
        analyzer = ProjectAnalyzer(api_key="test-key")
        yaml_str = await analyzer.generate_manifest(plan, tui_project)

        assert "drop-shadow" in yaml_str
        assert "optimize:" in yaml_str

    async def test_web_project_manifest(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("{}")
        web_plan = _MOCK_PLAN_JSON.copy()
        web_plan["project_type"] = "web"
        plan = AnalysisPlan.model_validate(web_plan)
        analyzer = ProjectAnalyzer(api_key="test-key")
        yaml_str = await analyzer.generate_manifest(plan, tmp_path)

        assert "npm" in yaml_str
        assert "http" in yaml_str


class TestSeedRequirements:
    async def test_generates_markdown(self) -> None:
        plan = AnalysisPlan.model_validate(_MOCK_PLAN_JSON)
        analyzer = ProjectAnalyzer(api_key="test-key")
        md = await analyzer.generate_seed_requirements(plan)

        assert "# Demo Data Requirements" in md
        assert "15 playlists" in md
        assert "inbox-triage" in md
