"""Git diff analysis — determines which captures need re-analysis.

Uses subprocess to call git (same pattern as orchestrator.py:248-264).
Maps changed files to affected captures based on file patterns.
"""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from phantom.analyst.models import AnalystDiffResult

if TYPE_CHECKING:
    from phantom.analyst.models import CaptureSpec

logger = structlog.get_logger()

# Visual file patterns per project type — changes to these affect screenshots
_VISUAL_PATTERNS: dict[str, list[str]] = {
    "web": [
        "*.tsx",
        "*.jsx",
        "*.css",
        "*.scss",
        "*.sass",
        "*.less",
        "*.html",
        "*.vue",
        "*.svelte",
        "*.astro",
        "templates/**",
        "src/components/**",
        "src/pages/**",
        "src/views/**",
        "src/layouts/**",
        "src/styles/**",
        "public/**",
        "static/**",
        "assets/**",
        "*.svg",
        "*.png",
        "*.jpg",
        "*.gif",
        "*.ico",
        "tailwind.config.*",
        "postcss.config.*",
        "theme.*",
    ],
    "tui": [
        "*.py",
        "*.rs",
        "*.go",
        "*.tcss",
        "src/**",
        "lib/**",
        "assets/**",
        "*.toml",
    ],
    "desktop": [
        "*.c",
        "*.cpp",
        "*.h",
        "*.java",
        "*.swift",
        "*.kt",
        "*.cs",
        "*.fxml",
        "*.qml",
        "*.ui",
        "assets/**",
        "resources/**",
        "src/**",
    ],
    "docker-compose": [
        "*.tsx",
        "*.jsx",
        "*.css",
        "*.html",
        "*.vue",
        "*.svelte",
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
        "Dockerfile*",
        "nginx.conf",
        "templates/**",
        "src/**",
        "public/**",
        "static/**",
    ],
}

# Files that never affect visual output — always safe to skip
_SKIP_PATTERNS: list[str] = [
    "*.md",
    "*.txt",
    "*.rst",
    "*.yml",
    "*.yaml",
    "*.json",
    "*.lock",
    "*.log",
    "*.env",
    "*.env.*",
    "tests/**",
    "test/**",
    ".github/**",
    ".gitignore",
    ".gitattributes",
    "docs/screenshots/**",
    "docs/**/*.md",
    "LICENSE*",
    "CHANGELOG*",
    "CONTRIBUTING*",
    "Makefile",
    "*.cfg",
    "*.ini",
    "setup.py",
    "setup.cfg",
    "mypy.ini",
    "pyproject.toml",
    ".pre-commit-config.yaml",
    ".editorconfig",
    ".flake8",
    "ruff.toml",
    ".ruff.toml",
]

# Global style patterns — changes here affect ALL captures
_GLOBAL_STYLE_PATTERNS: list[str] = [
    "*.css",
    "*.scss",
    "*.sass",
    "*.less",
    "*.tcss",
    "tailwind.config.*",
    "postcss.config.*",
    "theme.*",
    "styles/**",
    "src/styles/**",
]


