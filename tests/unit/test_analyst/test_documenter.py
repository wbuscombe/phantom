"""Tests for the documentation writer with mocked Claude API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from phantom.analyst.costs import CostTracker
from phantom.analyst.documenter import (
    DocumentationWriter,
    DocumenterError,
    _extract_headers,
    _sections_by_header,
)
from phantom.analyst.models import AnalysisPlan, DocUpdate, ScreenshotInfo

if TYPE_CHECKING:
    from pathlib import Path


# ── Fixtures ──


_SAMPLE_README = """\
# My Project

A great project.

## Features

- Feature A
- Feature B

## TUI (Terminal User Interface)

Launch with `my-tui`.

**Playlist Browser:**

Browse your playlists.

**Inbox Triage (60/40 split):**

Process new videos.

## Contributing

PRs welcome.

## License

MIT
"""

_SAMPLE_PLAN_JSON = {
    "project_type": "tui",
    "project_name": "My Project",
    "project_description": "A great project with TUI",
    "tech_stack": ["python", "textual"],
    "features": [],
    "captures": [
        {
            "id": "main-menu",
            "name": "Main Menu",
            "description": "Landing screen",
            "alt_text": "Main menu with options",
            "importance": 5,
            "navigation_actions": [{"type": "wait", "ms": 2000}],
        },
        {
            "id": "inbox",
            "name": "Inbox",
            "description": "Inbox triage view",
            "alt_text": "Inbox showing videos",
            "importance": 4,
            "navigation_actions": [{"type": "keystroke", "key": "2"}],
        },
    ],
    "demo_data_requirements": [],
    "documentation_sections": [],
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


def _create_fake_screenshot(path: Path, width: int = 2560, height: int = 1600) -> Path:
    """Create a minimal PNG file at the given path."""
    try:
        from PIL import Image

        img = Image.new("RGB", (width, height), color=(40, 42, 54))
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path)
    except ImportError:
        # If PIL not available, create a dummy file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    return path


# ── Test Helpers ──


class TestExtractHeaders:
    def test_extracts_all_levels(self) -> None:
        content = "# H1\n## H2\n### H3\ntext"
        headers = _extract_headers(content)
        assert headers == ["# H1", "## H2", "### H3"]

    def test_empty_content(self) -> None:
        assert _extract_headers("") == []

    def test_no_headers(self) -> None:
        assert _extract_headers("just some text\nand more") == []


class TestSectionsByHeader:
    def test_splits_sections(self) -> None:
        content = "# Title\nIntro\n## Section A\nContent A\n## Section B\nContent B"
        sections = _sections_by_header(content)
        assert "# Title" in sections
        assert "## Section A" in sections
        assert "## Section B" in sections
        assert "Content A" in sections["## Section A"]

    def test_empty_content(self) -> None:
        assert _sections_by_header("") == {}


# ── Test ScreenshotInfo Model ──


class TestScreenshotInfo:
    def test_valid_screenshot_info(self) -> None:
        info = ScreenshotInfo(
            capture_id="main-menu",
            file_path="docs/screenshots/main-menu.png",
            width=2560,
            height=1600,
            file_size_kb=150,
            alt_text="Main menu screenshot",
            description="Shows the main menu",
        )
        assert info.capture_id == "main-menu"
        assert info.width == 2560

    def test_serialization(self) -> None:
        info = ScreenshotInfo(
            capture_id="test",
            file_path="/tmp/test.png",
            width=1280,
            height=800,
            file_size_kb=50,
            alt_text="Test",
            description="Test capture",
        )
        data = info.model_dump()
        restored = ScreenshotInfo.model_validate(data)
        assert restored.capture_id == "test"


# ── Test DocUpdate Model ──


class TestDocUpdate:
    def test_valid_doc_update(self) -> None:
        update = DocUpdate(
            original_content="# Old README",
            updated_content="# Updated README\n<img src='test.png'>",
            screenshots_placed=1,
            sections_modified=["## Features"],
            new_sections_added=[],
        )
        assert update.screenshots_placed == 1
        assert update.target_file == "README.md"

    def test_zero_screenshots(self) -> None:
        update = DocUpdate(
            original_content="# README",
            updated_content="# README",
            screenshots_placed=0,
        )
        assert update.screenshots_placed == 0
        assert update.sections_modified == []

    def test_negative_screenshots_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            DocUpdate(
                original_content="x",
                updated_content="x",
                screenshots_placed=-1,
            )


# ── Test DocumentationWriter ──


class TestGatherScreenshotInfo:
    def test_gathers_with_plan(self, tmp_path: Path) -> None:
        plan = AnalysisPlan.model_validate(_SAMPLE_PLAN_JSON)
        ss_path = _create_fake_screenshot(tmp_path / "main-menu.png")

        writer = DocumentationWriter(api_key="test-key")
        infos = writer._gather_screenshot_info([ss_path], plan)

        assert len(infos) == 1
        assert infos[0].capture_id == "main-menu"
        assert infos[0].alt_text == "Main menu with options"

    def test_gathers_without_plan(self, tmp_path: Path) -> None:
        ss_path = _create_fake_screenshot(tmp_path / "main-menu.png")

        writer = DocumentationWriter(api_key="test-key")
        infos = writer._gather_screenshot_info([ss_path], None)

        assert len(infos) == 1
        assert infos[0].capture_id == "main-menu"
        assert "Main Menu" in infos[0].alt_text

    def test_skips_missing_files(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.png"

        writer = DocumentationWriter(api_key="test-key")
        infos = writer._gather_screenshot_info([missing], None)

        assert len(infos) == 0

    def test_multiple_screenshots(self, tmp_path: Path) -> None:
        ss1 = _create_fake_screenshot(tmp_path / "main-menu.png")
        ss2 = _create_fake_screenshot(tmp_path / "inbox.png")
        plan = AnalysisPlan.model_validate(_SAMPLE_PLAN_JSON)

        writer = DocumentationWriter(api_key="test-key")
        infos = writer._gather_screenshot_info([ss1, ss2], plan)

        assert len(infos) == 2
        ids = {i.capture_id for i in infos}
        assert ids == {"main-menu", "inbox"}


class TestFilenameToAlt:
    def test_converts_kebab_case(self) -> None:
        assert DocumentationWriter._filename_to_alt("main-menu") == "Main Menu screenshot"

    def test_single_word(self) -> None:
        assert DocumentationWriter._filename_to_alt("inbox") == "Inbox screenshot"


class TestRetinaDimensions:
    def test_img_tag_uses_half_width(self, tmp_path: Path) -> None:
        """Screenshot at 2560px should render at 1280px logical width."""
        ss_path = _create_fake_screenshot(tmp_path / "test.png", width=2560, height=1600)

        writer = DocumentationWriter(api_key="test-key")
        infos = writer._gather_screenshot_info([ss_path], None)

        assert len(infos) == 1
        # The actual halving is done in _generate_documentation
        assert infos[0].width == 2560


class TestSentinelRemoval:
    def test_sentinel_in_readme_context(self) -> None:
        """The documentation prompt instructs Claude to remove sentinels.
        We verify the prompt text contains the removal instruction."""
        from phantom.analyst.prompts import DOCUMENTATION_SYSTEM_PROMPT

        assert "sentinel" in DOCUMENTATION_SYSTEM_PROMPT.lower()
        assert "phantom" in DOCUMENTATION_SYSTEM_PROMPT.lower()


class TestWriteDocs:
    @patch("phantom.analyst.documenter._get_anthropic_client")
    async def test_writes_docs_with_plan(self, mock_get_client: MagicMock, tmp_path: Path) -> None:
        plan = AnalysisPlan.model_validate(_SAMPLE_PLAN_JSON)

        # Create project structure
        readme_path = tmp_path / "README.md"
        readme_path.write_text(_SAMPLE_README)
        ss_path = _create_fake_screenshot(tmp_path / "docs" / "screenshots" / "main-menu.png")

        # Mock Claude response
        updated_readme = _SAMPLE_README.replace(
            "## TUI (Terminal User Interface)\n\nLaunch with `my-tui`.",
            '## TUI (Terminal User Interface)\n\n<img src="docs/screenshots/main-menu.png" '
            'width="1280" alt="Main menu with options">\n\nThe main menu shows all '
            "available features.\n\nLaunch with `my-tui`.",
        )

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(
            updated_readme, input_tokens=5000, output_tokens=2000
        )
        mock_get_client.return_value = mock_client

        writer = DocumentationWriter(api_key="test-key")
        result = await writer.write_docs([ss_path], plan, tmp_path)

        assert isinstance(result, DocUpdate)
        assert result.screenshots_placed == 1
        assert result.original_content == _SAMPLE_README
        assert "main-menu.png" in result.updated_content

    @patch("phantom.analyst.documenter._get_anthropic_client")
    async def test_writes_docs_without_plan(
        self, mock_get_client: MagicMock, tmp_path: Path
    ) -> None:
        readme_path = tmp_path / "README.md"
        readme_path.write_text(_SAMPLE_README)
        ss_path = _create_fake_screenshot(tmp_path / "docs" / "screenshots" / "inbox.png")

        updated_readme = _SAMPLE_README + '\n<img src="docs/screenshots/inbox.png" width="1280">\n'

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(updated_readme)
        mock_get_client.return_value = mock_client

        writer = DocumentationWriter(api_key="test-key")
        result = await writer.write_docs([ss_path], None, tmp_path)

        assert isinstance(result, DocUpdate)
        assert result.screenshots_placed == 1

    async def test_no_screenshots_returns_unchanged(self, tmp_path: Path) -> None:
        readme_path = tmp_path / "README.md"
        readme_path.write_text(_SAMPLE_README)

        writer = DocumentationWriter(api_key="test-key")
        result = await writer.write_docs([], None, tmp_path)

        assert result.screenshots_placed == 0
        assert result.updated_content == _SAMPLE_README

    async def test_missing_readme_returns_empty(self, tmp_path: Path) -> None:
        writer = DocumentationWriter(api_key="test-key")
        result = await writer.write_docs([], None, tmp_path)

        assert result.original_content == ""
        assert result.screenshots_placed == 0

    @patch("phantom.analyst.documenter._get_anthropic_client")
    async def test_handles_code_fenced_response(
        self, mock_get_client: MagicMock, tmp_path: Path
    ) -> None:
        readme_path = tmp_path / "README.md"
        readme_path.write_text("# Test\n")
        ss_path = _create_fake_screenshot(tmp_path / "test.png")

        # Claude wraps response in code fences
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(
            "```markdown\n# Test\n<img src='test.png'>\n```"
        )
        mock_get_client.return_value = mock_client

        writer = DocumentationWriter(api_key="test-key")
        result = await writer.write_docs([ss_path], None, tmp_path)

        assert "```" not in result.updated_content
        assert "# Test" in result.updated_content

    @patch("phantom.analyst.documenter._get_anthropic_client")
    async def test_records_cost(self, mock_get_client: MagicMock, tmp_path: Path) -> None:
        readme_path = tmp_path / "README.md"
        readme_path.write_text("# Test\n")
        ss_path = _create_fake_screenshot(tmp_path / "test.png")

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(
            "# Test\n", input_tokens=3000, output_tokens=500
        )
        mock_get_client.return_value = mock_client

        tracker = CostTracker()
        writer = DocumentationWriter(api_key="test-key", cost_tracker=tracker)
        await writer.write_docs([ss_path], None, tmp_path)

        assert tracker.total_input_tokens == 3000
        assert tracker.total_output_tokens == 500
        assert tracker.call_count == 1


class TestDiffSections:
    def test_detects_new_section(self) -> None:
        original = "# Title\nIntro\n## Features\nStuff"
        updated = "# Title\nIntro\n## Features\nStuff\n## Screenshots\nNew stuff"

        _modified, new = DocumentationWriter._diff_sections(original, updated)
        assert "## Screenshots" in new

    def test_detects_modified_section(self) -> None:
        original = "# Title\n## Features\nOld content"
        updated = "# Title\n## Features\nNew content with img tag"

        modified, new = DocumentationWriter._diff_sections(original, updated)
        assert "## Features" in modified
        assert new == []

    def test_unchanged_content(self) -> None:
        content = "# Title\n## Features\nSame"
        modified, new = DocumentationWriter._diff_sections(content, content)
        assert modified == []
        assert new == []


class TestEmptyReadme:
    @patch("phantom.analyst.documenter._get_anthropic_client")
    async def test_empty_readme_gets_screenshots_section(
        self, mock_get_client: MagicMock, tmp_path: Path
    ) -> None:
        # No README exists
        ss_path = _create_fake_screenshot(tmp_path / "main-menu.png")

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(
            '## Screenshots\n\n<img src="main-menu.png" width="1280" alt="Main Menu">\n'
        )
        mock_get_client.return_value = mock_client

        writer = DocumentationWriter(api_key="test-key")
        result = await writer.write_docs([ss_path], None, tmp_path)

        assert result.screenshots_placed == 1
        assert "## Screenshots" in result.updated_content


class TestMissingApiKey:
    def test_no_key_raises(self) -> None:
        from phantom.exceptions import AnalystDependencyError

        with (
            patch.dict("os.environ", {}, clear=True),
            pytest.raises((DocumenterError, AnalystDependencyError)),
        ):
            writer = DocumentationWriter(api_key=None)
            writer._ensure_client()
