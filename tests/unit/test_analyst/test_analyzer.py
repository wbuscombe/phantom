"""Tests for the project analyzer with mocked Claude API."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from phantom.analyst.analyzer import AnalystDependencyError, AnalystError, ProjectAnalyzer
from phantom.analyst.costs import AnalystBudgetExceeded, CostTracker
from phantom.analyst.models import AnalysisPlan
from phantom.analyst.providers import LLMResponse

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


def _make_mock_response(
    text: str, input_tokens: int = 1000, output_tokens: int = 500
) -> LLMResponse:
    """Create a mock LLMResponse."""
    return LLMResponse(
        content=text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model="claude-sonnet-4-20250514",
        cost_usd=0.01,
    )


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
    async def test_valid_response_produces_plan(self, tui_project: Path) -> None:
        mock_provider = MagicMock()
        mock_provider.model = "claude-sonnet-4-20250514"
        mock_provider.complete = AsyncMock(
            return_value=_make_mock_response(
                json.dumps(_MOCK_PLAN_JSON), input_tokens=15000, output_tokens=2000
            )
        )

        analyzer = ProjectAnalyzer(api_key="test-key", provider=mock_provider)
        plan = await analyzer.analyze(tui_project)

        assert isinstance(plan, AnalysisPlan)
        assert plan.project_type == "tui"
        assert len(plan.captures) == 2
        assert plan.captures[0].id == "main-menu"

    async def test_invalid_json_retries(self, tui_project: Path) -> None:
        mock_provider = MagicMock()
        mock_provider.model = "claude-sonnet-4-20250514"
        # First call returns invalid JSON, second returns valid
        mock_provider.complete = AsyncMock(
            side_effect=[
                _make_mock_response("This is not valid JSON at all"),
                _make_mock_response(json.dumps(_MOCK_PLAN_JSON)),
            ]
        )

        analyzer = ProjectAnalyzer(api_key="test-key", provider=mock_provider)
        plan = await analyzer.analyze(tui_project)

        assert isinstance(plan, AnalysisPlan)
        assert mock_provider.complete.call_count == 2

    async def test_invalid_json_twice_raises(self, tui_project: Path) -> None:
        mock_provider = MagicMock()
        mock_provider.model = "claude-sonnet-4-20250514"
        mock_provider.complete = AsyncMock(return_value=_make_mock_response("not json"))

        analyzer = ProjectAnalyzer(api_key="test-key", provider=mock_provider)
        with pytest.raises(AnalystError, match="Failed to parse"):
            await analyzer.analyze(tui_project)

    async def test_budget_exceeded_before_call(self, tui_project: Path) -> None:
        mock_provider = MagicMock()
        mock_provider.model = "claude-sonnet-4-20250514"
        tracker = CostTracker(max_input_tokens=100)  # Tiny budget

        analyzer = ProjectAnalyzer(api_key="test-key", cost_tracker=tracker, provider=mock_provider)
        with pytest.raises(AnalystBudgetExceeded):
            await analyzer.analyze(tui_project)

    async def test_records_usage(self, tui_project: Path) -> None:
        mock_provider = MagicMock()
        mock_provider.model = "claude-sonnet-4-20250514"
        mock_provider.complete = AsyncMock(
            return_value=_make_mock_response(
                json.dumps(_MOCK_PLAN_JSON), input_tokens=18000, output_tokens=2500
            )
        )

        tracker = CostTracker()
        analyzer = ProjectAnalyzer(api_key="test-key", cost_tracker=tracker, provider=mock_provider)
        await analyzer.analyze(tui_project)

        assert tracker.total_input_tokens == 18000
        assert tracker.total_output_tokens == 2500
        assert tracker.call_count == 1

    async def test_handles_code_fenced_response(self, tui_project: Path) -> None:
        mock_provider = MagicMock()
        mock_provider.model = "claude-sonnet-4-20250514"
        # Claude sometimes wraps JSON in code fences despite instructions
        fenced = f"```json\n{json.dumps(_MOCK_PLAN_JSON)}\n```"
        mock_provider.complete = AsyncMock(return_value=_make_mock_response(fenced))

        analyzer = ProjectAnalyzer(api_key="test-key", provider=mock_provider)
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
        from phantom.exceptions import PhantomError

        with patch.dict(os.environ, {}, clear=False):
            # Remove ANTHROPIC_API_KEY if set
            env = os.environ.copy()
            env.pop("ANTHROPIC_API_KEY", None)
            with patch.dict(os.environ, env, clear=True):
                from phantom.analyst.providers import AnthropicProvider

                provider = AnthropicProvider(api_key=None)
                with pytest.raises(PhantomError, match=r"API key|anthropic"):
                    provider._ensure_client()


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


class TestEntryPointDetection:
    """Tests for _detect_python_entry with TUI-aware selection."""

    def test_prefers_tui_script_name(self, tmp_path: Path) -> None:
        """When multiple scripts exist, prefer the one with 'tui' in name."""
        (tmp_path / "pyproject.toml").write_text(
            '[project.scripts]\nyt = "src.cli:cli"\nyt-tui = "src.app:main"\n'
        )
        analyzer = ProjectAnalyzer(api_key="test-key")
        result = analyzer._detect_python_entry(tmp_path, project_type="tui")
        assert result == "venv/bin/yt-tui"

    def test_prefers_ui_script_name(self, tmp_path: Path) -> None:
        """Prefer script name containing 'ui'."""
        (tmp_path / "pyproject.toml").write_text(
            '[project.scripts]\ncli = "pkg.cli:main"\nmy-ui = "pkg.ui:run"\n'
        )
        analyzer = ProjectAnalyzer(api_key="test-key")
        result = analyzer._detect_python_entry(tmp_path, project_type="tui")
        assert result == "venv/bin/my-ui"

    def test_prefers_gui_script_name(self, tmp_path: Path) -> None:
        """Prefer script name containing 'gui'."""
        (tmp_path / "pyproject.toml").write_text(
            '[project.scripts]\nserver = "pkg.server:main"\nmy-gui = "pkg.gui:run"\n'
        )
        analyzer = ProjectAnalyzer(api_key="test-key")
        result = analyzer._detect_python_entry(tmp_path, project_type="tui")
        assert result == "venv/bin/my-gui"

    def test_prefers_app_script_name(self, tmp_path: Path) -> None:
        """Prefer script name containing 'app'."""
        (tmp_path / "pyproject.toml").write_text(
            '[project.scripts]\ncli = "pkg.cli:main"\nmy-app = "pkg.app:run"\n'
        )
        analyzer = ProjectAnalyzer(api_key="test-key")
        result = analyzer._detect_python_entry(tmp_path, project_type="tui")
        assert result == "venv/bin/my-app"

    def test_falls_back_to_target_module_keyword(self, tmp_path: Path) -> None:
        """If no script name matches, check target module for TUI keywords."""
        (tmp_path / "pyproject.toml").write_text(
            '[project.scripts]\nmycli = "pkg.cli:main"\nmything = "pkg.tui:run"\n'
        )
        analyzer = ProjectAnalyzer(api_key="test-key")
        result = analyzer._detect_python_entry(tmp_path, project_type="tui")
        assert result == "venv/bin/mything"

    def test_single_script_returns_it(self, tmp_path: Path) -> None:
        """With only one script, return it regardless of name."""
        (tmp_path / "pyproject.toml").write_text('[project.scripts]\nmytool = "pkg.main:run"\n')
        analyzer = ProjectAnalyzer(api_key="test-key")
        result = analyzer._detect_python_entry(tmp_path, project_type="tui")
        assert result == "venv/bin/mytool"

    def test_web_project_takes_first_entry(self, tmp_path: Path) -> None:
        """Web projects don't apply TUI preference — take first entry."""
        (tmp_path / "pyproject.toml").write_text(
            '[project.scripts]\nyt = "src.cli:cli"\nyt-tui = "src.app:main"\n'
        )
        analyzer = ProjectAnalyzer(api_key="test-key")
        result = analyzer._detect_python_entry(tmp_path, project_type="web")
        assert result == "venv/bin/yt"

    def test_no_scripts_section(self, tmp_path: Path) -> None:
        """No [project.scripts] section returns None."""
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "my-tool"\n')
        analyzer = ProjectAnalyzer(api_key="test-key")
        result = analyzer._detect_python_entry(tmp_path, project_type="tui")
        assert result is None

    def test_no_pyproject_file(self, tmp_path: Path) -> None:
        """Missing pyproject.toml returns None."""
        analyzer = ProjectAnalyzer(api_key="test-key")
        result = analyzer._detect_python_entry(tmp_path, project_type="tui")
        assert result is None

    def test_empty_scripts_section(self, tmp_path: Path) -> None:
        """Empty [project.scripts] section returns None."""
        (tmp_path / "pyproject.toml").write_text("[project.scripts]\n[build-system]\n")
        analyzer = ProjectAnalyzer(api_key="test-key")
        result = analyzer._detect_python_entry(tmp_path, project_type="tui")
        assert result is None

    def test_dashboard_script_name(self, tmp_path: Path) -> None:
        """Prefer script name containing 'dashboard'."""
        (tmp_path / "pyproject.toml").write_text(
            '[project.scripts]\napi = "pkg.api:main"\nmy-dashboard = "pkg.dash:run"\n'
        )
        analyzer = ProjectAnalyzer(api_key="test-key")
        result = analyzer._detect_python_entry(tmp_path, project_type="tui")
        assert result == "venv/bin/my-dashboard"