class DiffAnalyzer:
    """Analyzes git diffs to determine which captures need re-analysis."""

    def __init__(self, project_dir: Path) -> None:
        self._project_dir = project_dir

    def get_head_sha(self) -> str | None:
        """Get the current HEAD commit SHA."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self._project_dir,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None

    def get_changed_files(self, since_sha: str) -> list[str]:
        """Get list of files changed since a given commit."""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", since_sha, "HEAD"],
                cwd=self._project_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return [f for f in result.stdout.strip().splitlines() if f]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.warning("git_diff_failed", since=since_sha)
        return []

    def classify_changes(self, files: list[str], project_type: str = "web") -> dict[str, list[str]]:
        """Classify changed files as visual or non-visual.

        Returns dict with 'visual' and 'non_visual' keys.
        """
        visual: list[str] = []
        non_visual: list[str] = []
        patterns = _VISUAL_PATTERNS.get(project_type, _VISUAL_PATTERNS["web"])

        for f in files:
            if self._matches_any(f, _SKIP_PATTERNS):
                non_visual.append(f)
            elif self._matches_any(f, patterns):
                visual.append(f)
            else:
                # Unknown file — conservatively treat as visual
                visual.append(f)

        return {"visual": visual, "non_visual": non_visual}

    def map_files_to_captures(self, files: list[str], captures: list[CaptureSpec]) -> list[str]:
        """Map changed files to affected capture IDs.

        Uses heuristics: if a file path contains terms from a capture's
        navigation actions or description, that capture is affected.
        Returns list of affected capture IDs.
        """
        affected: set[str] = set()

        for f in files:
            f_lower = f.lower()
            f_parts = set(Path(f).stem.lower().replace("-", " ").replace("_", " ").split())

            for cap in captures:
                # Check if file path relates to capture's navigation
                cap_terms = self._extract_capture_terms(cap)
                if cap_terms & f_parts:
                    affected.add(cap.id)
                    continue

                # Check if file appears in navigation actions
                for action in cap.navigation_actions:
                    for value in action.values():
                        if isinstance(value, str) and f_lower in value.lower():
                            affected.add(cap.id)

        return sorted(affected)

    def analyze(
        self,
        last_sha: str | None,
        captures: list[CaptureSpec],
        project_type: str = "web",
    ) -> AnalystDiffResult:
        """Full diff analysis — returns recommendation and affected captures.

        Logic:
        - No prior state (last_sha is None) → full
        - No changes since last_sha → skip
        - Only non-visual changes → skip
        - Global style change (CSS/theme) → full
        - >75% captures affected → full
        - Some captures affected → incremental
        """
        head_sha = self.get_head_sha()

        if not last_sha or not head_sha:
            return AnalystDiffResult(
                recommendation="full",
                reason="No prior analysis state" if not last_sha else "Cannot determine HEAD",
            )

        if last_sha == head_sha:
            return AnalystDiffResult(
                recommendation="skip",
                reason="No changes since last analysis",
                commit_range=f"{last_sha[:8]}..{head_sha[:8]}",
            )

        changed = self.get_changed_files(last_sha)

        if not changed:
            return AnalystDiffResult(
                recommendation="skip",
                reason="No file changes detected",
                commit_range=f"{last_sha[:8]}..{head_sha[:8]}",
            )

        classified = self.classify_changes(changed, project_type)

        if not classified["visual"]:
            return AnalystDiffResult(
                recommendation="skip",
                changed_files=changed,
                reason="Only non-visual files changed",
                commit_range=f"{last_sha[:8]}..{head_sha[:8]}",
            )

        # Check for global style changes
        if any(self._matches_any(f, _GLOBAL_STYLE_PATTERNS) for f in classified["visual"]):
            return AnalystDiffResult(
                recommendation="full",
                changed_files=changed,
                affected_capture_ids=[c.id for c in captures],
                reason="Global style files changed",
                commit_range=f"{last_sha[:8]}..{head_sha[:8]}",
            )

        # Map visual changes to captures
        affected_ids = self.map_files_to_captures(classified["visual"], captures)

        if not affected_ids:
            # Visual files changed but can't map to specific captures — be conservative
            return AnalystDiffResult(
                recommendation="full",
                changed_files=changed,
                affected_capture_ids=[c.id for c in captures],
                reason="Visual files changed but cannot determine affected captures",
                commit_range=f"{last_sha[:8]}..{head_sha[:8]}",
            )

        # If more than 75% of captures affected, just do full
        if len(affected_ids) > len(captures) * 0.75:
            return AnalystDiffResult(
                recommendation="full",
                changed_files=changed,
                affected_capture_ids=[c.id for c in captures],
                reason=f"{len(affected_ids)}/{len(captures)} captures affected (>75%)",
                commit_range=f"{last_sha[:8]}..{head_sha[:8]}",
            )

        return AnalystDiffResult(
            recommendation="incremental",
            changed_files=changed,
            affected_capture_ids=affected_ids,
            reason=f"{len(affected_ids)}/{len(captures)} captures affected",
            commit_range=f"{last_sha[:8]}..{head_sha[:8]}",
        )

    @staticmethod
    def _matches_any(filepath: str, patterns: list[str]) -> bool:
        """Check if a filepath matches any of the given glob patterns."""
        for pattern in patterns:
            if fnmatch.fnmatch(filepath, pattern):
                return True
            # Also check against just the filename for non-path patterns
            if "/" not in pattern and fnmatch.fnmatch(Path(filepath).name, pattern):
                return True
        return False

    @staticmethod
    def _extract_capture_terms(cap: CaptureSpec) -> set[str]:
        """Extract searchable terms from a capture spec."""
        terms: set[str] = set()

        # From capture ID
        terms.update(cap.id.split("-"))

        # From capture name
        terms.update(cap.name.lower().replace("-", " ").replace("_", " ").split())

        # From navigation actions (route URLs, selectors)
        for action in cap.navigation_actions:
            url = action.get("url")
            if isinstance(url, str):
                # Extract path segments from URL
                for segment in url.strip("/").split("/"):
                    if segment and not segment.startswith("{"):
                        terms.add(segment.lower())

            selector = action.get("selector")
            if isinstance(selector, str):
                # Extract element names from selectors
                for part in selector.replace(".", " ").replace("#", " ").replace(">", " ").split():
                    clean = part.strip().lower()
                    if clean and len(clean) > 2:
                        terms.add(clean)

        # Remove common noise words
        terms -= {"the", "and", "for", "with", "from", "into", "page", "view", "main"}

        return terms
