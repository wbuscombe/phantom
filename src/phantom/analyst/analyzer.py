"""Project analyzer — the core AI analysis engine.

Reads a project's codebase and generates a complete .phantom.yml manifest.
"""

from __future__ import annotations

import contextlib
import json
import os
from typing import TYPE_CHECKING, Any

import structlog
from ruamel.yaml import YAML

from phantom.analyst.costs import CostTracker
from phantom.analyst.diff import DiffAnalyzer
from phantom.analyst.file_selector import FileSelector
from phantom.analyst.models import AnalysisPlan, AnalystDiffResult, CaptureSpec
from phantom.analyst.prompts import (
    build_incremental_prompt,
    build_incremental_system_prompt,
    build_system_prompt,
    build_user_prompt,
)
from phantom.analyst.state import AnalystStateManager
from phantom.exceptions import AnalystDependencyError as AnalystDependencyError  # re-export
from phantom.exceptions import PhantomError

if TYPE_CHECKING:
    from pathlib import Path

logger = structlog.get_logger()

# Approximate chars per token for budget estimation
_CHARS_PER_TOKEN = 4


class AnalystError(PhantomError):
    """Raised when the analyst fails to produce a valid plan."""

    def __init__(self, message: str, raw_response: str | None = None) -> None:
        self.raw_response = raw_response
        super().__init__(message)


def _get_anthropic_client(api_key: str | None = None) -> Any:
    """Get an Anthropic client, raising a clear error if not installed."""
    try:
        import anthropic
    except ImportError:
        raise AnalystDependencyError from None

    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise AnalystError(
            "No API key provided. Set ANTHROPIC_API_KEY environment variable "
            "or pass api_key to ProjectAnalyzer."
        )
    return anthropic.Anthropic(api_key=key)


