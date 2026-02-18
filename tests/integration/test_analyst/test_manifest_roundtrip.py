"""Integration test: generate manifest from plan, validate with phantom."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from phantom.analyst.analyzer import ProjectAnalyzer
from phantom.analyst.models import AnalysisPlan

if TYPE_CHECKING:
    from pathlib import Path

_MOCK_PLAN = {
    "project_type": "tui",
    "project_name": "Test TUI App",
    "project_description": "A test terminal UI application",
    "tech_stack": ["python", "textual"],
    "features": [
        {
            "name": "Main Menu",
            "description": "Landing screen",
            "ui_type": "screen",
            "importance": 5,
            "navigation": "App launch",
        },
    ],
    "captures": [
        {
            "id": "main-menu",
            "name": "Main Menu",
            "description": "The app's landing screen",
            "alt_text": "Main menu with navigation options",
            "importance": 5,
            "navigation_actions": [{"type": "wait", "ms": 2000}],
            "terminal_dimensions": {"width": 140, "height": 36},
            "demo_data_needs": [],
        },
        {
            "id": "feature-view",
            "name": "Feature View",
            "description": "A key feature of the app",
            "alt_text": "Feature view showing data",
            "importance": 4,
            "navigation_actions": [
                {"type": "keystroke", "key": "1"},
                {"type": "wait", "ms": 1500},
            ],
            "terminal_dimensions": {"width": 140, "height": 36},
            "demo_data_needs": ["Sample data entries"],
        },
    ],
    "demo_data_requirements": ["Some sample data"],
    "documentation_sections": [
        {
            "screenshot_id": "main-menu",
            "target_file": "README.md",
            "section_header": "## Getting Started",
            "placement": "after_header",
            "description_text": "Launch the app to see the main menu.",
        },
    ],
}


@pytest.mark.integration
class TestManifestRoundtrip:
    async def test_generated_manifest_validates(self, tmp_path: Path) -> None:
        """Generate a manifest from a mock plan and validate it with phantom validate."""
        # Create a minimal project dir
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"')

        plan = AnalysisPlan.model_validate(_MOCK_PLAN)
        analyzer = ProjectAnalyzer(api_key="test-key")
        yaml_str = await analyzer.generate_manifest(plan, tmp_path)

        # Write to a temp file
        manifest_path = tmp_path / ".phantom.yml"
        manifest_path.write_text(yaml_str)

        # Run phantom validate
        result = subprocess.run(
            ["phantom", "validate", str(manifest_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"phantom validate failed:\n{result.stderr}\n{result.stdout}"
        assert "Manifest is valid" in result.stdout

    async def test_manifest_has_correct_structure(self, tmp_path: Path) -> None:
        """Verify the generated YAML has the expected top-level keys."""
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"')

        plan = AnalysisPlan.model_validate(_MOCK_PLAN)
        analyzer = ProjectAnalyzer(api_key="test-key")
        yaml_str = await analyzer.generate_manifest(plan, tmp_path)

        from ruamel.yaml import YAML

        yaml = YAML()
        import io

        data = yaml.load(io.StringIO(yaml_str))

        assert data["phantom"] == "1"
        assert "setup" in data
        assert "captures" in data
        assert len(data["captures"]) == 2
        assert "processing" in data
        assert "publishing" in data