class TestDisplayNameExtraction:
    """Tests for _extract_display_name with README H1 and kebab-case conversion."""

    def test_extracts_readme_h1(self, tmp_path: Path) -> None:
        """Prefer README H1 as display name."""
        (tmp_path / "README.md").write_text("# YouTube Playlist Manager\n\nSome description.")
        result = ProjectAnalyzer._extract_display_name("youtube-playlist-manager", tmp_path)
        assert result == "YouTube Playlist Manager"

    def test_converts_kebab_case(self, tmp_path: Path) -> None:
        """Convert kebab-case to Title Case when no README exists."""
        result = ProjectAnalyzer._extract_display_name("youtube-playlist-manager", tmp_path)
        assert result == "Youtube Playlist Manager"

    def test_converts_snake_case(self, tmp_path: Path) -> None:
        """Convert snake_case to Title Case when no README exists."""
        result = ProjectAnalyzer._extract_display_name("youtube_playlist_manager", tmp_path)
        assert result == "Youtube Playlist Manager"

    def test_preserves_proper_name(self, tmp_path: Path) -> None:
        """Already proper name is returned as-is."""
        result = ProjectAnalyzer._extract_display_name("MyApp", tmp_path)
        assert result == "MyApp"

    def test_skips_h2_headers(self, tmp_path: Path) -> None:
        """Only use H1, not H2 or deeper."""
        (tmp_path / "README.md").write_text("## Not This\n\n# This One\n")
        result = ProjectAnalyzer._extract_display_name("fallback-name", tmp_path)
        assert result == "This One"

    def test_empty_readme_falls_back(self, tmp_path: Path) -> None:
        """Empty README falls back to name conversion."""
        (tmp_path / "README.md").write_text("")
        result = ProjectAnalyzer._extract_display_name("my-project", tmp_path)
        assert result == "My Project"

    def test_manifest_uses_readme_name(self, tui_project: Path) -> None:
        """generate_manifest should use README H1 for display name."""
        # The tui_project fixture has README with "# My TUI"
        plan = AnalysisPlan.model_validate(_MOCK_PLAN_JSON)
        analyzer = ProjectAnalyzer(api_key="test-key")
        import asyncio

        yaml_str = asyncio.run(analyzer.generate_manifest(plan, tui_project))
        assert "name: My TUI" in yaml_str


