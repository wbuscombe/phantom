"""Integration tests for the documentation writer.

Tests the full pipeline with mocked API responses against realistic README content.
All tests use mocked API calls — no real Claude calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

from phantom.analyst.documenter import DocumentationWriter
from phantom.analyst.models import AnalysisPlan, DocUpdate

if TYPE_CHECKING:
    from pathlib import Path


# ── Realistic test data ──

_REALISTIC_README = """\
# Media Library Tool

> CLI and TUI tool for managing a local media library and tracking new items.

## Quick Start

```bash
git clone https://github.com/example/media-library.git
cd media-library
pip install -e .
ml list
```

## Commands

### Library Operations

- List items: `ml list`
- Analyze sources: `ml source "Name" items`

### Search & Duplicates

- Find duplicates: `ml duplicates`
- Search: `ml search "keyword"`

## TUI (Terminal User Interface)

Launch with `ml-tui`.

**Collection Browser:**

Browse and manage your collections.

**Inbox Triage (60/40 split):**

Process new items from tracked sources.

**Add to Collection Dialog:**

Multi-select dialog for sorting items.

**Source Manager:**

Track your sources.

**Search:**

Find items across your whole library.

## Contributing

PRs welcome! See CONTRIBUTING.md.

## License

MIT
"""

_REALISTIC_PLAN_JSON = {
    "project_type": "tui",
    "project_name": "Media Library Tool",
    "project_description": "CLI and TUI for a media library",
    "tech_stack": ["python", "textual", "click"],
    "features": [],
    "captures": [
        {
            "id": "main-menu",
            "name": "Main Menu",
            "description": "Landing screen with navigation",
            "alt_text": "Media Library Tool main menu",
            "importance": 5,
            "navigation_actions": [{"type": "wait", "ms": 2000}],
        },
        {
            "id": "inbox-triage",
            "name": "Inbox Triage",
            "description": "60/40 split for processing items",
            "alt_text": "Inbox triage showing unprocessed items",
            "importance": 5,
            "navigation_actions": [{"type": "keystroke", "key": "2"}],
        },
        {
            "id": "playlist-detail",
            "name": "Collection Detail",
            "description": "Two-panel collection browser",
            "alt_text": "Collection browser with item list",
            "importance": 4,
            "navigation_actions": [{"type": "keystroke", "key": "1"}],
        },
    ],
    "demo_data_requirements": [],
    "documentation_sections": [],
}


def _make_mock_response(text: str, input_tokens: int = 5000, output_tokens: int = 3000) -> Any:
    mock = MagicMock()
    content_block = MagicMock()
    content_block.text = text
    mock.content = [content_block]
    mock.usage = MagicMock()
    mock.usage.input_tokens = input_tokens
    mock.usage.output_tokens = output_tokens
    return mock


def _create_fake_png(path: Path, width: int = 2560, height: int = 1600) -> Path:
    """Create a minimal PNG for testing."""
    try:
        from PIL import Image

        img = Image.new("RGB", (width, height), color=(40, 42, 54))
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path)
    except ImportError:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    return path


# The updated README that the mocked Claude API "returns"
_MOCK_UPDATED_README = """\
# Media Library Tool

> CLI and TUI tool for managing a local media library and tracking new items.

## Quick Start

```bash
git clone https://github.com/example/media-library.git
cd media-library
pip install -e .
ml list
```

## Commands

### Library Operations

- List items: `ml list`
- Analyze sources: `ml source "Name" items`

### Search & Duplicates

- Find duplicates: `ml duplicates`
- Search: `ml search "keyword"`

## TUI (Terminal User Interface)

Launch with `ml-tui`.

<img src="docs/screenshots/main-menu.png" width="1280" alt="Media Library Tool main menu">

The main menu provides quick access to all features including library, inbox, sources, and search.

**Collection Browser:**

<img src="docs/screenshots/playlist-detail.png" width="1280" alt="Collection browser with item list">

Browse and manage your collections.

**Inbox Triage (60/40 split):**

<img src="docs/screenshots/inbox-triage.png" width="1280" alt="Inbox triage showing unprocessed items">

Process new items from tracked sources.

**Add to Collection Dialog:**

Multi-select dialog for sorting items.

**Source Manager:**

Track your sources.

**Search:**

Find items across your whole library.

## Contributing

PRs welcome! See CONTRIBUTING.md.

## License

