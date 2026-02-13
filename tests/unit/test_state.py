"""Unit tests for the state manager."""

from __future__ import annotations

from typing import TYPE_CHECKING

from phantom.conductor.state import PhantomState, RunRecord, StateManager

if TYPE_CHECKING:
    from pathlib import Path


class TestStateManager:
    def test_load_empty(self, tmp_path: Path) -> None:
        mgr = StateManager(tmp_path / "state.json")
        state = mgr.load()
        assert isinstance(state, PhantomState)
        assert state.projects == {}

    def test_save_and_load(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        mgr = StateManager(state_file)
        mgr.load()

        # Record a run
        record = RunRecord(
            timestamp=1700000000.0,
            project="test-project",
            status="completed",
            captures_total=3,
            captures_changed=2,
            captures_failed=0,
            commit_sha="abc123def456",
            duration_ms=5000,
        )
        mgr.record_run(record)

        # Verify file exists
        assert state_file.exists()

        # Load in a new manager
        mgr2 = StateManager(state_file)
        state2 = mgr2.load()
        assert "test-project" in state2.projects
        proj = state2.projects["test-project"]
        assert proj.total_runs == 1
        assert proj.last_sha == "abc123def456"
        assert proj.last_status == "completed"
        assert len(proj.runs) == 1
        assert proj.runs[0].captures_total == 3

    def test_multiple_runs(self, tmp_path: Path) -> None:
        mgr = StateManager(tmp_path / "state.json")
        mgr.load()

        for i in range(3):
            mgr.record_run(
                RunRecord(
                    timestamp=1700000000.0 + i,
                    project="my-project",
                    status="completed",
                    captures_total=1,
                    captures_changed=1,
                )
            )

        proj = mgr.get_project("my-project")
        assert proj.total_runs == 3
        assert len(proj.runs) == 3

    def test_run_history_limit(self, tmp_path: Path) -> None:
        mgr = StateManager(tmp_path / "state.json", history_limit=20)
        mgr.load()

        # Record 25 runs — only the last 20 should be kept
        for i in range(25):
            mgr.record_run(
                RunRecord(
                    timestamp=1700000000.0 + i,
                    project="big-project",
                    status="completed",
                )
            )

        proj = mgr.get_project("big-project")
        assert proj.total_runs == 25
        assert len(proj.runs) == 20
        # First run should be the 6th one (index 5)
        assert proj.runs[0].timestamp == 1700000005.0

    def test_get_recent_runs_all_projects(self, tmp_path: Path) -> None:
        mgr = StateManager(tmp_path / "state.json")
        mgr.load()

        mgr.record_run(
            RunRecord(
                timestamp=1700000001.0,
                project="a",
                status="completed",
            )
        )
        mgr.record_run(
            RunRecord(
                timestamp=1700000002.0,
                project="b",
                status="failed",
            )
        )
        mgr.record_run(
            RunRecord(
                timestamp=1700000003.0,
                project="a",
                status="completed",
            )
        )

        recent = mgr.get_recent_runs(limit=10)
        assert len(recent) == 3
        # Should be sorted by timestamp descending
        assert recent[0].timestamp == 1700000003.0
        assert recent[1].timestamp == 1700000002.0
        assert recent[2].timestamp == 1700000001.0

    def test_get_recent_runs_filtered(self, tmp_path: Path) -> None:
        mgr = StateManager(tmp_path / "state.json")
        mgr.load()

        mgr.record_run(RunRecord(timestamp=1.0, project="a", status="completed"))
        mgr.record_run(RunRecord(timestamp=2.0, project="b", status="completed"))

        recent = mgr.get_recent_runs(project="a", limit=10)
        assert len(recent) == 1
        assert recent[0].project == "a"

    def test_corrupt_state_file(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        state_file.write_text("not valid json {{{")

        mgr = StateManager(state_file)
        state = mgr.load()
        # Should fall back to empty state
        assert state.projects == {}

    def test_get_project_creates_if_missing(self, tmp_path: Path) -> None:
        mgr = StateManager(tmp_path / "state.json")
        mgr.load()

        proj = mgr.get_project("new-project")
        assert proj.project == "new-project"
        assert proj.total_runs == 0