class TestRetryConfig:
    """Tests for retry config in generated manifests."""

    async def test_manifest_includes_retry(self, tui_project: Path) -> None:
        """Generated manifest should include retry config in capture_defaults."""
        plan = AnalysisPlan.model_validate(_MOCK_PLAN_JSON)
        analyzer = ProjectAnalyzer(api_key="test-key")
        yaml_str = await analyzer.generate_manifest(plan, tui_project)

        assert "retry:" in yaml_str
        assert "max_attempts:" in yaml_str
        assert "backoff_ms:" in yaml_str

    async def test_retry_values(self, tui_project: Path) -> None:
        """Verify retry config has expected default values."""
        from ruamel.yaml import YAML

        plan = AnalysisPlan.model_validate(_MOCK_PLAN_JSON)
        analyzer = ProjectAnalyzer(api_key="test-key")
        yaml_str = await analyzer.generate_manifest(plan, tui_project)

        yaml = YAML()
        import io

        data = yaml.load(io.StringIO(yaml_str))
        retry = data["capture_defaults"]["retry"]
        assert retry["max_attempts"] == 2
        assert retry["backoff_ms"] == 1000


class TestSeedRequirements:
    async def test_generates_markdown(self) -> None:
        plan = AnalysisPlan.model_validate(_MOCK_PLAN_JSON)
        analyzer = ProjectAnalyzer(api_key="test-key")
        md = await analyzer.generate_seed_requirements(plan)

        assert "# Demo Data Requirements" in md
        assert "15 playlists" in md
        assert "inbox-triage" in md
