"""Integration tests for the publisher — git operations on a real repo."""

from __future__ import annotations

import asyncio
import subprocess
from typing import TYPE_CHECKING

import pytest
from PIL import Image

from phantom.models import CommitAuthor, PublishingConfig
from phantom.publisher.git import (
    find_stale_screenshots,
    publish,
    publish_squash,
    remove_stale_files,
)
from phantom.publisher.readme import ReadmeUpdate, update_readme_file

if TYPE_CHECKING:
    from pathlib import Path


def _init_git_repo(path: Path) -> None:
    """Initialize a git repo with initial commit."""
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    (path / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def _create_fake_pipeline_result(
    capture_id: str,
    output_path: Path,
    changed: bool = True,
):
    """Create a minimal PipelineResult-like object for testing."""
    from dataclasses import dataclass, field

    @dataclass
    class FakeResult:
        capture_id: str
        input_path: Path
        output_path: Path
        changed: bool
        stage_results: dict = field(default_factory=dict)
        error: str | None = None

    return FakeResult(
        capture_id=capture_id,
        input_path=output_path,
        output_path=output_path,
        changed=changed,
    )


class TestPublishIntegration:
    @pytest.mark.integration
    def test_full_publish_workflow(self, tmp_path: Path) -> None:
        """Full publish: create file, add, commit, verify."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        # Create a screenshot file
        screenshots_dir = repo / "docs" / "screenshots"
        screenshots_dir.mkdir(parents=True)
        img = Image.new("RGB", (100, 100), (255, 0, 0))
        img_path = screenshots_dir / "dashboard.png"
        img.save(img_path)

        result = _create_fake_pipeline_result("dashboard", img_path)
        config = PublishingConfig(ci_skip_tag="[skip ci]")

        pub_result = asyncio.get_event_loop().run_until_complete(
            publish(
                repo_dir=repo,
                pipeline_results=[result],
                publishing_config=config,
                project_name="test-project",
            )
        )

        assert pub_result.committed
        assert pub_result.commit_sha is not None
        assert len(pub_result.commit_sha) == 40

        # Verify commit content
        log = subprocess.run(
            ["git", "log", "-1", "--format=%B"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        assert "docs(screenshots)" in log.stdout
        assert "[phantom]" in log.stdout
        assert "[skip ci]" in log.stdout

    @pytest.mark.integration
    def test_publish_custom_author(self, tmp_path: Path) -> None:
        """Commit uses the configured author."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        img_path = repo / "screenshot.png"
        Image.new("RGB", (10, 10)).save(img_path)

        result = _create_fake_pipeline_result("test", img_path)
        config = PublishingConfig(
            commit_author=CommitAuthor(name="Custom Bot", email="custom@bot.io"),
        )

        asyncio.get_event_loop().run_until_complete(publish(repo, [result], config, "test"))

        author = subprocess.run(
            ["git", "log", "-1", "--format=%an <%ae>"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        assert "Custom Bot" in author.stdout
        assert "custom@bot.io" in author.stdout

    @pytest.mark.integration
    def test_publish_dry_run(self, tmp_path: Path) -> None:
        """Dry run should not create a commit."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        img_path = repo / "screenshot.png"
        Image.new("RGB", (10, 10)).save(img_path)

        result = _create_fake_pipeline_result("test", img_path)
        config = PublishingConfig()

        # Get initial commit count
        log_before = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
        )

        pub_result = asyncio.get_event_loop().run_until_complete(
            publish(repo, [result], config, "test", dry_run=True)
        )

        assert not pub_result.committed

        # Commit count should not change
        log_after = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        assert log_before.stdout == log_after.stdout

    @pytest.mark.integration
    def test_publish_no_changes(self, tmp_path: Path) -> None:
        """Publishing with all unchanged results does nothing."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        result = _create_fake_pipeline_result(
            "unchanged",
            repo / "screenshot.png",
            changed=False,
        )
        config = PublishingConfig()

        pub_result = asyncio.get_event_loop().run_until_complete(
            publish(repo, [result], config, "test")
        )
        assert not pub_result.committed

    @pytest.mark.integration
    def test_stale_removal(self, tmp_path: Path) -> None:
        """Stale files are detected and removed."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        screenshots = repo / "docs" / "screenshots"
        screenshots.mkdir(parents=True)
        (screenshots / "active.png").write_text("active")
        (screenshots / "stale.png").write_text("stale")

        stale = asyncio.get_event_loop().run_until_complete(
            find_stale_screenshots(repo, "docs/screenshots", {"docs/screenshots/active.png"})
        )
        assert "docs/screenshots/stale.png" in stale

        removed = asyncio.get_event_loop().run_until_complete(remove_stale_files(repo, stale))
        assert removed == 1
        assert not (screenshots / "stale.png").exists()
        assert (screenshots / "active.png").exists()


class TestReadmePublishIntegration:
    @pytest.mark.integration
    def test_readme_update_and_commit(self, tmp_path: Path) -> None:
        """README updates are committed alongside screenshots."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        # Create README with sentinel
        readme = repo / "README.md"
        readme.write_text(
            "# My App\n\n<!-- phantom:dashboard -->\nplaceholder\n<!-- /phantom:dashboard -->\n"
        )

        # Create screenshot
        screenshots = repo / "docs" / "screenshots"
        screenshots.mkdir(parents=True)
        Image.new("RGB", (1280, 800)).save(screenshots / "dashboard.png")

        # Update README
        updates = {
            "dashboard": ReadmeUpdate(
                capture_id="dashboard",
                img_path="docs/screenshots/dashboard.png",
                alt_text="Dashboard view",
                logical_width=640,
            ),
        }
        result = update_readme_file(readme, updates)
        assert result.updated

        # Verify the tag
        content = readme.read_text()
        assert 'width="640"' in content
        assert 'alt="Dashboard view"' in content

        # Commit both files
        img_result = _create_fake_pipeline_result("dashboard", screenshots / "dashboard.png")
        config = PublishingConfig()

        pub_result = asyncio.get_event_loop().run_until_complete(
            publish(
                repo,
                [img_result],
                config,
                "test",
                readme_updated=True,
            )
        )

        assert pub_result.committed

        # Both files should be in the commit
        diff = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        assert "README.md" in diff.stdout
        assert "docs/screenshots/dashboard.png" in diff.stdout


class TestSquashPublish:
    @pytest.mark.integration
    def test_squash_publish_creates_single_commit(self, tmp_path: Path) -> None:
        """Squash publish should create a single commit on the target branch."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        # Count commits before
        log_before = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=repo, capture_output=True, text=True,
        )
        count_before = int(log_before.stdout.strip())

        # Create screenshot
        screenshots_dir = repo / "docs" / "screenshots"
        screenshots_dir.mkdir(parents=True)
        img = Image.new("RGB", (100, 100), (0, 255, 0))
        img_path = screenshots_dir / "hero.png"
        img.save(img_path)

        result = _create_fake_pipeline_result("hero", img_path)
        config = PublishingConfig(strategy="squash", ci_skip_tag="[skip ci]")

        pub_result = asyncio.get_event_loop().run_until_complete(
            publish_squash(
                repo_dir=repo,
                pipeline_results=[result],
                publishing_config=config,
                project_name="test-project",
            )
        )

        assert pub_result.committed
        assert pub_result.commit_sha is not None

        # Should have exactly 1 new commit (the squash)
        log_after = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=repo, capture_output=True, text=True,
        )
        count_after = int(log_after.stdout.strip())
        assert count_after == count_before + 1

        # Side branch should be cleaned up
        branches = subprocess.run(
            ["git", "branch"], cwd=repo, capture_output=True, text=True,
        )
        assert "phantom/screenshots" not in branches.stdout

        # Commit message should be descriptive
        msg = subprocess.run(
            ["git", "log", "-1", "--format=%B"],
            cwd=repo, capture_output=True, text=True,
        )
        assert "docs(screenshots)" in msg.stdout
        assert "[phantom]" in msg.stdout

        # File should be in the commit
        diff = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
            cwd=repo, capture_output=True, text=True,
        )
        assert "docs/screenshots/hero.png" in diff.stdout

    @pytest.mark.integration
    def test_squash_publish_no_changes(self, tmp_path: Path) -> None:
        """Squash publish with no changes should do nothing."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        result = _create_fake_pipeline_result(
            "unchanged", repo / "screenshot.png", changed=False,
        )
        config = PublishingConfig(strategy="squash")

        pub_result = asyncio.get_event_loop().run_until_complete(
            publish_squash(repo, [result], config, "test")
        )
        assert not pub_result.committed

    @pytest.mark.integration
    def test_squash_via_publish_strategy(self, tmp_path: Path) -> None:
        """publish() dispatches to squash when strategy='squash'."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        screenshots_dir = repo / "docs" / "screenshots"
        screenshots_dir.mkdir(parents=True)
        img_path = screenshots_dir / "test.png"
        Image.new("RGB", (50, 50)).save(img_path)

        result = _create_fake_pipeline_result("test", img_path)
        config = PublishingConfig(strategy="squash")

        pub_result = asyncio.get_event_loop().run_until_complete(
            publish(repo, [result], config, "test")
        )
        assert pub_result.committed

        # Verify no side branch remains
        branches = subprocess.run(
            ["git", "branch"], cwd=repo, capture_output=True, text=True,
        )
        assert "phantom/screenshots" not in branches.stdout
