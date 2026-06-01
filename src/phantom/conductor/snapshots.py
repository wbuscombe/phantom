"""Snapshot management for the manual ``phantom snapshots`` / ``phantom rollback`` CLI.

``phantom snapshots`` records the current commit hash and screenshot file hashes;
``phantom rollback`` restores those files from the recorded commit.

NOTE: this is a MANUAL tool, not an automatic safety net. The orchestrator does
not create snapshots or roll back during a ``phantom run``, and a failing quality
check does not trigger a rollback — the publish quality gate prevents bad frames
from being committed in the first place (see ``Orchestrator._publish``). Rollback
is also forward-only: it restores files via ``git checkout`` into a *new* commit
and therefore CANNOT remove a frame already pushed to a remote — that blob persists
in history and may already have been cloned or cached.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

import structlog

from phantom.utils.process import run_command

if TYPE_CHECKING:
    from pathlib import Path

logger = structlog.get_logger()

_STATE_FILE = ".phantom-state.json"
_MAX_SNAPSHOTS = 10


@dataclass
class Snapshot:
    """A point-in-time record of screenshot state."""

    id: str
    timestamp: float
    commit_sha: str | None = None
    file_hashes: dict[str, str] = field(default_factory=dict)
    capture_count: int = 0


@dataclass
class SnapshotList:
    """Container for snapshots stored in state file."""

    snapshots: list[Snapshot] = field(default_factory=list)


class SnapshotManager:
    """Manages snapshots for rollback capability."""

    def __init__(self, project_dir: Path) -> None:
        self._project_dir = project_dir
        self._state_path = project_dir / _STATE_FILE

    async def snapshot(self) -> str:
        """Record the current commit hash and screenshot hashes.

        Returns:
            Snapshot ID.
        """
        # Get current commit SHA
        result = await run_command(
            "git",
            "rev-parse",
            "HEAD",
            cwd=self._project_dir,
            timeout=5,
        )
        commit_sha = result.stdout.strip() if result.returncode == 0 else None

        # Hash all screenshot files
        screenshots_dir = self._project_dir / "docs" / "screenshots"
        file_hashes: dict[str, str] = {}
        if screenshots_dir.is_dir():
            for f in sorted(screenshots_dir.iterdir()):
                if f.is_file() and f.suffix in (".png", ".webp"):
                    file_hashes[str(f.relative_to(self._project_dir))] = _file_hash(f)

        snap = Snapshot(
            id=uuid.uuid4().hex[:8],
            timestamp=time.time(),
            commit_sha=commit_sha,
            file_hashes=file_hashes,
            capture_count=len(file_hashes),
        )

        # Save to state
        snapshots = self._load_snapshots()
        snapshots.append(snap)
        # Trim to max
        if len(snapshots) > _MAX_SNAPSHOTS:
            snapshots = snapshots[-_MAX_SNAPSHOTS:]
        self._save_snapshots(snapshots)

        logger.info(
            "snapshot_created",
            snapshot_id=snap.id,
            commit=commit_sha[:8] if commit_sha else None,
            files=len(file_hashes),
        )
        return snap.id

    async def rollback(self, snapshot_id: str | None = None) -> bool:
        """Restore screenshots from a snapshot.

        Args:
            snapshot_id: Specific snapshot to restore.  If ``None``, uses the
                most recent snapshot.

        Returns:
            ``True`` if rollback succeeded.
        """
        snapshots = self._load_snapshots()
        if not snapshots:
            logger.warning("rollback_no_snapshots")
            return False

        if snapshot_id:
            snap = next((s for s in snapshots if s.id == snapshot_id), None)
            if snap is None:
                logger.warning("rollback_snapshot_not_found", snapshot_id=snapshot_id)
                return False
        else:
            snap = snapshots[-1]

        if not snap.commit_sha:
            logger.warning("rollback_no_commit", snapshot_id=snap.id)
            return False

        # Restore screenshots from the snapshot commit
        files_to_restore = list(snap.file_hashes.keys())
        if not files_to_restore:
            logger.info("rollback_no_files", snapshot_id=snap.id)
            return True

        # git checkout <commit> -- <files>
        result = await run_command(
            "git",
            "checkout",
            snap.commit_sha,
            "--",
            *files_to_restore,
            cwd=self._project_dir,
            timeout=30,
        )

        if result.returncode != 0:
            logger.error(
                "rollback_failed",
                snapshot_id=snap.id,
                error=result.stderr[:500],
            )
            return False

        # Also restore README if it was tracked
        readme_result = await run_command(
            "git",
            "checkout",
            snap.commit_sha,
            "--",
            "README.md",
            cwd=self._project_dir,
            timeout=10,
        )
        if readme_result.returncode != 0:
            logger.debug("rollback_readme_skip", reason="README not in snapshot commit")

        logger.info(
            "rollback_complete",
            snapshot_id=snap.id,
            commit=snap.commit_sha[:8],
            files_restored=len(files_to_restore),
        )
        return True

    def list_snapshots(self) -> list[Snapshot]:
        """Return all recorded snapshots, oldest first."""
        return self._load_snapshots()

    def _load_snapshots(self) -> list[Snapshot]:
        """Load snapshots from the state file."""
        if not self._state_path.exists():
            return []

        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

        raw_snaps = data.get("snapshots", [])
        snapshots = []
        for raw in raw_snaps:
            try:
                snapshots.append(Snapshot(**raw))
            except (TypeError, KeyError):
                continue
        return snapshots

    def _save_snapshots(self, snapshots: list[Snapshot]) -> None:
        """Save snapshots to the state file (preserving other keys)."""
        data: dict[str, object] = {}
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}

        data["snapshots"] = [asdict(s) for s in snapshots]

        # Atomic write
        tmp_path = self._state_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(str(tmp_path), str(self._state_path))


def _file_hash(path: Path) -> str:
    """SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:16]
