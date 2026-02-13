"""State persistence — tracks run history per project.

State file lives at ~/.phantom/state.json (or configurable path).
Uses atomic writes (temp file + rename) to prevent corruption on crash.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import structlog

logger = structlog.get_logger()

DEFAULT_STATE_DIR = Path.home() / ".phantom"
DEFAULT_STATE_FILE = DEFAULT_STATE_DIR / "state.json"

DEFAULT_HISTORY_LIMIT = 20


@dataclass
class RunRecord:
    """Record of a single Phantom run."""

    timestamp: float
    project: str
    status: str  # "completed", "failed", "dry_run"
    captures_total: int = 0
    captures_changed: int = 0
    captures_failed: int = 0
    commit_sha: str | None = None
    duration_ms: int = 0
    error: str | None = None
    trigger_source: str | None = None  # "cli", "webhook", "schedule"
    diff_pct: float | None = None  # average diff percentage for the run


@dataclass
class ProjectState:
    """Per-project persistent state."""

    project: str
    last_sha: str | None = None
    last_run: float | None = None
    last_status: str | None = None
    last_diff_pct: float | None = None
    total_runs: int = 0
    runs: list[RunRecord] = field(default_factory=list)


@dataclass
class PhantomState:
    """Root state object persisted to disk."""

    projects: dict[str, ProjectState] = field(default_factory=dict)
    version: int = 1


class StateManager:
    """Manages persistent state for Phantom runs."""

    def __init__(
        self,
        state_file: Path | None = None,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> None:
        self._path = state_file or DEFAULT_STATE_FILE
        self._state: PhantomState | None = None
        self._history_limit = history_limit

    def load(self) -> PhantomState:
        """Load state from disk. Returns empty state if file doesn't exist."""
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._state = self._deserialize(data)
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning("state_load_failed", error=str(e), path=str(self._path))
                self._state = PhantomState()
        else:
            self._state = PhantomState()

        return self._state

    def save(self) -> None:
        """Write state to disk atomically (write to temp, then rename)."""
        if self._state is None:
            return

        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = self._serialize(self._state)
        content = json.dumps(data, indent=2, default=str)

        # Atomic write: write to temp file in same directory, then rename
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self._path.parent),
            prefix=".phantom_state_",
            suffix=".tmp",
        )
        closed = False
        try:
            os.write(fd, content.encode("utf-8"))
            os.fsync(fd)
            os.close(fd)
            closed = True
            os.replace(tmp_path, str(self._path))
            logger.debug("state_saved", path=str(self._path))
        except Exception:
            if not closed:
                os.close(fd)
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

    def get_project(self, project: str) -> ProjectState:
        """Get or create project state."""
        state = self._state or self.load()
        if project not in state.projects:
            state.projects[project] = ProjectState(project=project)
        return state.projects[project]

    def record_run(self, record: RunRecord) -> None:
        """Record a completed run and save."""
        proj = self.get_project(record.project)
        proj.last_run = record.timestamp
        proj.last_status = record.status
        proj.total_runs += 1
        if record.commit_sha:
            proj.last_sha = record.commit_sha
        if record.diff_pct is not None:
            proj.last_diff_pct = record.diff_pct

        # Keep last N runs per project (configurable, default 20)
        proj.runs.append(record)
        if len(proj.runs) > self._history_limit:
            proj.runs = proj.runs[-self._history_limit :]

        self.save()

    def update_sha(self, project: str, sha: str) -> None:
        """Update the last captured SHA for a project."""
        proj = self.get_project(project)
        proj.last_sha = sha
        self.save()

    def get_last_sha(self, project: str) -> str | None:
        """Get the last captured commit SHA for a project."""
        proj = self.get_project(project)
        return proj.last_sha

    @staticmethod
    def _serialize(state: PhantomState) -> dict[str, object]:
        return {
            "version": state.version,
            "projects": {name: asdict(proj) for name, proj in state.projects.items()},
        }

    @staticmethod
    def _deserialize(data: dict[str, object]) -> PhantomState:
        projects: dict[str, ProjectState] = {}
        raw_projects = data.get("projects", {})
        if isinstance(raw_projects, dict):
            for name, proj_data in raw_projects.items():
                if isinstance(proj_data, dict):
                    runs_data = proj_data.pop("runs", [])
                    runs = [RunRecord(**r) for r in runs_data if isinstance(r, dict)]
                    projects[str(name)] = ProjectState(**proj_data, runs=runs)

        version = data.get("version", 1)
        return PhantomState(
            version=int(version) if isinstance(version, (int, float)) else 1,
            projects=projects,
        )

    def get_recent_runs(self, project: str | None = None, limit: int = 10) -> list[RunRecord]:
        """Get recent runs, optionally filtered by project."""
        state = self._state or self.load()
        all_runs: list[RunRecord] = []

        if project:
            proj = state.projects.get(project)
            if proj:
                all_runs = proj.runs
        else:
            for proj in state.projects.values():
                all_runs.extend(proj.runs)

        all_runs.sort(key=lambda r: r.timestamp, reverse=True)
        return all_runs[:limit]

    @staticmethod
    def now() -> float:
        """Current timestamp for records."""
        return time.time()
