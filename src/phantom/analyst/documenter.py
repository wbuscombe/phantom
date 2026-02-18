"""Documentation writer — AI-powered README updates with screenshot placement.

Post-capture intelligence: reads captured screenshots and existing README,
then uses Claude to place screenshots naturally in the documentation.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

import structlog

from phantom.analyst.costs import CostTracker
from phantom.analyst.models import DocUpdate, ScreenshotInfo
from phantom.analyst.prompts import DOCUMENTATION_SYSTEM_PROMPT
from phantom.exceptions import PhantomError

if TYPE_CHECKING:
    from pathlib import Path

    from phantom.analyst.models import AnalysisPlan

logger = structlog.get_logger()

_CHARS_PER_TOKEN = 4


class DocumenterError(PhantomError):
    """Raised when documentation generation fails."""

    def __init__(self, message: str, raw_response: str | None = None) -> None:
        self.raw_response = raw_response
        super().__init__(message)


def _get_anthropic_client(api_key: str | None = None) -> Any:
    """Get an Anthropic client, raising a clear error if not installed."""
    try:
        import anthropic
    except ImportError:
        from phantom.analyst.analyzer import AnalystDependencyError

        raise AnalystDependencyError from None

    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise DocumenterError("No API key provided. Set ANTHROPIC_API_KEY environment variable.")
    return anthropic.Anthropic(api_key=key)


class DocumentationWriter:
    """Generates README updates with intelligently placed screenshots."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
        cost_tracker: CostTracker | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.cost_tracker = cost_tracker or CostTracker()
        self._client: Any = None

    def _ensure_client(self) -> Any:
        if self._client is None:
            self._client = _get_anthropic_client(self.api_key)
        return self._client

    async def write_docs(
        self,
        screenshots: list[Path],
        plan: AnalysisPlan | None,
        project_dir: Path,
    ) -> DocUpdate:
        """Generate documentation updates for captured screenshots.

        1. Read existing README.md
        2. Gather screenshot metadata (dimensions, sizes)
        3. Build context from plan (if available) or filenames
        4. Call Claude to produce updated README
        5. Return DocUpdate with modified content
        """
        readme_path = project_dir / "README.md"
        original_content = ""
        if readme_path.exists():
            original_content = readme_path.read_text(encoding="utf-8", errors="replace")

        # Gather screenshot info
        screenshot_infos = self._gather_screenshot_info(screenshots, plan)

        if not screenshot_infos:
            return DocUpdate(
                original_content=original_content,
                updated_content=original_content,
                screenshots_placed=0,
            )

        # Build project context
        project_context = self._build_project_context(plan, project_dir)

        # Generate updated README
        updated_content = await self._generate_documentation(
            readme_content=original_content,
            screenshots=screenshot_infos,
            project_context=project_context,
        )

        # Determine what changed
        sections_modified, new_sections = self._diff_sections(original_content, updated_content)

        return DocUpdate(
            original_content=original_content,
            updated_content=updated_content,
            screenshots_placed=len(screenshot_infos),
            sections_modified=sections_modified,
            new_sections_added=new_sections,
        )

    def _gather_screenshot_info(
        self,
        screenshots: list[Path],
        plan: AnalysisPlan | None,
    ) -> list[ScreenshotInfo]:
        """Build ScreenshotInfo list from screenshot files and optional plan."""
        infos: list[ScreenshotInfo] = []

        # Build lookup from plan captures if available
        plan_lookup: dict[str, dict[str, str]] = {}
        if plan:
            for cap in plan.captures:
                plan_lookup[cap.id] = {
                    "alt_text": cap.alt_text,
                    "description": cap.description,
                }

        for path in screenshots:
            if not path.exists():
                continue

            capture_id = path.stem  # e.g., "main-menu" from "main-menu.png"
            file_size_kb = path.stat().st_size // 1024

            # Get image dimensions
            width, height = self._get_image_dimensions(path)

            # Get alt text and description from plan or generate from filename
            plan_data = plan_lookup.get(capture_id, {})
            alt_text = plan_data.get("alt_text", self._filename_to_alt(capture_id))
            description = plan_data.get("description", self._filename_to_description(capture_id))

            infos.append(
                ScreenshotInfo(
                    capture_id=capture_id,
                    file_path=str(path),
                    width=width,
                    height=height,
                    file_size_kb=file_size_kb,
                    alt_text=alt_text,
                    description=description,
                )
            )

        return infos

    @staticmethod
    def _get_image_dimensions(path: Path) -> tuple[int, int]:
        """Get image width and height. Falls back to defaults on error."""
        try:
            from PIL import Image

            with Image.open(path) as img:
                return img.size
        except Exception:
            return (1280, 800)

    @staticmethod
    def _filename_to_alt(capture_id: str) -> str:
        """Convert a capture ID to basic alt text."""
        return capture_id.replace("-", " ").title() + " screenshot"

    @staticmethod
    def _filename_to_description(capture_id: str) -> str:
        """Convert a capture ID to a basic description."""
        return capture_id.replace("-", " ").replace("_", " ").title()

    @staticmethod
    def _build_project_context(plan: AnalysisPlan | None, project_dir: Path) -> str:
        """Build project context string for the documentation prompt."""
        parts: list[str] = [f"Project directory: {project_dir.name}"]
        if plan:
            parts.append(f"Project name: {plan.project_name}")
            parts.append(f"Project type: {plan.project_type}")
            parts.append(f"Description: {plan.project_description}")
            if plan.tech_stack:
                parts.append(f"Tech stack: {', '.join(plan.tech_stack)}")
        return "\n".join(parts)

    async def _generate_documentation(
        self,
        readme_content: str,
        screenshots: list[ScreenshotInfo],
        project_context: str,
    ) -> str:
        """Single Claude API call to update README with screenshots."""
        client = self._ensure_client()

        # Build screenshot metadata for the prompt
        screenshot_data = []
        for ss in screenshots:
            logical_width = ss.width // 2  # Retina: actual is 2x logical
            screenshot_data.append(
                {
                    "capture_id": ss.capture_id,
                    "file_path": ss.file_path,
                    "width": ss.width,
                    "height": ss.height,
                    "logical_width": logical_width,
                    "file_size_kb": ss.file_size_kb,
                    "alt_text": ss.alt_text,
                    "description": ss.description,
                }
            )

        user_message = (
            f"## Project Context\n{project_context}\n\n"
            f"## Current README.md\n```markdown\n{readme_content}\n```\n\n"
            f"## Screenshots to Place\n```json\n"
            f"{json.dumps(screenshot_data, indent=2)}\n```"
        )

        # Check budget
        input_estimate = (len(DOCUMENTATION_SYSTEM_PROMPT) + len(user_message)) // _CHARS_PER_TOKEN
        output_estimate = max(4096, len(readme_content) // _CHARS_PER_TOKEN + 2000)
        self.cost_tracker.require_budget(input_estimate, output_estimate)

        logger.info(
            "documenter_api_call",
            model=self.model,
            input_estimate=input_estimate,
            screenshots=len(screenshots),
        )

        response = client.messages.create(
            model=self.model,
            max_tokens=output_estimate,
            system=DOCUMENTATION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        self.cost_tracker.record_usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        updated: str = response.content[0].text

        # Strip code fences if Claude wrapped the response
        if updated.startswith("```"):
            first_nl = updated.index("\n")
            updated = updated[first_nl + 1 :]
        if updated.endswith("```"):
            updated = updated[:-3]
        updated = updated.strip() + "\n"

        logger.info(
            "documenter_complete",
            screenshots_placed=len(screenshots),
            cost=self.cost_tracker.summary(),
        )

        return updated

    @staticmethod
    def _diff_sections(original: str, updated: str) -> tuple[list[str], list[str]]:
        """Compare original and updated README to find modified/new sections."""
        original_headers = _extract_headers(original)
        updated_headers = _extract_headers(updated)

        new_sections = [h for h in updated_headers if h not in original_headers]

        # A section is "modified" if it existed before and has different content
        modified = []
        original_section_content = _sections_by_header(original)
        updated_section_content = _sections_by_header(updated)

        for header in original_headers:
            if header in updated_section_content and original_section_content.get(
                header
            ) != updated_section_content.get(header):
                modified.append(header)

        return modified, new_sections


def _extract_headers(content: str) -> list[str]:
    """Extract markdown headers from content."""
    headers: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            headers.append(stripped)
    return headers


def _sections_by_header(content: str) -> dict[str, str]:
    """Split content into sections keyed by header."""
    sections: dict[str, str] = {}
    current_header = ""
    current_lines: list[str] = []

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            if current_header:
                sections[current_header] = "\n".join(current_lines)
            current_header = stripped
            current_lines = []
        else:
            current_lines.append(line)

    if current_header:
        sections[current_header] = "\n".join(current_lines)

    return sections
