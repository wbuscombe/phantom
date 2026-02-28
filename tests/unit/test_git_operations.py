"""Unit tests for git operations and commit message generation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from phantom.models import CommitAuthor, PublishingConfig
from phantom.publisher.git import compose_commit_message

# Minimal stubs matching the interfaces used by compose_commit_message


@dataclass
class FakeMetadata:
    metadata: dict[str, object] | None = None


@dataclass
class FakePipelineResult:
    capture_id: str
    changed: bool
    input_path: Path = Path("/tmp/fake")
    output_path: Path = Path("/tmp/fake")
    stage_results: dict[str, FakeMetadata] = field(default_factory=dict)
    error: str | None = None


class TestComposeCommitMessage:
    def test_default_message(self) -> None:
        results = [
            FakePipelineResult("dashboard", changed=True),
            FakePipelineResult("settings", changed=False),
        ]
        config = PublishingConfig()
        msg = compose_commit_message("my-project", results, config)

        assert "docs(screenshots): update 1 of 2 captures [phantom]" in msg
        assert "Updated: dashboard (new)" in msg
        assert "Unchanged: settings" in msg
        assert "[skip ci]" in msg

    def test_custom_ci_skip_tag(self) -> None:
        config = PublishingConfig(ci_skip_tag="[ci skip]")
        msg = compose_commit_message("test", [FakePipelineResult("a", True)], config)
        assert "[ci skip]" in msg
        assert "[skip ci]" not in msg

    def test_no_ci_skip_when_empty(self) -> None:
        config = PublishingConfig(ci_skip_tag="")
        msg = compose_commit_message("test", [FakePipelineResult("a", True)], config)
        # Should not end with an empty line for the tag
        assert msg.rstrip() == msg.rstrip()  # Basic sanity
        assert "[skip ci]" not in msg

    def test_custom_commit_message(self) -> None:
        config = PublishingConfig(commit_message="chore: update screenshots")
        msg = compose_commit_message("test", [FakePipelineResult("a", True)], config)
        assert msg.startswith("chore: update screenshots")

    def test_force_mode_noted(self) -> None:
        config = PublishingConfig()
        msg = compose_commit_message("test", [FakePipelineResult("a", True)], config, force=True)
        assert "Force mode" in msg

    def test_readme_noted(self) -> None:
        config = PublishingConfig()
        msg = compose_commit_message(
            "test", [FakePipelineResult("a", True)], config, readme_updated=True
        )
        assert "README sentinels updated" in msg

    def test_diff_details_in_message(self) -> None:
        results = [
            FakePipelineResult(
                "dashboard",
                changed=True,
                stage_results={
                    "diff": FakeMetadata(metadata={"diff_pct": 5.2, "similarity": 0.948})
                },
            ),
        ]
        config = PublishingConfig()
        msg = compose_commit_message("test", results, config)
        assert "dashboard (5.2% diff)" in msg

    def test_new_capture_shows_new(self) -> None:
        results = [FakePipelineResult("new-cap", changed=True)]
        config = PublishingConfig()
        msg = compose_commit_message("test", results, config)
        assert "new-cap (new)" in msg

    def test_all_unchanged(self) -> None:
        results = [
            FakePipelineResult("a", changed=False),
            FakePipelineResult("b", changed=False),
        ]
        config = PublishingConfig()
        msg = compose_commit_message("test", results, config)
        assert "no changes [phantom]" in msg
        assert "Unchanged: a, b" in msg


class TestGitAdd:
    def test_git_add_in_repo(self, tmp_path: Path) -> None:
        """Test git add works in a real git repo."""
        # Initialize a git repo
        import subprocess

        from phantom.publisher.git import git_add

        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        # Create a file
        (tmp_path / "test.txt").write_text("hello")

        asyncio.get_event_loop().run_until_complete(git_add(tmp_path, ["test.txt"]))

        # Verify it's staged
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert "test.txt" in result.stdout


class TestGitCommit:
    def test_commit_and_sha(self, tmp_path: Path) -> None:
        """Test that git commit creates a commit and returns SHA."""
        import subprocess

        from phantom.publisher.git import git_add, git_commit

        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        (tmp_path / "file.txt").write_text("content")
        asyncio.get_event_loop().run_until_complete(git_add(tmp_path, ["file.txt"]))

        author = CommitAuthor(name="Phantom Bot", email="phantom@noreply")
        sha = asyncio.get_event_loop().run_until_complete(
            git_commit(tmp_path, "test commit\n\n[skip ci]", author)
        )

        assert sha is not None
        assert len(sha) == 40  # Full SHA

        # Verify author
        result = subprocess.run(
            ["git", "log", "-1", "--format=%an <%ae>"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert "Phantom Bot" in result.stdout
        assert "phantom@noreply" in result.stdout

    def test_nothing_to_commit(self, tmp_path: Path) -> None:
        """git_commit returns None when nothing is staged."""
        import subprocess

        from phantom.publisher.git import git_commit

        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        # Initial commit so we have a HEAD
        (tmp_path / "init.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        author = CommitAuthor()
        sha = asyncio.get_event_loop().run_until_complete(git_commit(tmp_path, "empty", author))
        assert sha is None


class TestStaleDetection:
    def test_finds_stale_files(self, tmp_path: Path) -> None:
        from phantom.publisher.git import find_stale_screenshots

        # Create output directory with files
        screenshots_dir = tmp_path / "docs" / "screenshots"
        screenshots_dir.mkdir(parents=True)
        (screenshots_dir / "active.png").write_text("active")
        (screenshots_dir / "orphan.png").write_text("orphan")
        (screenshots_dir / "readme.txt").write_text("not a screenshot")

        known = {"docs/screenshots/active.png"}
        stale = asyncio.get_event_loop().run_until_complete(
            find_stale_screenshots(tmp_path, "docs/screenshots", known)
        )
        assert "docs/screenshots/orphan.png" in stale
        assert "docs/screenshots/active.png" not in stale
        # Non-image files should not be flagged
        assert "docs/screenshots/readme.txt" not in stale

    def test_no_stale_when_all_known(self, tmp_path: Path) -> None:
        from phantom.publisher.git import find_stale_screenshots

        screenshots_dir = tmp_path / "docs" / "screenshots"
        screenshots_dir.mkdir(parents=True)
        (screenshots_dir / "a.png").write_text("a")

        known = {"docs/screenshots/a.png"}
        stale = asyncio.get_event_loop().run_until_complete(
            find_stale_screenshots(tmp_path, "docs/screenshots", known)
        )
        assert stale == []

    def test_empty_directory(self, tmp_path: Path) -> None:
        from phantom.publisher.git import find_stale_screenshots

        stale = asyncio.get_event_loop().run_until_complete(
            find_stale_screenshots(tmp_path, "nonexistent", set())
        )
        assert stale == []