class ProjectAnalyzer:
    """Analyzes a project and generates a Phantom manifest."""

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

    async def detect_project_type(self, project_dir: Path) -> str:
        """Detect project type from file signatures. No API call needed."""
        # Docker-compose takes precedence
        for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
            if (project_dir / name).exists():
                return "docker-compose"

        # Web projects
        if (project_dir / "package.json").exists():
            return "web"

        # TUI projects
        if (project_dir / "Cargo.toml").exists():
            # Check it's not a Tauri project (which is web)
            cargo_text = (project_dir / "Cargo.toml").read_text(errors="replace")
            if "tauri" not in cargo_text.lower():
                return "tui"
            return "web"

        if (project_dir / "pyproject.toml").exists():
            pyproject = (project_dir / "pyproject.toml").read_text(errors="replace")
            tui_indicators = ["textual", "curses", "rich", "blessed", "prompt_toolkit"]
            if any(ind in pyproject.lower() for ind in tui_indicators):
                return "tui"

        if (project_dir / "go.mod").exists():
            return "tui"

        return "web"  # Default fallback

    async def analyze(self, project_dir: Path) -> AnalysisPlan:
        """Full analysis pipeline — returns a structured plan."""
        client = self._ensure_client()

        # 1. Detect project type
        project_type = await self.detect_project_type(project_dir)
        logger.info("project_type_detected", project_type=project_type)

        # 2. Select files
        selector = FileSelector()
        selected = await selector.select_files(project_dir, project_type)
        logger.info("files_selected", count=len(selected))

        # 3. Read existing README for context
        readme_path = project_dir / "README.md"
        existing_readme = None
        if readme_path.exists():
            with contextlib.suppress(OSError):
                existing_readme = readme_path.read_text(encoding="utf-8", errors="replace")

        # 4. Build prompts
        system_prompt = build_system_prompt(project_type)
        user_prompt = build_user_prompt(
            project_type=project_type,
            project_dir_name=project_dir.name,
            selected_files=[(f.path, f.content) for f in selected],
            existing_readme=existing_readme,
        )

        # 5. Estimate tokens and check budget
        input_estimate = (len(system_prompt) + len(user_prompt)) // _CHARS_PER_TOKEN
        output_estimate = 4096  # max_tokens we'll request
        self.cost_tracker.require_budget(input_estimate, output_estimate)

        # 6. Call Claude API
        logger.info("analyst_api_call", model=self.model, input_estimate=input_estimate)

        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        # Record actual usage
        self.cost_tracker.record_usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        # 7. Parse response
        raw_text = response.content[0].text
        plan = self._parse_response(raw_text)

        if plan is None:
            # Retry once with correction prompt
            logger.warning("analyst_parse_failed_retrying")
            self.cost_tracker.require_budget(input_estimate // 2, output_estimate)

            retry_response = client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt},
                    {"role": "assistant", "content": raw_text},
                    {
                        "role": "user",
                        "content": (
                            "Your response was not valid JSON matching the required schema. "
                            "Please try again. Respond ONLY with a valid JSON object — "
                            "no markdown, no code fences, no explanation."
                        ),
                    },
                ],
            )
            self.cost_tracker.record_usage(
                input_tokens=retry_response.usage.input_tokens,
                output_tokens=retry_response.usage.output_tokens,
            )

            retry_text = retry_response.content[0].text
            plan = self._parse_response(retry_text)

            if plan is None:
                raise AnalystError(
                    "Failed to parse Claude response as valid AnalysisPlan after retry",
                    raw_response=retry_text,
                )

        logger.info(
            "analysis_complete",
            features=len(plan.features),
            captures=len(plan.captures),
            cost=self.cost_tracker.summary(),
        )
        return plan

    def _parse_response(self, text: str) -> AnalysisPlan | None:
        """Try to parse a Claude response as an AnalysisPlan."""
        # Strip markdown code fences if present
        cleaned = text.strip()
        if cleaned.startswith("```"):
            # Remove opening fence (possibly with language tag)
            first_newline = cleaned.index("\n")
            cleaned = cleaned[first_newline + 1 :]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("analyst_json_parse_error", text_preview=cleaned[:200])
            return None

        try:
            return AnalysisPlan.model_validate(data)
        except Exception as e:
            logger.warning("analyst_validation_error", error=str(e))
            return None

    async def generate_manifest(self, plan: AnalysisPlan, project_dir: Path) -> str:
        """Convert an AnalysisPlan to a valid .phantom.yml string.

        This is deterministic — no API call needed.
        """
        yaml = YAML()
        yaml.default_flow_style = False
        yaml.width = 120

        # Determine display name: prefer README H1, then convert plan name
        display_name = self._extract_display_name(plan.project_name, project_dir)
        project_slug = display_name.lower().replace(" ", "-")

        # Build the manifest structure
        manifest: dict[str, Any] = {
            "phantom": "1",
            "project": project_slug,
            "name": display_name,
        }

        # Setup section
        setup = self._build_setup(plan, project_dir)
        manifest["setup"] = setup

        # TUI-specific terminal config
        if plan.project_type == "tui":
            manifest["tui"] = {
                "terminal": {"width": 140, "height": 36},
                "renderer": "silicon",
                "renderer_config": {
                    "font": "JetBrains Mono",
                    "font_size": 14,
                    "theme": "Dracula",
                    "padding": 20,
                    "background": "#282a36",
                    "window_controls": True,
                    "corner_radius": 8,
                },
            }

        # Capture defaults
        manifest["capture_defaults"] = {
            "theme": "dark",
            "device_scale": 2,
            "timeout": 15,
            "retry": {"max_attempts": 2, "backoff_ms": 1000},
        }
        if plan.project_type == "tui":
            manifest["capture_defaults"]["wait_after_actions"] = 500

        # Captures — sorted by importance (highest first)
        sorted_captures = sorted(plan.captures, key=lambda c: c.importance, reverse=True)
        captures_list = []
        for cap in sorted_captures:
            entry: dict[str, Any] = {
                "id": cap.id,
                "name": cap.name,
                "output": f"docs/screenshots/{cap.id}.png",
                "alt_text": cap.alt_text,
                "readme_target": cap.id,
            }
            if cap.navigation_actions:
                entry["actions"] = cap.navigation_actions
            captures_list.append(entry)

        manifest["captures"] = captures_list

        # Processing
        manifest["processing"] = {
            "format": "png",
            "optimize": True,
            "border": {"style": "drop-shadow"},
        }

        # Publishing
        manifest["publishing"] = {
            "branch": "main",
            "strategy": "direct",
            "readme_update": True,
        }

        # Serialize to YAML string
        import io

        stream = io.StringIO()
        yaml.dump(manifest, stream)
        return stream.getvalue()

    def _build_setup(self, plan: AnalysisPlan, project_dir: Path) -> dict[str, Any]:
        """Build the setup section based on project type and tech stack."""
        setup: dict[str, Any] = {"type": plan.project_type}

        if plan.project_type == "tui":
            # Detect Python or Rust
            if (project_dir / "pyproject.toml").exists():
                setup["requires"] = ["python3"]
                setup["build"] = [
                    "python3 -m venv venv || true",
                    "venv/bin/pip install -e .",
                ]
                # Try to find the entry point
                entry = self._detect_python_entry(project_dir, plan.project_type)
                setup["run"] = {
                    "command": entry or "venv/bin/python -m src.app",
                    "env": {"PHANTOM_MODE": "1"},
                    "ready_check": {"type": "delay", "seconds": 5},
                }
            elif (project_dir / "Cargo.toml").exists():
                setup["requires"] = ["cargo"]
                setup["build"] = ["cargo build --release"]
                setup["run"] = {
                    "command": f"./target/release/{project_dir.name}",
                    "env": {"PHANTOM_MODE": "1"},
                    "ready_check": {"type": "screen_stable", "timeout": 10},
                }
        elif plan.project_type == "web":
            setup["requires"] = ["node"]
            setup["build"] = ["npm ci"]
            setup["run"] = {
                "command": "npm run dev",
                "env": {"PHANTOM_MODE": "1"},
                "ready_check": {"type": "http", "url": "http://localhost:3000", "timeout": 30},
            }
        elif plan.project_type == "docker-compose":
            setup["type"] = "docker-compose"
            setup["compose_file"] = "docker-compose.yml"

        return setup

    @staticmethod
    def _extract_display_name(plan_name: str, project_dir: Path) -> str:
        """Extract a display name for the project.

        Priority:
        1. README H1 heading (first `# Title` line)
        2. Convert kebab-case/snake_case plan name to Title Case
        3. Use plan name as-is if it looks like a proper name already
        """
        # Try README H1
        readme_path = project_dir / "README.md"
        if readme_path.exists():
            with contextlib.suppress(OSError):
                for line in readme_path.read_text(encoding="utf-8", errors="replace").splitlines():
                    stripped = line.strip()
                    if stripped.startswith("# ") and not stripped.startswith("## "):
                        title = stripped[2:].strip()
                        if title:
                            return title

        # Convert kebab-case or snake_case to Title Case
        if "-" in plan_name or "_" in plan_name:
            return plan_name.replace("-", " ").replace("_", " ").title()

        return plan_name

    def _detect_python_entry(self, project_dir: Path, project_type: str = "tui") -> str | None:
        """Try to detect the Python entry point from pyproject.toml.

        For TUI projects, prefers scripts with tui/ui/gui/app/dashboard in their
        name or target module. Falls back to first entry otherwise.
        """
        pyproject = project_dir / "pyproject.toml"
        if not pyproject.exists():
            return None

        try:
            content = pyproject.read_text(encoding="utf-8")
        except OSError:
            return None

        # Parse all [project.scripts] entries
        scripts: list[tuple[str, str]] = []  # (name, target)
        in_scripts = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped == "[project.scripts]":
                in_scripts = True
                continue
            if in_scripts:
                if stripped.startswith("["):
                    break
                if "=" in stripped:
                    name, target = stripped.split("=", 1)
                    scripts.append((name.strip(), target.strip().strip('"').strip("'")))

        if not scripts:
            return None

        # For TUI projects, prefer entries with TUI-related keywords
        if project_type == "tui":
            tui_keywords = {"tui", "ui", "gui", "app", "dashboard"}

            # First pass: check script name for TUI keywords
            for name, _target in scripts:
                name_lower = name.lower().replace("-", " ").replace("_", " ")
                if any(kw in name_lower.split() for kw in tui_keywords):
                    return f"venv/bin/{name}"

            # Second pass: check target module/function for TUI keywords
            for name, target in scripts:
                target_lower = target.lower()
                if any(kw in target_lower for kw in tui_keywords):
                    return f"venv/bin/{name}"

        # Fall back to first entry
        return f"venv/bin/{scripts[0][0]}"

    async def analyze_incremental(
        self,
        project_dir: Path,
        force_full: bool = False,
    ) -> tuple[AnalysisPlan, AnalystDiffResult]:
        """Incremental analysis — only re-analyzes affected captures.

        1. Load AnalystState, run DiffAnalyzer
        2. skip → re-parse previous manifest from state, return
        3. incremental → call Claude with lighter prompt, merge with previous
        4. full → delegate to existing analyze()
        5. Save updated state

        Returns:
            Tuple of (plan, diff_result) where diff_result shows what was done.
        """
        state_mgr = AnalystStateManager(project_dir)
        state = state_mgr.load()

        project_type = await self.detect_project_type(project_dir)

        # Run diff analysis
        diff_analyzer = DiffAnalyzer(project_dir)
        head_sha = diff_analyzer.get_head_sha()

        if force_full or not state.last_analysis_commit:
            diff_result = AnalystDiffResult(
                recommendation="full",
                reason="Forced full analysis" if force_full else "No prior analysis state",
            )
        else:
            # Build capture list from previous manifest to inform diff analysis
            previous_captures = []
            if state.last_manifest_yaml:
                try:
                    prev_plan = self._parse_manifest_to_plan(state.last_manifest_yaml)
                    if prev_plan:
                        previous_captures = prev_plan.captures
                except Exception:
                    pass

            diff_result = diff_analyzer.analyze(
                last_sha=state.last_analysis_commit,
                captures=previous_captures,
                project_type=project_type,
            )

        logger.info(
            "incremental_analysis_recommendation",
            recommendation=diff_result.recommendation,
            reason=diff_result.reason,
            changed_files=len(diff_result.changed_files),
            affected_captures=len(diff_result.affected_capture_ids),
        )

        # Handle skip
        if diff_result.recommendation == "skip":
            if state.last_manifest_yaml:
                plan = self._parse_manifest_to_plan(state.last_manifest_yaml)
                if plan:
                    state_mgr.update_after_analysis(
                        commit_sha=head_sha,
                        recommendation="skip",
                    )
                    return plan, diff_result

            # Can't skip without a previous manifest — fall through to full
            diff_result = AnalystDiffResult(
                recommendation="full",
                changed_files=diff_result.changed_files,
                reason="No previous manifest available, falling back to full",
            )

        # Handle full analysis
        if diff_result.recommendation == "full":
            plan = await self.analyze(project_dir)
            manifest_yaml = await self.generate_manifest(plan, project_dir)

            state_mgr.update_after_analysis(
                commit_sha=head_sha,
                manifest_yaml=manifest_yaml,
                cost_usd=self.cost_tracker.estimated_cost_usd,
                input_tokens=self.cost_tracker.total_input_tokens,
                output_tokens=self.cost_tracker.total_output_tokens,
                recommendation="full",
            )
            return plan, diff_result

        # Handle incremental analysis
        assert diff_result.recommendation == "incremental"
        assert state.last_manifest_yaml is not None

        previous_plan = self._parse_manifest_to_plan(state.last_manifest_yaml)
        if not previous_plan:
            # Can't do incremental without a valid previous plan
            plan = await self.analyze(project_dir)
            manifest_yaml = await self.generate_manifest(plan, project_dir)
            state_mgr.update_after_analysis(
                commit_sha=head_sha,
                manifest_yaml=manifest_yaml,
                cost_usd=self.cost_tracker.estimated_cost_usd,
                input_tokens=self.cost_tracker.total_input_tokens,
                output_tokens=self.cost_tracker.total_output_tokens,
                recommendation="full",
            )
            diff_result.recommendation = "full"
            diff_result.reason = "Previous manifest invalid, fell back to full"
            return plan, diff_result

        client = self._ensure_client()

        # Build incremental prompt
        system_prompt = build_incremental_system_prompt(project_type)
        user_prompt = build_incremental_prompt(
            project_type=project_type,
            project_dir_name=project_dir.name,
            changed_files=diff_result.changed_files,
            previous_manifest=state.last_manifest_yaml,
        )

        input_estimate = (len(system_prompt) + len(user_prompt)) // _CHARS_PER_TOKEN
        output_estimate = 2048  # Smaller output for incremental
        self.cost_tracker.require_budget(input_estimate, output_estimate)

        logger.info(
            "incremental_api_call",
            model=self.model,
            input_estimate=input_estimate,
            affected_captures=diff_result.affected_capture_ids,
        )

        response = client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        self.cost_tracker.record_usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        raw_text = response.content[0].text
        incremental_plan = self._parse_response(raw_text)

        if incremental_plan is None:
            # Incremental parse failed — fall back to full
            logger.warning("incremental_parse_failed_falling_back_to_full")
            plan = await self.analyze(project_dir)
            manifest_yaml = await self.generate_manifest(plan, project_dir)
            state_mgr.update_after_analysis(
                commit_sha=head_sha,
                manifest_yaml=manifest_yaml,
                cost_usd=self.cost_tracker.estimated_cost_usd,
                input_tokens=self.cost_tracker.total_input_tokens,
                output_tokens=self.cost_tracker.total_output_tokens,
                recommendation="full",
            )
            diff_result.recommendation = "full"
            diff_result.reason = "Incremental parse failed, fell back to full"
            return plan, diff_result

        # Merge incremental results with previous plan
        plan = self._merge_plans(previous_plan, incremental_plan)
        manifest_yaml = await self.generate_manifest(plan, project_dir)

        state_mgr.update_after_analysis(
            commit_sha=head_sha,
            manifest_yaml=manifest_yaml,
            cost_usd=self.cost_tracker.estimated_cost_usd,
            input_tokens=self.cost_tracker.total_input_tokens,
            output_tokens=self.cost_tracker.total_output_tokens,
            recommendation="incremental",
        )

        logger.info(
            "incremental_analysis_complete",
            total_captures=len(plan.captures),
            updated_captures=len(incremental_plan.captures),
        )

        return plan, diff_result

    def _parse_manifest_to_plan(self, manifest_yaml: str) -> AnalysisPlan | None:
        """Parse a manifest YAML back into an AnalysisPlan.

        This is a best-effort reverse mapping — we extract what we can.
        """
        yaml = YAML()
        try:
            data = yaml.load(manifest_yaml)
        except Exception:
            return None

        if not isinstance(data, dict):
            return None

        captures = []
        for cap_data in data.get("captures", []):
            if not isinstance(cap_data, dict):
                continue
            try:
                captures.append(
                    CaptureSpec(
                        id=cap_data.get("id", "unknown"),
                        name=cap_data.get("name", "Unknown"),
                        description=cap_data.get("alt_text", ""),
                        alt_text=cap_data.get("alt_text", ""),
                        importance=3,
                        navigation_actions=cap_data.get("actions", []),
                    )
                )
            except Exception:
                continue

        setup = data.get("setup")
        project_type = setup.get("type", "web") if isinstance(setup, dict) else "web"
        if project_type not in {"web", "tui", "docker-compose"}:
            project_type = "web"

        name = str(data.get("name") or data.get("project") or "unknown")

        try:
            return AnalysisPlan(
                project_type=str(project_type),
                project_name=name,
                project_description=f"Project {name}",
                captures=captures,
            )
        except Exception:
            return None

    @staticmethod
    def _merge_plans(previous: AnalysisPlan, incremental: AnalysisPlan) -> AnalysisPlan:
        """Merge incremental analysis results with the previous plan.

        Replace matching capture IDs, append new ones, keep others unchanged.
        """
        updated_ids = {c.id for c in incremental.captures}
        merged_captures = []

        # Keep all previous captures that weren't updated
        for cap in previous.captures:
            if cap.id not in updated_ids:
                merged_captures.append(cap)

        # Add all updated/new captures
        merged_captures.extend(incremental.captures)

        return AnalysisPlan(
            project_type=previous.project_type,
            project_name=incremental.project_name or previous.project_name,
            project_description=incremental.project_description or previous.project_description,
            tech_stack=incremental.tech_stack or previous.tech_stack,
            features=incremental.features or previous.features,
            captures=merged_captures,
            demo_data_requirements=(
                incremental.demo_data_requirements or previous.demo_data_requirements
            ),
            documentation_sections=(
                incremental.documentation_sections or previous.documentation_sections
            ),
        )

    async def generate_seed_requirements(self, plan: AnalysisPlan) -> str:
        """Generate a markdown description of what demo data is needed."""
        lines = [
            f"# Demo Data Requirements for {plan.project_name}",
            "",
            "The following data must be available when running in PHANTOM_MODE "
            "for screenshot captures to produce meaningful output.",
            "",
        ]

        if plan.demo_data_requirements:
            lines.append("## General Requirements")
            lines.append("")
            for req in plan.demo_data_requirements:
                lines.append(f"- {req}")
            lines.append("")

        lines.append("## Per-Capture Requirements")
        lines.append("")
        for cap in plan.captures:
            if cap.demo_data_needs:
                lines.append(f"### {cap.name} (`{cap.id}`)")
                for need in cap.demo_data_needs:
                    lines.append(f"- {need}")
                lines.append("")

        return "\n".join(lines)
