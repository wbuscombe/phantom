"""Unit tests for the README sentinel updater."""

from __future__ import annotations

from phantom.publisher.readme import (
    ReadmeUpdate,
    build_img_tag,
    find_sentinels,
    update_readme_content,
    update_readme_file,
)


class TestBuildImgTag:
    def test_basic_tag(self) -> None:
        tag = build_img_tag("docs/screenshots/dashboard.png", "Dashboard view", 640)
        assert tag == '<img src="docs/screenshots/dashboard.png" width="640" alt="Dashboard view">'

    def test_escapes_quotes_in_alt(self) -> None:
        tag = build_img_tag("img.png", 'A "quoted" value', 800)
        assert "&quot;" in tag
        assert '"quoted"' not in tag.split("alt=")[1]

    def test_retina_width(self) -> None:
        # 2x retina capture displayed at 1x
        tag = build_img_tag("img.png", "Alt", 1280)
        assert 'width="1280"' in tag


class TestFindSentinels:
    def test_finds_single_sentinel(self) -> None:
        content = "# Title\n<!-- phantom:dashboard -->\nold\n<!-- /phantom:dashboard -->\n"
        ids = find_sentinels(content)
        assert ids == ["dashboard"]

    def test_finds_multiple_sentinels(self) -> None:
        content = (
            "<!-- phantom:dashboard -->\nold\n<!-- /phantom:dashboard -->\n"
            "<!-- phantom:settings -->\nold\n<!-- /phantom:settings -->\n"
        )
        ids = find_sentinels(content)
        assert ids == ["dashboard", "settings"]

    def test_no_sentinels(self) -> None:
        content = "# Just a regular README\nNo sentinels here.\n"
        assert find_sentinels(content) == []

    def test_kebab_case_ids(self) -> None:
        content = "<!-- phantom:mobile-admin -->\n<!-- /phantom:mobile-admin -->\n"
        ids = find_sentinels(content)
        assert ids == ["mobile-admin"]

    def test_mismatched_ids_not_found(self) -> None:
        content = "<!-- phantom:foo -->\n<!-- /phantom:bar -->\n"
        ids = find_sentinels(content)
        assert ids == []


class TestUpdateReadmeContent:
    def test_replaces_sentinel_content(self) -> None:
        content = (
            "# My Project\n\n"
            "<!-- phantom:dashboard -->\nold content\n<!-- /phantom:dashboard -->\n\n"
            "End."
        )
        updates = {
            "dashboard": ReadmeUpdate(
                capture_id="dashboard",
                img_path="docs/screenshots/dashboard.png",
                alt_text="Dashboard",
                logical_width=640,
            ),
        }
        new_content, count, orphaned = update_readme_content(content, updates)
        assert count == 1
        assert '<img src="docs/screenshots/dashboard.png"' in new_content
        assert 'width="640"' in new_content
        assert "old content" not in new_content
        assert orphaned == []

    def test_multiple_updates(self) -> None:
        content = (
            "<!-- phantom:a -->\n<!-- /phantom:a -->\n<!-- phantom:b -->\n<!-- /phantom:b -->\n"
        )
        updates = {
            "a": ReadmeUpdate("a", "a.png", "A", 100),
            "b": ReadmeUpdate("b", "b.png", "B", 200),
        }
        new_content, count, orphaned = update_readme_content(content, updates)
        assert count == 2
        assert 'src="a.png"' in new_content
        assert 'src="b.png"' in new_content
        assert orphaned == []

    def test_orphaned_sentinels(self) -> None:
        content = (
            "<!-- phantom:active -->\n<!-- /phantom:active -->\n"
            "<!-- phantom:orphan -->\n<!-- /phantom:orphan -->\n"
        )
        updates = {
            "active": ReadmeUpdate("active", "a.png", "Active", 100),
        }
        _new_content, count, orphaned = update_readme_content(content, updates)
        assert count == 1
        assert orphaned == ["orphan"]

    def test_no_matching_updates(self) -> None:
        content = "<!-- phantom:foo -->\n<!-- /phantom:foo -->\n"
        updates = {"bar": ReadmeUpdate("bar", "b.png", "Bar", 100)}
        new_content, count, orphaned = update_readme_content(content, updates)
        assert count == 0
        assert orphaned == ["foo"]
        # Content should be unchanged
        assert new_content == content

    def test_preserves_surrounding_content(self) -> None:
        content = "Before\n<!-- phantom:x -->\nold\n<!-- /phantom:x -->\nAfter\n"
        updates = {"x": ReadmeUpdate("x", "x.png", "X", 50)}
        new_content, _count, _orphaned = update_readme_content(content, updates)
        assert new_content.startswith("Before\n")
        assert new_content.endswith("After\n")


class TestUpdateReadmeFile:
    def test_updates_file_on_disk(self, tmp_path) -> None:
        readme = tmp_path / "README.md"
        readme.write_text("# Title\n<!-- phantom:cap -->\nold\n<!-- /phantom:cap -->\n")
        updates = {"cap": ReadmeUpdate("cap", "img.png", "Caption", 320)}
        result = update_readme_file(readme, updates)
        assert result.updated
        assert result.sentinels_found == 1
        assert result.sentinels_updated == 1
        assert result.orphaned_sentinels == []

        # Verify file was written
        new_text = readme.read_text()
        assert 'src="img.png"' in new_text

    def test_nonexistent_file(self, tmp_path) -> None:
        result = update_readme_file(tmp_path / "nope.md", {})
        assert not result.updated
        assert result.sentinels_found == 0

    def test_no_sentinels_in_file(self, tmp_path) -> None:
        readme = tmp_path / "README.md"
        readme.write_text("# Just a readme\nNo sentinels.\n")
        result = update_readme_file(readme, {})
        assert not result.updated
        assert result.sentinels_found == 0

    def test_idempotent_update(self, tmp_path) -> None:
        readme = tmp_path / "README.md"
        readme.write_text("<!-- phantom:a -->\n<!-- /phantom:a -->\n")
        updates = {"a": ReadmeUpdate("a", "a.png", "A", 100)}

        result1 = update_readme_file(readme, updates)
        assert result1.updated

        result2 = update_readme_file(readme, updates)
        # Second time, content is the same — no update
        assert not result2.updated
