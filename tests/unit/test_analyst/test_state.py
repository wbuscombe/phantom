"""Tests for analyst state persistence."""

from __future__ import annotations

import json

import pytest

from phantom.analyst.state import AnalystStateData, AnalystStateManager


class TestAnalystStateManager:
    def test_load_no_file(self, tmp_path: object) -> None:
        """Loading with no state file returns empty state."""
        from pathlib import Path

        mgr = AnalystStateManager(Path(str(tmp_path)))
        state = mgr.load()
        assert state.last_analysis_commit is None
        assert state.total_analyses == 0
        assert state.cumulative_cost_usd == 0.0

    def test_has_state_false(self, tmp_path: object) -> None:
        from pathlib import Path

        mgr = AnalystStateManager(Path(str(tmp_path)))
        assert not mgr.has_state()

    def test_save_and_load_roundtrip(self, tmp_path: object) -> None:
        """Save state and load it back."""
        from pathlib import Path

        project_dir = Path(str(tmp_path))
        mgr = AnalystStateManager(project_dir)
        state = mgr.load()
        state.last_analysis_commit = "abc123"
        state.total_analyses = 3
        state.cumulative_cost_usd = 0.1234
        mgr.save()

        assert mgr.has_state()

        mgr2 = AnalystStateManager(project_dir)
        state2 = mgr2.load()
        assert state2.last_analysis_commit == "abc123"
        assert state2.total_analyses == 3
        assert state2.cumulative_cost_usd == pytest.approx(0.1234)

    def test_atomic_write(self, tmp_path: object) -> None:
        """State file should be written atomically."""
        from pathlib import Path

        project_dir = Path(str(tmp_path))
        mgr = AnalystStateManager(project_dir)
        state = mgr.load()
        state.last_analysis_commit = "def456"
        mgr.save()

        # File should exist and be valid JSON
        state_file = project_dir / ".phantom-state.json"
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["last_analysis_commit"] == "def456"

    def test_update_after_analysis(self, tmp_path: object) -> None:
        from pathlib import Path

        mgr = AnalystStateManager(Path(str(tmp_path)))
        mgr.load()
        mgr.update_after_analysis(
            commit_sha="abc123",
            manifest_yaml="phantom: '1'\nproject: test",
            cost_usd=0.05,
            input_tokens=1000,
            output_tokens=500,
            recommendation="full",
        )

        state = mgr.load()
        assert state.last_analysis_commit == "abc123"
        assert state.manifest_hash is not None
        assert state.cumulative_cost_usd == pytest.approx(0.05)
        assert state.cumulative_input_tokens == 1000
        assert state.cumulative_output_tokens == 500
        assert state.total_analyses == 1
        assert state.full_analyses == 1
        assert state.last_recommendation == "full"

    def test_cumulative_cost_accumulates(self, tmp_path: object) -> None:
        from pathlib import Path

        mgr = AnalystStateManager(Path(str(tmp_path)))
        mgr.load()

        mgr.update_after_analysis(cost_usd=0.10, recommendation="full")
        mgr.update_after_analysis(cost_usd=0.05, recommendation="incremental")
        mgr.update_after_analysis(recommendation="skip")

        state = mgr.load()
        assert state.cumulative_cost_usd == pytest.approx(0.15)
        assert state.total_analyses == 3
        assert state.full_analyses == 1
        assert state.incremental_analyses == 1
        assert state.skipped_analyses == 1

    def test_corrupted_file_handling(self, tmp_path: object) -> None:
        """Corrupted JSON should fall back to empty state."""
        from pathlib import Path

        project_dir = Path(str(tmp_path))
        state_file = project_dir / ".phantom-state.json"
        state_file.write_text("not valid json {{{")

        mgr = AnalystStateManager(project_dir)
        state = mgr.load()
        assert state.total_analyses == 0

    def test_get_last_commit(self, tmp_path: object) -> None:
        from pathlib import Path

        mgr = AnalystStateManager(Path(str(tmp_path)))
        assert mgr.get_last_commit() is None

        state = mgr.load()
        state.last_analysis_commit = "abc123"
        mgr.save()

        mgr2 = AnalystStateManager(Path(str(tmp_path)))
        assert mgr2.get_last_commit() == "abc123"


class TestAnalystStateData:
    def test_defaults(self) -> None:
        state = AnalystStateData()
        assert state.last_analysis_commit is None
        assert state.capture_hashes == {}
        assert state.version == 1
