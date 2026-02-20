"""System and user prompts for the AI Analyst Claude API calls."""

from __future__ import annotations

import json

from phantom.analyst.models import AnalysisPlan

# The full JSON schema for the analysis plan
_SCHEMA_JSON = json.dumps(AnalysisPlan.model_json_schema(), indent=2)

_TUI_GUIDANCE = """\
This is a terminal UI application. Captures use a PTY-based terminal runner.
- Navigation actions use: keystroke (single key), type_text (string with delay), wait (ms), wait_for (selector/text match)
- Terminal dimensions should be 140x36 unless the view needs more/less
- Consider: main view, key workflows, search/filter, detail views, help screen
- The app launches at its main menu/screen — plan navigation from there
- For keystroke actions use format: {"type": "keystroke", "key": "<key>"}
- For type_text actions use format: {"type": "type_text", "text": "<text>", "delay": 80}
- For wait actions use format: {"type": "wait", "ms": <milliseconds>}
- For wait_for actions use format: {"type": "wait_for", "selector": "<text to match>", "timeout": 10}
- Important: after navigation, always include a wait action to let the view render"""

_WEB_GUIDANCE = """\
This is a web application. Captures use a Playwright browser runner.
- Navigation actions use: navigate (route), click (selector), wait_for (selector), type (selector + text), wait (ms)
- Default viewport is 1440x900 for desktop, 390x844 for mobile
- Consider: dashboard, key feature pages, mobile responsive view, settings
- Use CSS selectors for wait_for and click targets
- The app launches at its root URL — plan navigation from there
- For navigate actions use format: {"type": "navigate", "url": "<route>"}
- For click actions use format: {"type": "click", "selector": "<css selector>"}
- For wait actions use format: {"type": "wait", "ms": <milliseconds>}
- For wait_for actions use format: {"type": "wait_for", "selector": "<css selector>", "timeout": 10}"""

_DOCKER_GUIDANCE = """\
This is a Docker Compose application with a web frontend. Captures use a Playwright browser runner.
- Navigation actions are the same as web apps
- The frontend typically runs behind a reverse proxy or on a mapped port
- Consider: the main UI, key features, admin panels if present
- Default viewport is 1440x900"""

_GUIDANCE_MAP = {
    "tui": _TUI_GUIDANCE,
    "web": _WEB_GUIDANCE,
    "docker-compose": _DOCKER_GUIDANCE,
}

ANALYSIS_SYSTEM_PROMPT = """\
You are a documentation analyst for open-source software projects. Your job is to examine a project's source code and determine what screenshots would create the most compelling, useful documentation.

You will receive key source files from the project. Analyze them and respond with a JSON object matching this exact schema:

{schema}

Guidelines:
- Identify 5-8 captures that tell the story of using the app
- Prioritize first impressions: what should a new user see first?
- Ensure visual variety: don't capture 5 views that look the same
- For TUI apps: specify keyboard navigation actions (keystroke, type_text, wait)
- For web apps: specify browser actions (navigate, click, wait_for, type)
- Action types must match Phantom's action schema exactly
- Capture IDs must be kebab-case and unique
- Importance scores: 5 = must-have hero shot, 1 = nice-to-have detail
- For alt_text: be specific and descriptive for accessibility, not generic like "Screenshot"
- Order captures by the narrative flow a new user would follow
- demo_data_needs: describe what data must exist (e.g., "at least 5 playlists with videos")

{guidance}

Respond ONLY with the JSON object. No markdown, no explanation, no code fences."""


DOCUMENTATION_SYSTEM_PROMPT = """\
You are a technical writer for open-source projects. You receive a project's \
README.md and metadata about captured screenshots. Your job is to update the \
README to incorporate screenshots naturally.

Rules:
1. DO NOT rewrite existing content — preserve all existing text exactly
2. Place screenshots in the most relevant existing section
3. Use HTML img tags for retina: <img src="{path}" width="{logical_width}" alt="{alt_text}">
4. Add a 1-2 sentence description after each screenshot
5. If no existing section is appropriate, add a "## Screenshots" section \
before the Contributing/License section
6. Remove any phantom sentinel comments (<!-- phantom:xxx -->) and replace \
with direct img tags
7. Maintain the README's existing voice and formatting style
8. Screenshots should enhance the README, not dominate it

Respond with ONLY the complete updated README content. No explanation, \
no code fences, no preamble."""


