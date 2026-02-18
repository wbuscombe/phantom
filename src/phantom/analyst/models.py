"""Pydantic models for AI Analyst structured output."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator


class Feature(BaseModel):
    """A documentable feature discovered in the project."""

    name: str = Field(min_length=1, description="Feature name, e.g. 'Inbox Processing'")
    description: str = Field(min_length=1, description="What this feature does")
    ui_type: str = Field(description="screen | modal | panel | page")
    importance: int = Field(ge=1, le=5, description="1-5, higher = more important")
    navigation: str = Field(description="How to reach this feature from app start")

    @field_validator("ui_type")
    @classmethod
    def validate_ui_type(cls, v: str) -> str:
        allowed = {"screen", "modal", "panel", "page", "dialog", "view"}
        if v not in allowed:
            msg = f"ui_type must be one of {sorted(allowed)}, got '{v}'"
            raise ValueError(msg)
        return v


class CaptureSpec(BaseModel):
    """Specification for a single screenshot capture."""

    id: str = Field(min_length=1, description="Kebab-case capture identifier")
    name: str = Field(min_length=1, description="Human-readable name")
    description: str = Field(min_length=1, description="What this capture shows")
    alt_text: str = Field(min_length=1, description="Accessibility text for the image")
    importance: int = Field(ge=1, le=5, description="1-5 priority")
    navigation_actions: list[dict[str, object]] = Field(
        default_factory=list, description="Action sequence to reach this state"
    )
    terminal_dimensions: dict[str, int] | None = Field(
        default=None, description="For TUI: {width, height}"
    )
    viewport: dict[str, int] | None = Field(default=None, description="For web: {width, height}")
    demo_data_needs: list[str] = Field(
        default_factory=list, description="What data must exist for this capture"
    )

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", v):
            msg = f"Capture ID must be kebab-case, got '{v}'"
            raise ValueError(msg)
        return v


class DocSection(BaseModel):
    """Where and how a screenshot should appear in documentation."""

    screenshot_id: str = Field(description="Maps to CaptureSpec.id")
    target_file: str = Field(default="README.md", description="Target doc file")
    section_header: str = Field(description="Section header, e.g. '## Inbox Processing'")
    placement: str = Field(description="after_header | replace_existing | new_section")
    description_text: str = Field(description="Paragraph to accompany the screenshot")

    @field_validator("placement")
    @classmethod
    def validate_placement(cls, v: str) -> str:
        allowed = {"after_header", "replace_existing", "new_section"}
        if v not in allowed:
            msg = f"placement must be one of {sorted(allowed)}, got '{v}'"
            raise ValueError(msg)
        return v


class AnalysisPlan(BaseModel):
    """Complete analysis plan for a project — the structured output from Claude."""

    project_type: str = Field(description="web | tui | docker-compose")
    project_name: str = Field(min_length=1)
    project_description: str = Field(min_length=1)
    tech_stack: list[str] = Field(default_factory=list)
    features: list[Feature] = Field(default_factory=list)
    captures: list[CaptureSpec] = Field(default_factory=list)
    demo_data_requirements: list[str] = Field(default_factory=list)
    documentation_sections: list[DocSection] = Field(default_factory=list)

    @field_validator("project_type")
    @classmethod
    def validate_project_type(cls, v: str) -> str:
        allowed = {"web", "tui", "docker-compose"}
        if v not in allowed:
            msg = f"project_type must be one of {sorted(allowed)}, got '{v}'"
            raise ValueError(msg)
        return v

    @field_validator("captures")
    @classmethod
    def validate_unique_capture_ids(cls, v: list[CaptureSpec]) -> list[CaptureSpec]:
        ids = [cap.id for cap in v]
        if len(ids) != len(set(ids)):
            dupes = [i for i in ids if ids.count(i) > 1]
            msg = f"Capture IDs must be unique, duplicates: {set(dupes)}"
            raise ValueError(msg)
        return v


class ScreenshotInfo(BaseModel):
    """Metadata about a captured screenshot."""

    capture_id: str
    file_path: str
    width: int
    height: int
    file_size_kb: int
    alt_text: str
    description: str


class DocUpdate(BaseModel):
    """Result of documentation generation."""

    target_file: str = Field(default="README.md")
    original_content: str
    updated_content: str
    screenshots_placed: int = Field(ge=0)
    sections_modified: list[str] = Field(default_factory=list)
    new_sections_added: list[str] = Field(default_factory=list)
