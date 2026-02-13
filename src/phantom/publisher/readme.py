"""Sentinel-based README updater.

Scans for HTML comment pairs in README files:
    <!-- phantom:capture-id -->
    ... (replaced content) ...
    <!-- /phantom:capture-id -->

Replaces content between sentinels with <img> tags for retina-aware images.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from pathlib import Path

logger = structlog.get_logger()

# Pattern matches sentinel pairs: <!-- phantom:ID --> ... <!-- /phantom:ID -->
SENTINEL_PATTERN = re.compile(
    r"(<!-- phantom:(?P<id>[a-z0-9][a-z0-9\-]*) -->)"
    r".*?"
    r"(<!-- /phantom:(?P=id) -->)",
    re.DOTALL,
)


@dataclass
class ReadmeUpdate:
    """A single sentinel replacement."""

    capture_id: str
    img_path: str
    alt_text: str
    logical_width: int


@dataclass
class ReadmeResult:
    """Result of updating a README file."""

    path: Path
    updated: bool
    sentinels_found: int
    sentinels_updated: int
    orphaned_sentinels: list[str]


def build_img_tag(img_path: str, alt_text: str, logical_width: int) -> str:
    """Build a retina-aware <img> tag.

    The width attribute displays the image at logical (1x) dimensions,
    while the actual image file is 2x for retina clarity.
    """
    escaped_alt = alt_text.replace('"', "&quot;")
    return f'<img src="{img_path}" width="{logical_width}" alt="{escaped_alt}">'


def find_sentinels(content: str) -> list[str]:
    """Find all phantom sentinel IDs in a string."""
    return [m.group("id") for m in SENTINEL_PATTERN.finditer(content)]


def update_readme_content(
    content: str,
    updates: dict[str, ReadmeUpdate],
) -> tuple[str, int, list[str]]:
    """Replace sentinel regions in README content.

    Args:
        content: The current README content.
        updates: Mapping of capture_id -> ReadmeUpdate.

    Returns:
        Tuple of (new_content, updates_applied, orphaned_ids).
        Orphaned IDs are sentinels found in the README but not in updates.
    """
    found_ids = find_sentinels(content)
    updates_applied = 0
    orphaned: list[str] = []

    for sentinel_id in found_ids:
        if sentinel_id not in updates:
            orphaned.append(sentinel_id)
            continue

    def _replacer(match: re.Match[str]) -> str:
        nonlocal updates_applied
        capture_id = match.group("id")
        if capture_id not in updates:
            return match.group(0)  # Leave unchanged

        update = updates[capture_id]
        tag = build_img_tag(update.img_path, update.alt_text, update.logical_width)
        updates_applied += 1
        return f"<!-- phantom:{capture_id} -->\n{tag}\n<!-- /phantom:{capture_id} -->"

    new_content = SENTINEL_PATTERN.sub(_replacer, content)
    return new_content, updates_applied, orphaned


def update_readme_file(
    readme_path: Path,
    updates: dict[str, ReadmeUpdate],
) -> ReadmeResult:
    """Update sentinel regions in a README file on disk.

    Args:
        readme_path: Path to the README file.
        updates: Mapping of capture_id -> ReadmeUpdate.

    Returns:
        ReadmeResult with stats about what changed.
    """
    if not readme_path.exists():
        logger.warning("readme_not_found", path=str(readme_path))
        return ReadmeResult(
            path=readme_path,
            updated=False,
            sentinels_found=0,
            sentinels_updated=0,
            orphaned_sentinels=[],
        )

    content = readme_path.read_text(encoding="utf-8")
    sentinels_found = len(find_sentinels(content))

    if sentinels_found == 0:
        logger.debug("readme_no_sentinels", path=str(readme_path))
        return ReadmeResult(
            path=readme_path,
            updated=False,
            sentinels_found=0,
            sentinels_updated=0,
            orphaned_sentinels=[],
        )

    new_content, updates_applied, orphaned = update_readme_content(content, updates)
    changed = new_content != content

    if changed:
        readme_path.write_text(new_content, encoding="utf-8")
        logger.info(
            "readme_updated",
            path=str(readme_path),
            sentinels_updated=updates_applied,
            orphaned=len(orphaned),
        )

    return ReadmeResult(
        path=readme_path,
        updated=changed,
        sentinels_found=sentinels_found,
        sentinels_updated=updates_applied,
        orphaned_sentinels=orphaned,
    )
