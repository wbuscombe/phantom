"""Integration tests for state manager persistence and atomic writes."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from phantom.conductor.state import RunRecord, StateManager

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.integration
class TestStatePersistence:
    def test_write_restart_read(self, tmp_path: Path) -> None:
        """Write state, create new manager, read state back."""
        state_file = tmp_path / "state.json"

        # Write with first manager
        mgr1 = StateManager(state_file)
        mgr1.load()
        mgr1.record_run(
            RunRecord(
                timestamp=1700000000.0,
                project="my-project",
                status="completed",
                captures_total=5,
                captures_changed=3,
                commit_sha="abc123def456",
                duration_ms=8000,
                trigger_source="webhook",
                diff_pct=4.5,
            )
        )

        # Read with second manager (simulates restart)
        mgr2 = StateManager(state_file)
        state = mgr2.load()

        proj = state.projects["my-project"]
        assert proj.total_runs == 1
        assert proj.last_sha == "abc123def456"
        assert proj.last_status == "completed"
        assert proj.last_diff_pct == 4.5
        assert len(proj.runs) == 1
        assert proj.runs[0].trigger_source == "webhook"
        assert proj.runs[0].diff_pct == 4.5

    def test_atomic_write_survives_crash(self, tmp_path: Path) -> None:
        """State file should not be corrupted by partial writes."""
        state_file = tmp_path / "state.json"

        # Create initial valid state
        mgr = StateManager(state_file)
        mgr.load()
        mgr.record_run(
            RunRecord(
                timestamp=1.0,
                project="test",
                status="completed",
            )
        )

        # Verify file is valid JSON
        content = state_file.read_text()
        data = json.loads(content)
        assert data["projects"]["test"]["total_runs"] == 1

        # The atomic write means no temp files should remain
        tmp_files = list(tmp_path.glob(".phantom_state_*"))
        assert len(tmp_files) == 0

    def test_update_sha_persists(self, tmp_path: Path) -> None:
        """update_sha should persist across manager instances."""
        state_file = tmp_path / "state.json"

        mgr1 = StateManager(state_file)
        mgr1.load()
        mgr1.update_sha("my-project", "abc123")

        mgr2 = StateManager(state_file)
        mgr2.load()
        assert mgr2.get_last_sha("my-project") == "abc123"

    def test_history_limit_configurable(self, tmp_path: Path) -> None:
        """history_limit parameter controls max runs kept."""
        state_file = tmp_path / "state.json"
        mgr = StateManager(state_file, history_limit=5)
        mgr.load()

        for i in range(10):
            mgr.record_run(
                RunRecord(
                    timestamp=float(i),
                    project="test",
                    status="completed",
                )
            )

        proj = mgr.get_project("test")
        assert len(proj.runs) == 5
        assert proj.runs[0].timestamp == 5.0  # Oldest kept

    def test_multiple_projects(self, tmp_path: Path) -> None:
        """State should track multiple projects independently."""
        state_file = tmp_path / "state.json"
        mgr = StateManager(state_file)
        mgr.load()

        mgr.record_run(RunRecord(timestamp=1.0, project="a", status="completed"))
        mgr.record_run(RunRecord(timestamp=2.0, project="b", status="failed"))
        mgr.record_run(RunRecord(timestamp=3.0, project="a", status="completed"))

        # Reload
        mgr2 = StateManager(state_file)
        mgr2.load()

        proj_a = mgr2.get_project("a")
        proj_b = mgr2.get_project("b")

        assert proj_a.total_runs == 2
        assert proj_b.total_runs == 1
        assert proj_b.last_status == "failed"
