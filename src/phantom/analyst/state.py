"""Per-project analyst state persistence.

State file lives at `.phantom-state.json` in the project directory.
Uses atomic writes (temp file + rename) to prevent corruption on crash.
Same pattern as conductor/state.py.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from pathlib import Path

from phantom.exceptions import AnalystStateError

logger = structlog.get_logger()

STATE_FILENAME = ".phantom-state.json"


@dataclass
class AnalystStateData:
    """Per-project analyst state."""

    last_analysis_commit: str | None = None
    manifest_hash: str | None = None
    capture_hashes: dict[str, str] = field(default_factory=dict)
    cumulative_cost_usd: float = 0.0
    cumulative_input_tokens: int = 0
    cumulative_output_tokens: int = 0
    total_analyses: int = 0
    full_analyses: int = 0
    incremental_analyses: int = 0
    skipped_analyses: int = 0
    last_recommendation: str | None = None
    last_manifest_yaml: str | None = None
    version: int = 1


class AnalystStateManager:
    """Manages per-project analyst state stored in .phantom-state.json."""

    def __init__(self, project_dir: Path) -> None:
        self._project_dir = project_dir
        self._path = project_dir / STATE_FILENAME
        self._state: AnalystStateData | None = None

    @property
    def state_path(self) -> Path:
        return self._path

    def has_state(self) -> bool:
        """Check if a state file exists for this project."""
        return self._path.exists()

    def load(self) -> AnalystStateData:
        """Load state from disk. Returns empty state if file doesn't exist."""
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._state = self._deserialize(data)
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning(
                    "analyst_state_load_failed",
                    error=str(e),
                    path=str(self._path),
                )
                self._state = AnalystStateData()
        else:
            self._state = AnalystStateData()

        return self._state

    def save(self) -> None:
        """Write state to disk atomically (write to temp, then rename)."""
        if self._state is None:
            return

        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self._state)
        content = json.dumps(data, indent=2, default=str)

        # Atomic write: write to temp file in same directory, then rename
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self._path.parent),
            prefix=".phantom_analyst_state_",
            suffix=".tmp",
        )
        closed = False
        try:
            os.write(fd, content.encode("utf-8"))
            os.fsync(fd)
            os.close(fd)
            closed = True
            os.replace(tmp_path, str(self._path))
            logger.debug("analyst_state_saved", path=str(self._path))
        except Exception as e:
            if not closed:
                os.close(fd)
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise AnalystStateError(f"Failed to save analyst state: {e}") from e

    def get_last_commit(self) -> str | None:
        """Get the last analyzed commit SHA."""
        state = self._state or self.load()
        return state.last_analysis_commit

    def update_after_analysis(
        self,
        *,
        commit_sha: str | None = None,
        manifest_yaml: str | None = None,
        cost_usd: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        recommendation: str = "full",
    ) -> None:
        """Update state after a completed analysis run."""
        state = self._state or self.load()

        if commit_sha:
            state.last_analysis_commit = commit_sha

        if manifest_yaml:
            state.manifest_hash = hashlib.sha256(manifest_yaml.encode()).hexdigest()[:16]
            state.last_manifest_yaml = manifest_yaml

        state.cumulative_cost_usd += cost_usd
        state.cumulative_input_tokens += input_tokens
        state.cumulative_output_tokens += output_tokens
        state.total_analyses += 1
        state.last_recommendation = recommendation

        if recommendation == "full":
            state.full_analyses += 1
        elif recommendation == "incremental":
            state.incremental_analyses += 1
        elif recommendation == "skip":
            state.skipped_analyses += 1

        self.save()

    @staticmethod
    def compute_manifest_hash(manifest_yaml: str) -> str:
        """Compute a short hash of a manifest YAML string."""
        return hashlib.sha256(manifest_yaml.encode()).hexdigest()[:16]

    @staticmethod
    def _deserialize(data: dict[str, object]) -> AnalystStateData:
        """Deserialize a dict to AnalystStateData, handling missing keys."""

        def _str_or_none(val: object) -> str | None:
            return str(val) if val is not None else None

        def _to_float(val: object, default: float = 0.0) -> float:
            if val is None:
                return default
            if isinstance(val, (int, float)):
                return float(val)
            try:
                return float(str(val))
            except (TypeError, ValueError):
                return default

        def _to_int(val: object, default: int = 0) -> int:
            if val is None:
                return default
            if isinstance(val, int):
                return val
            if isinstance(val, float):
                return int(val)
            try:
                return int(str(val))
            except (TypeError, ValueError):
                return default

        raw_captures = data.get("capture_hashes", {})

        return AnalystStateData(
            last_analysis_commit=_str_or_none(data.get("last_analysis_commit")),
            manifest_hash=_str_or_none(data.get("manifest_hash")),
            capture_hashes=dict(raw_captures) if isinstance(raw_captures, dict) else {},
            cumulative_cost_usd=_to_float(data.get("cumulative_cost_usd")),
            cumulative_input_tokens=_to_int(data.get("cumulative_input_tokens")),
            cumulative_output_tokens=_to_int(data.get("cumulative_output_tokens")),
            total_analyses=_to_int(data.get("total_analyses")),
            full_analyses=_to_int(data.get("full_analyses")),
            incremental_analyses=_to_int(data.get("incremental_analyses")),
            skipped_analyses=_to_int(data.get("skipped_analyses")),
            last_recommendation=_str_or_none(data.get("last_recommendation")),
            last_manifest_yaml=_str_or_none(data.get("last_manifest_yaml")),
            version=_to_int(data.get("version"), 1),
        )
