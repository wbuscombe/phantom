"""Intelligent file selection for project analysis.

Selects the most informative files for Claude to analyze while staying
under a token budget (~25K tokens).
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from pathlib import Path

logger = structlog.get_logger()

# Approximate tokens per character
_CHARS_PER_TOKEN = 4
_DEFAULT_TOKEN_BUDGET = 25_000
_MAX_FILE_LINES = 500
_TRUNCATE_HEAD = 200
_TRUNCATE_TAIL = 100

# Directories to always skip
_SKIP_DIRS = frozenset(
    {
        "node_modules",
        ".git",
        "target",
        "dist",
        "build",
        "__pycache__",
        ".next",
        ".nuxt",
        ".svelte-kit",
        "venv",
        ".venv",
        "env",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "coverage",
        ".turbo",
        ".cache",
        "vendor",
    }
)

# File extensions to always skip
_SKIP_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".ico",
        ".webp",
        ".bmp",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".otf",
        ".mp3",
        ".mp4",
        ".avi",
        ".mov",
        ".wmv",
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".7z",
        ".rar",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".pyc",
        ".pyo",
        ".so",
        ".dylib",
        ".dll",
        ".exe",
        ".lock",
        ".sum",
        ".map",
        ".min.js",
        ".min.css",
    }
)

# Files to always skip
_SKIP_FILES = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "Cargo.lock",
        "poetry.lock",
        "Pipfile.lock",
        ".DS_Store",
        "Thumbs.db",
    }
)


@dataclass
class SelectedFile:
    """A file selected for analysis."""

    path: str
    content: str
    token_estimate: int


class FileSelector:
    """Selects the most informative project files for AI analysis."""

    def __init__(self, token_budget: int = _DEFAULT_TOKEN_BUDGET) -> None:
        self.token_budget = token_budget

    async def select_files(self, project_dir: Path, project_type: str) -> list[SelectedFile]:
        """Select files for analysis, staying under the token budget."""
        # Get priority patterns for the project type
        priority_patterns = self._get_priority_patterns(project_type)

        # Collect candidate files
        candidates = self._collect_candidates(project_dir)

        # Score and sort candidates
        scored = [(path, self._score_file(path, priority_patterns)) for path in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)

        # Read files within budget
        selected: list[SelectedFile] = []
        total_tokens = 0

        for path, _score in scored:
            if total_tokens >= self.token_budget:
                break

            content = self._read_file(project_dir / path)
            if content is None:
                continue

            token_est = len(content) // _CHARS_PER_TOKEN
            if total_tokens + token_est > self.token_budget:
                # Try truncating
                remaining = self.token_budget - total_tokens
                max_chars = remaining * _CHARS_PER_TOKEN
                if max_chars < 200:
                    break
                content = self._truncate_content(content, max_chars)
                token_est = len(content) // _CHARS_PER_TOKEN

            selected.append(
                SelectedFile(
                    path=path,
                    content=content,
                    token_estimate=token_est,
                )
            )
            total_tokens += token_est

        logger.info(
            "files_selected",
            count=len(selected),
            total_tokens=total_tokens,
            budget=self.token_budget,
        )
        return selected

    def _get_priority_patterns(self, project_type: str) -> list[list[str]]:
        """Return prioritized file pattern groups for a project type.

        Each group is a list of glob patterns. Groups are in descending
        priority order.
        """
        common_high = ["README.md", "CHANGELOG.md"]

        patterns: dict[str, list[list[str]]] = {
            "web": [
                ["package.json"],
                common_high,
                [
                    "src/pages/**/*",
                    "src/routes/**/*",
                    "src/app/**/page.*",
                    "src/app/**/layout.*",
                    "app/routes/**/*",
                    "pages/**/*",
                ],
                ["src/app.*", "src/main.*", "src/index.*", "app/root.*"],
                ["**/layout*", "**/nav*", "**/sidebar*", "**/header*"],
                ["src/components/index.*"],
            ],
            "tui": [
                ["Cargo.toml", "pyproject.toml"],
                common_high,
                ["src/main.*", "src/app.*", "src/lib.*"],
                ["**/*view*", "**/*screen*", "**/*ui*", "**/*tui*"],
                ["**/*key*", "**/*bind*", "**/*command*", "**/*action*"],
            ],
            "docker-compose": [
                ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"],
                common_high,
                ["package.json"],
                [
                    "frontend/src/**/*",
                    "client/src/**/*",
                    "web/src/**/*",
                    "src/pages/**/*",
                    "src/routes/**/*",
                ],
                ["src/app.*", "src/main.*", "src/index.*"],
            ],
        }

        return patterns.get(project_type, [common_high, ["src/**/*"]])

    def _collect_candidates(self, project_dir: Path) -> list[str]:
        """Walk the project directory and collect candidate file paths."""
        candidates: list[str] = []

        for path in project_dir.rglob("*"):
            if not path.is_file():
                continue

            relative = path.relative_to(project_dir)
            rel_str = str(relative)

            # Skip hidden directories (except well-known config)
            parts = relative.parts
            if any(p.startswith(".") and p not in (".github",) for p in parts[:-1]):
                continue

            # Skip excluded directories
            if any(p in _SKIP_DIRS for p in parts):
                continue

            # Skip by extension
            if path.suffix.lower() in _SKIP_EXTENSIONS:
                continue

            # Skip specific files
            if path.name in _SKIP_FILES:
                continue

            # Skip large files (>100KB)
            try:
                if path.stat().st_size > 100_000:
                    continue
            except OSError:
                continue

            candidates.append(rel_str)

        return candidates

    def _score_file(self, path: str, priority_patterns: list[list[str]]) -> int:
        """Score a file based on priority patterns. Higher = more important."""
        base_score = 0

        # Priority group scoring (higher index in list = lower priority)
        for group_idx, patterns in enumerate(priority_patterns):
            priority = (len(priority_patterns) - group_idx) * 100
            for pattern in patterns:
                if fnmatch.fnmatch(path, pattern):
                    base_score = max(base_score, priority)

        # Bonus for certain file names
        name = path.split("/")[-1].lower()
        if name in ("readme.md", "package.json", "pyproject.toml", "cargo.toml"):
            base_score += 50
        if name.endswith((".tsx", ".jsx", ".svelte", ".vue")):
            base_score += 10
        if "test" in path.lower() or "spec" in path.lower():
            base_score -= 50  # Tests are less informative for feature discovery

        return base_score

    def _read_file(self, path: Path) -> str | None:
        """Read a file, returning None if it can't be read."""
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            return None

        # Truncate long files
        lines = content.splitlines(keepends=True)
        if len(lines) > _MAX_FILE_LINES:
            head = lines[:_TRUNCATE_HEAD]
            tail = lines[-_TRUNCATE_TAIL:]
            skipped = len(lines) - _TRUNCATE_HEAD - _TRUNCATE_TAIL
            content = "".join(head) + f"\n[...truncated {skipped} lines...]\n\n" + "".join(tail)

        return content

    def _truncate_content(self, content: str, max_chars: int) -> str:
        """Truncate content to fit within a character budget."""
        if len(content) <= max_chars:
            return content
        return content[:max_chars] + "\n[...truncated to fit budget...]"