MIT
"""


class TestFullDocumentationPipeline:
    @patch("phantom.analyst.documenter._get_anthropic_client")
    async def test_writes_docs_for_real_readme(
        self, mock_get_client: MagicMock, tmp_path: Path
    ) -> None:
        """Test the full pipeline against a realistic README."""
        plan = AnalysisPlan.model_validate(_REALISTIC_PLAN_JSON)

        # Create project structure
        readme_path = tmp_path / "README.md"
        readme_path.write_text(_REALISTIC_README)
        ss_dir = tmp_path / "docs" / "screenshots"
        _create_fake_png(ss_dir / "main-menu.png")
        _create_fake_png(ss_dir / "inbox-triage.png")
        _create_fake_png(ss_dir / "playlist-detail.png")

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(_MOCK_UPDATED_README)
        mock_get_client.return_value = mock_client

        writer = DocumentationWriter(api_key="test-key")
        result = await writer.write_docs(
            screenshots=[
                ss_dir / "main-menu.png",
                ss_dir / "inbox-triage.png",
                ss_dir / "playlist-detail.png",
            ],
            plan=plan,
            project_dir=tmp_path,
        )

        assert isinstance(result, DocUpdate)
        assert result.screenshots_placed == 3
        assert result.target_file == "README.md"

    @patch("phantom.analyst.documenter._get_anthropic_client")
    async def test_updated_readme_is_valid_markdown(
        self, mock_get_client: MagicMock, tmp_path: Path
    ) -> None:
        """Verify the updated README is syntactically valid markdown."""
        readme_path = tmp_path / "README.md"
        readme_path.write_text(_REALISTIC_README)
        ss_dir = tmp_path / "docs" / "screenshots"
        _create_fake_png(ss_dir / "main-menu.png")

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(_MOCK_UPDATED_README)
        mock_get_client.return_value = mock_client

        writer = DocumentationWriter(api_key="test-key")
        result = await writer.write_docs(
            [ss_dir / "main-menu.png"],
            AnalysisPlan.model_validate(_REALISTIC_PLAN_JSON),
            tmp_path,
        )

        # Basic markdown validity checks
        assert result.updated_content.startswith("#")
        assert "## " in result.updated_content
        # No orphaned code fences
        fence_count = result.updated_content.count("```")
        assert fence_count % 2 == 0, "Unmatched code fences"

    @patch("phantom.analyst.documenter._get_anthropic_client")
    async def test_screenshots_referenced_with_correct_paths(
        self, mock_get_client: MagicMock, tmp_path: Path
    ) -> None:
        """Verify screenshots use correct relative paths."""
        readme_path = tmp_path / "README.md"
        readme_path.write_text(_REALISTIC_README)
        ss_dir = tmp_path / "docs" / "screenshots"
        _create_fake_png(ss_dir / "main-menu.png")
        _create_fake_png(ss_dir / "inbox-triage.png")

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(_MOCK_UPDATED_README)
        mock_get_client.return_value = mock_client

        writer = DocumentationWriter(api_key="test-key")
        result = await writer.write_docs(
            [ss_dir / "main-menu.png", ss_dir / "inbox-triage.png"],
            AnalysisPlan.model_validate(_REALISTIC_PLAN_JSON),
            tmp_path,
        )

        # Verify img tags reference screenshots
        assert "main-menu.png" in result.updated_content
        assert "inbox-triage.png" in result.updated_content
        # Verify img tags have width attribute (retina)
        assert 'width="1280"' in result.updated_content

    @patch("phantom.analyst.documenter._get_anthropic_client")
    async def test_existing_content_preserved(
        self, mock_get_client: MagicMock, tmp_path: Path
    ) -> None:
        """Verify no existing text content was removed."""
        readme_path = tmp_path / "README.md"
        readme_path.write_text(_REALISTIC_README)
        ss_dir = tmp_path / "docs" / "screenshots"
        _create_fake_png(ss_dir / "main-menu.png")

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(_MOCK_UPDATED_README)
        mock_get_client.return_value = mock_client

        writer = DocumentationWriter(api_key="test-key")
        result = await writer.write_docs(
            [ss_dir / "main-menu.png"],
            AnalysisPlan.model_validate(_REALISTIC_PLAN_JSON),
            tmp_path,
        )

        # All original sections should still be present
        assert "## Quick Start" in result.updated_content
        assert "## Commands" in result.updated_content
        assert "## TUI (Terminal User Interface)" in result.updated_content
        assert "## Contributing" in result.updated_content
        assert "## License" in result.updated_content
        # Key content preserved
        assert "pip install -e ." in result.updated_content
        assert "ml list" in result.updated_content
        assert "PRs welcome" in result.updated_content

    @patch("phantom.analyst.documenter._get_anthropic_client")
    async def test_api_called_with_correct_structure(
        self, mock_get_client: MagicMock, tmp_path: Path
    ) -> None:
        """Verify the API is called with proper system prompt and user message."""
        readme_path = tmp_path / "README.md"
        readme_path.write_text("# Test\n")
        ss_path = _create_fake_png(tmp_path / "test.png")

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response("# Test\n")
        mock_get_client.return_value = mock_client

        writer = DocumentationWriter(api_key="test-key")
        await writer.write_docs([ss_path], None, tmp_path)

        # Verify API was called
        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args[1]

        # System prompt should be the documentation prompt
        assert "technical writer" in call_kwargs["system"].lower()
        # User message should contain README and screenshot data
        user_msg = call_kwargs["messages"][0]["content"]
        assert "README.md" in user_msg
        assert "test.png" in user_msg
