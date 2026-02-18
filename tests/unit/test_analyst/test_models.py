"""Tests for analyst Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from phantom.analyst.models import AnalysisPlan, CaptureSpec, DocSection, Feature


class TestFeature:
    def test_valid_feature(self) -> None:
        f = Feature(
            name="Inbox",
            description="Triage new videos",
            ui_type="screen",
            importance=5,
            navigation="Press 2 from main menu",
        )
        assert f.name == "Inbox"
        assert f.importance == 5

    def test_invalid_ui_type(self) -> None:
        with pytest.raises(ValidationError, match="ui_type"):
            Feature(
                name="X",
                description="Y",
                ui_type="popup",
                importance=3,
                navigation="click",
            )

    def test_importance_bounds(self) -> None:
        with pytest.raises(ValidationError):
            Feature(name="X", description="Y", ui_type="screen", importance=0, navigation="n")
        with pytest.raises(ValidationError):
            Feature(name="X", description="Y", ui_type="screen", importance=6, navigation="n")

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Feature(name="", description="Y", ui_type="screen", importance=3, navigation="n")


class TestCaptureSpec:
    def test_valid_capture(self) -> None:
        c = CaptureSpec(
            id="main-menu",
            name="Main Menu",
            description="Shows the main menu",
            alt_text="Main menu with 4 options",
            importance=5,
            navigation_actions=[{"type": "wait", "ms": 2000}],
        )
        assert c.id == "main-menu"

    def test_kebab_case_enforced(self) -> None:
        with pytest.raises(ValidationError, match="kebab-case"):
            CaptureSpec(
                id="Main_Menu",
                name="X",
                description="Y",
                alt_text="Z",
                importance=3,
            )

    def test_single_word_id(self) -> None:
        c = CaptureSpec(id="inbox", name="X", description="Y", alt_text="Z", importance=3)
        assert c.id == "inbox"

    def test_terminal_dimensions(self) -> None:
        c = CaptureSpec(
            id="test",
            name="X",
            description="Y",
            alt_text="Z",
            importance=3,
            terminal_dimensions={"width": 140, "height": 36},
        )
        assert c.terminal_dimensions == {"width": 140, "height": 36}

    def test_viewport(self) -> None:
        c = CaptureSpec(
            id="test",
            name="X",
            description="Y",
            alt_text="Z",
            importance=3,
            viewport={"width": 1440, "height": 900},
        )
        assert c.viewport == {"width": 1440, "height": 900}


class TestDocSection:
    def test_valid_section(self) -> None:
        s = DocSection(
            screenshot_id="inbox",
            section_header="## Inbox",
            placement="after_header",
            description_text="Shows the inbox view.",
        )
        assert s.placement == "after_header"

    def test_invalid_placement(self) -> None:
        with pytest.raises(ValidationError, match="placement"):
            DocSection(
                screenshot_id="x",
                section_header="## X",
                placement="inline",
                description_text="Y",
            )


class TestAnalysisPlan:
    def _make_plan(self, **overrides: object) -> AnalysisPlan:
        defaults: dict[str, object] = {
            "project_type": "tui",
            "project_name": "My App",
            "project_description": "A test app",
            "tech_stack": ["python", "textual"],
            "features": [],
            "captures": [],
            "demo_data_requirements": [],
            "documentation_sections": [],
        }
        defaults.update(overrides)
        return AnalysisPlan(**defaults)  # type: ignore[arg-type]

    def test_valid_plan(self) -> None:
        plan = self._make_plan()
        assert plan.project_type == "tui"

    def test_invalid_project_type(self) -> None:
        with pytest.raises(ValidationError, match="project_type"):
            self._make_plan(project_type="mobile")

    def test_duplicate_capture_ids(self) -> None:
        cap = CaptureSpec(id="test", name="X", description="Y", alt_text="Z", importance=3)
        with pytest.raises(ValidationError, match="unique"):
            self._make_plan(captures=[cap, cap])

    def test_serialization_roundtrip(self) -> None:
        cap = CaptureSpec(
            id="inbox",
            name="Inbox",
            description="Inbox view",
            alt_text="Inbox",
            importance=4,
            navigation_actions=[{"type": "keystroke", "key": "2"}],
        )
        plan = self._make_plan(captures=[cap])
        data = plan.model_dump()
        restored = AnalysisPlan.model_validate(data)
        assert restored.captures[0].id == "inbox"

    def test_json_schema_generation(self) -> None:
        schema = AnalysisPlan.model_json_schema()
        assert "properties" in schema
        assert "project_type" in schema["properties"]