def build_system_prompt(project_type: str) -> str:
    """Build the system prompt for the analysis API call."""
    guidance = _GUIDANCE_MAP.get(project_type, _WEB_GUIDANCE)
    return ANALYSIS_SYSTEM_PROMPT.format(schema=_SCHEMA_JSON, guidance=guidance)


INCREMENTAL_SYSTEM_PROMPT = """\
You are a documentation analyst for open-source software projects. You previously \
analyzed this project and generated a capture plan. Some files have changed since \
your last analysis. Your job is to determine which captures need updating and \
return ONLY the captures that need changes.

You will receive:
1. The list of changed files
2. Your previous capture plan (as JSON)
3. Key source files from the project

Respond with a JSON object matching this exact schema:

{schema}

IMPORTANT:
- Return ONLY captures that need updating based on the changed files
- Keep capture IDs the same for existing captures that need updates
- You may add new captures if the changes introduce new features
- Do not include unchanged captures — they will be merged automatically
- If no captures need updating, return an empty captures list
- Maintain the same project_type, project_name, and project_description

{guidance}

Respond ONLY with the JSON object. No markdown, no explanation, no code fences."""


def build_incremental_prompt(
    project_type: str,
    project_dir_name: str,
    changed_files: list[str],
    previous_manifest: str,
    selected_files: list[tuple[str, str]] | None = None,
) -> str:
    """Build a lighter user prompt for incremental analysis.

    Args:
        project_type: Detected project type.
        project_dir_name: Name of the project directory.
        changed_files: List of file paths that changed.
        previous_manifest: The previous manifest YAML content.
        selected_files: Optional list of (path, content) for changed files.
    """
    parts = [
        f"Incremental update for {project_type} project: **{project_dir_name}**\n",
        "## Changed files since last analysis:\n",
    ]

    for f in changed_files:
        parts.append(f"- `{f}`")

    parts.append("\n## Previous capture plan:\n")
    parts.append(f"```yaml\n{previous_manifest}\n```\n")

    if selected_files:
        parts.append("## Key changed source files:\n")
        for path, content in selected_files:
            parts.append(f"### {path}\n```\n{content}\n```\n")

    parts.append(
        "Based on the changed files, determine which captures need updating. "
        "Return ONLY captures that need changes."
    )

    return "\n".join(parts)


def build_incremental_system_prompt(project_type: str) -> str:
    """Build the system prompt for incremental analysis."""
    guidance = _GUIDANCE_MAP.get(project_type, _WEB_GUIDANCE)
    return INCREMENTAL_SYSTEM_PROMPT.format(schema=_SCHEMA_JSON, guidance=guidance)


def build_user_prompt(
    project_type: str,
    project_dir_name: str,
    selected_files: list[tuple[str, str]],
    existing_readme: str | None = None,
) -> str:
    """Build the user message containing project files for analysis.

    Args:
        project_type: Detected project type.
        project_dir_name: Name of the project directory.
        selected_files: List of (path, content) tuples.
        existing_readme: Content of existing README.md, if any.
    """
    parts = [
        f"Analyze this {project_type} project: **{project_dir_name}**\n",
    ]

    if existing_readme:
        parts.append(
            "Here is the existing README.md (the project already has documentation — "
            "your captures should complement it):\n"
        )
        # Truncate README to save tokens
        readme_preview = existing_readme[:3000]
        if len(existing_readme) > 3000:
            readme_preview += "\n[...truncated...]"
        parts.append(f"```markdown\n{readme_preview}\n```\n")

    parts.append("Here are the key source files:\n")

    for path, content in selected_files:
        parts.append(f"### {path}\n```\n{content}\n```\n")

    return "\n".join(parts)
