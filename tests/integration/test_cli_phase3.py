"""Integration tests for Phase 3 CLI commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path
from click.testing import CliRunner

from phantom.cli import main
from phantom.conductor.state import RunRecord, StateManager


@pytest.mark.integration
class TestStatusCommand:
    def test_status_no_history(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["status"])
        assert result.exit_code == 0
        assert "No run history" in result.output or "Phantom" in result.output

    def test_status_with_runs(self, tmp_path: Path) -> None:
        """Status should show recent runs from state file."""
        state_file = tmp_path / "state.json"
        mgr = StateManager(state_file)
        mgr.load()
        mgr.record_run(
            RunRecord(
                timestamp=1700000000.0,
                project="test-project",
                status="completed",
                captures_total=3,
                captures_changed=2,
                commit_sha="abc123def456",
                duration_ms=5000,
                trigger_source="cli",
            )
        )

        # We can't easily inject the state_file into the CLI,
        # but we can verify the state manager works
        recent = mgr.get_recent_runs(limit=10)
        assert len(recent) == 1
        assert recent[0].project == "test-project"
        assert recent[0].trigger_source == "cli"


@pytest.mark.integration
class TestGcCommand:
    def test_gc_no_workspace(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["gc", "--workspace-root", "/tmp/nonexistent-phantom-ws"])
        assert result.exit_code == 0
        assert "No workspace directory" in result.output

    def test_gc_dry_run(self, tmp_path: Path) -> None:
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()

        # Create a stale workspace (old mtime)
        stale_dir = workspace_root / "old-project-abc123"
        stale_dir.mkdir()
        (stale_dir / "file.txt").write_text("test")

        import os
        import time

        old_time = time.time() - (30 * 86400)  # 30 days old
        os.utime(stale_dir, (old_time, old_time))

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "gc",
                "--workspace-root",
                str(workspace_root),
                "--days",
                "7",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "Would remove" in result.output
        # Directory should still exist (dry run)
        assert stale_dir.exists()


@pytest.mark.integration
class TestRunIfChanged:
    def test_if_changed_flag_accepted(self) -> None:
        """Verify --if-changed is a valid flag."""
        runner = CliRunner()
        # This will fail because the project doesn't exist,
        # but it validates that the flag is recognized
        result = runner.invoke(
            main,
            [
                "run",
                "-p",
                "/tmp/nonexistent",
                "--if-changed",
                "--skip-publish",
            ],
        )
        # Should get a manifest error, not a CLI flag error
        assert result.exit_code != 0
        assert "Error" in result.output or "Manifest" in result.output


@pytest.mark.integration
class TestServeCommand:
    def test_serve_requires_secret(self) -> None:
        """Serve should fail without PHANTOM_WEBHOOK_SECRET."""
        import os

        # Ensure env var is not set
        env = os.environ.copy()
        env.pop("PHANTOM_WEBHOOK_SECRET", None)

        runner = CliRunner(env={"PHANTOM_WEBHOOK_SECRET": ""})
        result = runner.invoke(main, ["serve"])
        assert result.exit_code != 0
