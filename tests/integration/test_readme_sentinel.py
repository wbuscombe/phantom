"""Integration tests for README sentinel updates against real files."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from phantom.publisher.readme import ReadmeUpdate, update_readme_file


@pytest.mark.integration
class TestReadmeSentinelIntegration:
    def test_full_readme_update_cycle(self, tmp_path: Path) -> None:
        """Test a complete README update cycle with real file I/O."""
        readme = tmp_path / "README.md"
        readme.write_text("""\
# My Project

Screenshots:

<!-- phantom:dashboard -->
old dashboard image
<!-- /phantom:dashboard -->

Some text in between.

<!-- phantom:settings -->
old settings image
<!-- /phantom:settings -->

Footer text.
""")

        updates = {
            "dashboard": ReadmeUpdate(
                capture_id="dashboard",
                img_path="docs/screenshots/dashboard.png",
                alt_text="Dashboard View",
                logical_width=640,
            ),
            "settings": ReadmeUpdate(
                capture_id="settings",
                img_path="docs/screenshots/settings.png",
                alt_text="Settings Page",
                logical_width=800,
            ),
        }

        result = update_readme_file(readme, updates)
        assert result.updated
        assert result.sentinels_found == 2
        assert result.sentinels_updated == 2
        assert result.orphaned_sentinels == []

        # Verify file content
        content = readme.read_text()
        assert '<img src="docs/screenshots/dashboard.png" width="640"' in content
        assert '<img src="docs/screenshots/settings.png" width="800"' in content
        assert "old dashboard image" not in content
        assert "old settings image" not in content
        assert "Some text in between." in content
        assert "Footer text." in content

    def test_retina_tag_generation(self, tmp_path: Path) -> None:
        """Retina captures should use <img> tags with logical width."""
        readme = tmp_path / "README.md"
        readme.write_text("""\
<!-- phantom:hero -->
<!-- /phantom:hero -->
""")

        updates = {
            "hero": ReadmeUpdate(
                capture_id="hero",
                img_path="docs/hero@2x.png",
                alt_text="Hero Screenshot",
                logical_width=1280,  # Logical 1x width (actual image is 2560px)
            ),
        }

        result = update_readme_file(readme, updates)
        assert result.updated

        content = readme.read_text()
        assert '<img src="docs/hero@2x.png" width="1280" alt="Hero Screenshot">' in content

    def test_missing_sentinel_warning(self, tmp_path: Path) -> None:
        """Captures with readme_target but no matching sentinel should warn."""
        readme = tmp_path / "README.md"
        readme.write_text("# README\nNo sentinels here.\n")

        updates = {
            "dashboard": ReadmeUpdate(
                capture_id="dashboard",
                img_path="img.png",
                alt_text="Dashboard",
                logical_width=640,
            ),
        }

        result = update_readme_file(readme, updates)
        assert not result.updated
        assert result.sentinels_found == 0
