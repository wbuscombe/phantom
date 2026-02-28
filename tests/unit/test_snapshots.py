"""Unit tests for the snapshot/rollback manager."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from phantom.conductor.snapshots import Snapshot, SnapshotManager, _file_hash


class TestFileHash:
    def test_hash_consistency(self, tmp_path: Path) -> None:
        """Same file should always produce the same hash."""
        f = tmp_path / "test.png"
        f.write_bytes(b"\x89PNG" + b"\x00" * 100)
        h1 = _file_hash(f)
        h2 = _file_hash(f)
        assert h1 == h2

    def test_different_files_different_hash(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.png"
        f2 = tmp_path / "b.png"
        f1.write_bytes(b"\x89PNG" + b"\x00" * 100)
        f2.write_bytes(b"\x89PNG" + b"\xff" * 100)
        assert _file_hash(f1) != _file_hash(f2)

    def test_hash_length(self, tmp_path: Path) -> None:
        f = tmp_path / "test.png"
        f.write_bytes(b"\x89PNG")
        h = _file_hash(f)
        assert len(h) == 16  # Truncated SHA-256


class TestSnapshotManager:
    @pytest.fixture
    def mgr(self, tmp_path: Path) -> SnapshotManager:
        return SnapshotManager(tmp_path)

    @pytest.mark.asyncio
    async def test_snapshot_creates_record(self, mgr: SnapshotManager, tmp_path: Path) -> None:
        # Create some screenshots
        ss_dir = tmp_path / "docs" / "screenshots"
        ss_dir.mkdir(parents=True)
        (ss_dir / "main.png").write_bytes(b"\x89PNG" + b"\x00" * 100)
        (ss_dir / "settings.png").write_bytes(b"\x89PNG" + b"\xff" * 100)

        with patch("phantom.conductor.snapshots.run_command") as mock_cmd:
            mock_cmd.return_value = MagicMock(returncode=0, stdout="abc123def456\n")
            snap_id = await mgr.snapshot()

        assert isinstance(snap_id, str)
        assert len(snap_id) == 8

        # Verify state file was created
        state_path = tmp_path / ".phantom-state.json"
        assert state_path.exists()
        data = json.loads(state_path.read_text())
        assert len(data["snapshots"]) == 1
        assert data["snapshots"][0]["id"] == snap_id
        assert data["snapshots"][0]["capture_count"] == 2

    @pytest.mark.asyncio
    async def test_multiple_snapshots(self, mgr: SnapshotManager, tmp_path: Path) -> None:
        ss_dir = tmp_path / "docs" / "screenshots"
        ss_dir.mkdir(parents=True)
        (ss_dir / "main.png").write_bytes(b"\x89PNG" + b"\x00" * 100)

        with patch("phantom.conductor.snapshots.run_command") as mock_cmd:
            mock_cmd.return_value = MagicMock(returncode=0, stdout="abc123\n")
            id1 = await mgr.snapshot()
            id2 = await mgr.snapshot()

        assert id1 != id2
        snaps = mgr.list_snapshots()
        assert len(snaps) == 2

    def test_list_snapshots_empty(self, mgr: SnapshotManager) -> None:
        assert mgr.list_snapshots() == []

    @pytest.mark.asyncio
    async def test_rollback_latest(self, mgr: SnapshotManager, tmp_path: Path) -> None:
        # Create a snapshot record manually
        state_path = tmp_path / ".phantom-state.json"
        state_path.write_text(
            json.dumps(
                {
                    "snapshots": [
                        {
                            "id": "snap1",
                            "timestamp": 1000.0,
                            "commit_sha": "abc123",
                            "file_hashes": {"docs/screenshots/main.png": "deadbeef"},
                            "capture_count": 1,
                        }
                    ]
                }
            )
        )

        with patch("phantom.conductor.snapshots.run_command") as mock_cmd:
            mock_cmd.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = await mgr.rollback()

        assert result is True
        # Should have called git checkout with the commit SHA
        calls = mock_cmd.call_args_list
        checkout_call = calls[0]
        assert "checkout" in checkout_call.args
        assert "abc123" in checkout_call.args

    @pytest.mark.asyncio
    async def test_rollback_specific_id(self, mgr: SnapshotManager, tmp_path: Path) -> None:
        state_path = tmp_path / ".phantom-state.json"
        state_path.write_text(
            json.dumps(
                {
                    "snapshots": [
                        {
                            "id": "snap1",
                            "timestamp": 1000.0,
                            "commit_sha": "aaa111",
                            "file_hashes": {"docs/screenshots/old.png": "hash1"},
                            "capture_count": 1,
                        },
                        {
                            "id": "snap2",
                            "timestamp": 2000.0,
                            "commit_sha": "bbb222",
                            "file_hashes": {"docs/screenshots/new.png": "hash2"},
                            "capture_count": 1,
                        },
                    ]
                }
            )
        )

        with patch("phantom.conductor.snapshots.run_command") as mock_cmd:
            mock_cmd.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = await mgr.rollback("snap1")

        assert result is True
        # Should checkout snap1's commit
        assert "aaa111" in mock_cmd.call_args_list[0].args

    @pytest.mark.asyncio
    async def test_rollback_no_snapshots(self, mgr: SnapshotManager) -> None:
        result = await mgr.rollback()
        assert result is False

    @pytest.mark.asyncio
    async def test_rollback_unknown_id(self, mgr: SnapshotManager, tmp_path: Path) -> None:
        state_path = tmp_path / ".phantom-state.json"
        state_path.write_text(
            json.dumps(
                {
                    "snapshots": [
                        {
                            "id": "snap1",
                            "timestamp": 1000.0,
                            "commit_sha": "abc",
                            "file_hashes": {},
                            "capture_count": 0,
                        }
                    ]
                }
            )
        )

        result = await mgr.rollback("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_snapshot_max_limit(self, mgr: SnapshotManager, tmp_path: Path) -> None:
        """Snapshots should be capped at _MAX_SNAPSHOTS."""
        ss_dir = tmp_path / "docs" / "screenshots"
        ss_dir.mkdir(parents=True)
        (ss_dir / "test.png").write_bytes(b"\x89PNG" + b"\x00" * 100)

        with patch("phantom.conductor.snapshots.run_command") as mock_cmd:
            mock_cmd.return_value = MagicMock(returncode=0, stdout="abc\n")
            for _ in range(15):  # More than _MAX_SNAPSHOTS (10)
                await mgr.snapshot()

        snaps = mgr.list_snapshots()
        assert len(snaps) == 10  # Capped

    def test_preserves_other_state_keys(self, tmp_path: Path) -> None:
        """Saving snapshots should not clobber other keys in state file."""
        state_path = tmp_path / ".phantom-state.json"
        state_path.write_text(
            json.dumps(
                {
                    "last_analysis_commit": "abc",
                    "other_key": "value",
                }
            )
        )

        mgr = SnapshotManager(tmp_path)
        mgr._save_snapshots([Snapshot(id="s1", timestamp=1.0)])

        data = json.loads(state_path.read_text())
        assert data["last_analysis_commit"] == "abc"
        assert data["other_key"] == "value"
        assert len(data["snapshots"]) == 1
