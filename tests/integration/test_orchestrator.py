"""Integration tests for the Conductor orchestrator.

Tests the orchestrator coordination logic including locking,
state management, and publish workflows. Uses a mock runner
to avoid Playwright dependency.
"""

from __future__ import annotations

import asyncio
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from PIL import Image

from phantom.conductor.orchestrator import JobOptions, JobState, Orchestrator
from phantom.conductor.state import StateManager
from phantom.models import load_manifest

if TYPE_CHECKING:
    from pathlib import Path


def _write_test_manifest(manifest_path: Path, project_dir: Path) -> None:
    """Write a minimal manifest for testing."""
    screenshots = project_dir / "docs" / "screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)

    manifest_path.write_text("""\
phantom: "1"
project: "test-project"
name: "Test Project"
setup:
  type: web
  run:
    command: "echo serving"
    ready_check:
      type: delay
      seconds: 0
captures:
  - id: dashboard
    name: "Dashboard"
    route: "/"
    output: "docs/screenshots/dashboard.png"
  - id: settings
    name: "Settings"
    route: "/settings"
    output: "docs/screenshots/settings.png"
processing:
  border:
    style: none
  optimize: false
publishing:
  branch: main
  readme_update: false
""")


def _init_test_repo(path: Path) -> None:
    """Initialize a git repo with an initial commit."""
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
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


def _create_mock_runner(project_dir: Path, captures: list[str]):
    """Create a mock runner that produces test screenshots."""
    from phantom.runners.base import BaseRunner, CaptureResult, RunnerContext

    class MockRunner(BaseRunner):
        async def setup(self, ctx: RunnerContext) -> None:
            pass

        async def launch(self, ctx: RunnerContext) -> None:
            pass

        async def capture(self, ctx: RunnerContext, capture_def) -> CaptureResult:
            output_path = ctx.raw_output_dir / f"{capture_def.id}.png"
            img = Image.new("RGB", (400, 300), (30, 30, 50))
            img.save(output_path)
            return CaptureResult(
                capture_id=capture_def.id,
                success=True,
                output_path=output_path,
                duration_ms=100,
            )

        async def teardown(self, ctx: RunnerContext) -> None:
            pass

    return MockRunner()


class TestOrchestratorLocking:
    @pytest.mark.integration
    def test_lock_prevents_concurrent_run(self, tmp_path: Path) -> None:
        """Second orchestrator should fail with LockError."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        _init_test_repo(project_dir)

        manifest_path = project_dir / ".phantom.yml"
        _write_test_manifest(manifest_path, project_dir)
        manifest = load_manifest(str(manifest_path))

        workspace_root = tmp_path / "workspace"
        state_file = tmp_path / "state.json"

        options = JobOptions(
            skip_publish=True,
            local_project=project_dir,
        )

        # First orchestrator acquires lock
        orch1 = Orchestrator(
            manifest=manifest,
            options=options,
            workspace_root=workspace_root,
            state_manager=StateManager(state_file),
        )

        # Manually acquire lock by accessing private method
        orch1._acquire_lock()

        # Second orchestrator should fail
        orch2 = Orchestrator(
            manifest=manifest,
            options=options,
            workspace_root=workspace_root,
            state_manager=StateManager(state_file),
        )

        report = asyncio.get_event_loop().run_until_complete(orch2.run())
        assert report.state == JobState.FAILED
        assert "Another Phantom instance" in (report.error or "")

        # Release first lock
        orch1._release_lock()


class TestOrchestratorRun:
    @pytest.mark.integration
    def test_skip_publish_mode(self, tmp_path: Path) -> None:
        """--skip-publish should process but not touch git."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        _init_test_repo(project_dir)

        manifest_path = project_dir / ".phantom.yml"
        _write_test_manifest(manifest_path, project_dir)
        manifest = load_manifest(str(manifest_path))

        options = JobOptions(
            skip_publish=True,
            local_project=project_dir,
        )

        mock_runner = _create_mock_runner(project_dir, ["dashboard", "settings"])

        orch = Orchestrator(
            manifest=manifest,
            options=options,
            workspace_root=tmp_path / "workspace",
            state_manager=StateManager(tmp_path / "state.json"),
        )

        with patch.object(orch, "_create_runner", return_value=mock_runner):
            report = asyncio.get_event_loop().run_until_complete(orch.run())

        assert report.state == JobState.COMPLETED
        assert report.captures_total == 2
        assert report.captures_succeeded == 2
        assert report.commit_sha is None  # No commit in skip-publish mode

    @pytest.mark.integration
    def test_dry_run_mode(self, tmp_path: Path) -> None:
        """--dry-run should process and publish but not actually commit."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        _init_test_repo(project_dir)

        manifest_path = project_dir / ".phantom.yml"
        _write_test_manifest(manifest_path, project_dir)
        manifest = load_manifest(str(manifest_path))

        options = JobOptions(
            dry_run=True,
            local_project=project_dir,
        )

        mock_runner = _create_mock_runner(project_dir, ["dashboard", "settings"])

        orch = Orchestrator(
            manifest=manifest,
            options=options,
            workspace_root=tmp_path / "workspace",
            state_manager=StateManager(tmp_path / "state.json"),
        )

        # Get initial commit count
        log_before = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
        )

        with patch.object(orch, "_create_runner", return_value=mock_runner):
            report = asyncio.get_event_loop().run_until_complete(orch.run())

        assert report.state == JobState.COMPLETED
        assert report.commit_sha is None

        # Commit count should be unchanged
        log_after = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
        )
        assert log_before.stdout == log_after.stdout

    @pytest.mark.integration
    def test_capture_filter(self, tmp_path: Path) -> None:
        """--capture should only run the specified capture."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        _init_test_repo(project_dir)

        manifest_path = project_dir / ".phantom.yml"
        _write_test_manifest(manifest_path, project_dir)
        manifest = load_manifest(str(manifest_path))

        options = JobOptions(
            skip_publish=True,
            capture_id="dashboard",
            local_project=project_dir,
        )

        mock_runner = _create_mock_runner(project_dir, ["dashboard"])

        orch = Orchestrator(
            manifest=manifest,
            options=options,
            workspace_root=tmp_path / "workspace",
            state_manager=StateManager(tmp_path / "state.json"),
        )

        with patch.object(orch, "_create_runner", return_value=mock_runner):
            report = asyncio.get_event_loop().run_until_complete(orch.run())

        assert report.state == JobState.COMPLETED
        assert report.captures_total == 1  # Only dashboard
        assert report.capture_results[0].capture_id == "dashboard"

    @pytest.mark.integration
    def test_state_recorded(self, tmp_path: Path) -> None:
        """Run should be recorded in state file."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        _init_test_repo(project_dir)

        manifest_path = project_dir / ".phantom.yml"
        _write_test_manifest(manifest_path, project_dir)
        manifest = load_manifest(str(manifest_path))

        state_file = tmp_path / "state.json"
        options = JobOptions(
            skip_publish=True,
            local_project=project_dir,
        )

        mock_runner = _create_mock_runner(project_dir, ["dashboard", "settings"])

        orch = Orchestrator(
            manifest=manifest,
            options=options,
            workspace_root=tmp_path / "workspace",
            state_manager=StateManager(state_file),
        )

        with patch.object(orch, "_create_runner", return_value=mock_runner):
            asyncio.get_event_loop().run_until_complete(orch.run())

        # Verify state was recorded
        mgr = StateManager(state_file)
        recent = mgr.get_recent_runs(project="test-project")
        assert len(recent) == 1
        assert recent[0].status == "completed"
        assert recent[0].captures_total == 2

    @pytest.mark.integration
    def test_nonexistent_capture_id(self, tmp_path: Path) -> None:
        """--capture with a non-existent ID should fail."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        _init_test_repo(project_dir)

        manifest_path = project_dir / ".phantom.yml"
        _write_test_manifest(manifest_path, project_dir)
        manifest = load_manifest(str(manifest_path))

        options = JobOptions(
            skip_publish=True,
            capture_id="nonexistent",
            local_project=project_dir,
        )

        mock_runner = _create_mock_runner(project_dir, [])

        orch = Orchestrator(
            manifest=manifest,
            options=options,
            workspace_root=tmp_path / "workspace",
            state_manager=StateManager(tmp_path / "state.json"),
        )

        with patch.object(orch, "_create_runner", return_value=mock_runner):
            report = asyncio.get_event_loop().run_until_complete(orch.run())

        assert report.state == JobState.FAILED
        assert "nonexistent" in (report.error or "")


class TestOrchestratorQualityGate:
    """The publish step must not commit/push frames that fail an
    error-severity quality check unless --force is given (RC-A.1)."""

    @staticmethod
    def _runner_producing(make_image):
        """Build a mock runner whose every capture writes ``make_image()``."""
        from phantom.runners.base import BaseRunner, CaptureResult, RunnerContext

        class _Runner(BaseRunner):
            async def setup(self, ctx: RunnerContext) -> None:
                pass

            async def launch(self, ctx: RunnerContext) -> None:
                pass

            async def capture(self, ctx: RunnerContext, capture_def) -> CaptureResult:
                output_path = ctx.raw_output_dir / f"{capture_def.id}.png"
                make_image().save(output_path)
                return CaptureResult(
                    capture_id=capture_def.id,
                    success=True,
                    output_path=output_path,
                    duration_ms=10,
                )

            async def teardown(self, ctx: RunnerContext) -> None:
                pass

        return _Runner()

    @staticmethod
    def _blank_image():
        # Solid white -> blank_detection (uniformity 1.0) AND tiny file: error severity.
        return Image.new("RGB", (800, 600), (255, 255, 255))

    @staticmethod
    def _warning_only_image():
        # Wide RGB noise: rich content (no blank/size/dimension errors) but a
        # 6:1 aspect ratio -> aspect_ratio WARNING only, so it should still publish.
        import numpy as np

        rng = np.random.default_rng(0)
        arr = rng.integers(0, 256, size=(200, 1200, 3), dtype="uint8")
        return Image.fromarray(arr, "RGB")

    @staticmethod
    def _commit_count(project_dir: Path) -> str:
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def _run(self, tmp_path: Path, make_image, **option_kwargs):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        _init_test_repo(project_dir)
        manifest_path = project_dir / ".phantom.yml"
        _write_test_manifest(manifest_path, project_dir)
        manifest = load_manifest(str(manifest_path))

        options = JobOptions(
            local_project=project_dir, **option_kwargs
        )  # publish ON unless overridden
        orch = Orchestrator(
            manifest=manifest,
            options=options,
            workspace_root=tmp_path / "workspace",
            state_manager=StateManager(tmp_path / "state.json"),
        )
        runner = self._runner_producing(make_image)
        before = self._commit_count(project_dir)
        with patch.object(orch, "_create_runner", return_value=runner):
            report = asyncio.get_event_loop().run_until_complete(orch.run())
        after = self._commit_count(project_dir)
        return report, before, after

    @pytest.mark.integration
    def test_publish_blocked_on_quality_failure(self, tmp_path: Path) -> None:
        """An error-severity quality failure must block commit/push (no --force)."""
        report, before, after = self._run(tmp_path, self._blank_image, force=False)

        assert report.commit_sha is None, "blocked publish must not produce a commit"
        assert report.blocked_by_quality is True
        assert after == before, "no new commit should be created when blocked"

    @pytest.mark.integration
    def test_force_overrides_quality_gate(self, tmp_path: Path) -> None:
        """--force publishes even when quality fails (protects onboarded projects/CI)."""
        report, before, after = self._run(tmp_path, self._blank_image, force=True)

        assert report.blocked_by_quality is False
        assert report.commit_sha is not None, "--force must publish despite quality failure"
        assert after != before, "a commit should be created when forced"

    @pytest.mark.integration
    def test_warning_severity_still_publishes(self, tmp_path: Path) -> None:
        """Warning-only issues (e.g. extreme aspect ratio) must NOT block publish."""
        report, before, after = self._run(tmp_path, self._warning_only_image, force=False)

        assert report.blocked_by_quality is False
        assert report.commit_sha is not None, "warning-only frames should still publish"
        assert after != before

    # ── CI fail-closed path: --skip-publish + --fail-on-quality-error (RC-A.1/CI) ──

    @pytest.mark.integration
    def test_skip_publish_fail_on_quality_marks_blocked(self, tmp_path: Path) -> None:
        """In --skip-publish mode (used by CI), --fail-on-quality-error must flag an
        error-severity run as blocked so the CLI exits non-zero and CI skips commit."""
        report, before, after = self._run(
            tmp_path, self._blank_image, skip_publish=True, fail_on_quality_error=True
        )

        assert report.blocked_by_quality is True
        assert report.commit_sha is None  # --skip-publish never commits
        assert after == before

    @pytest.mark.integration
    def test_skip_publish_without_flag_not_blocked(self, tmp_path: Path) -> None:
        """--skip-publish alone (no fail-on-quality flag) must NOT block, even on a
        bad frame — preserves the local 'inspect without committing' workflow."""
        report, _before, _after = self._run(tmp_path, self._blank_image, skip_publish=True)

        assert report.blocked_by_quality is False

    @pytest.mark.integration
    def test_skip_publish_force_overrides_fail_on_quality(self, tmp_path: Path) -> None:
        """--force overrides the CI quality gate (wireable into CI via an input)."""
        report, _before, _after = self._run(
            tmp_path,
            self._blank_image,
            skip_publish=True,
            fail_on_quality_error=True,
            force=True,
        )

        assert report.blocked_by_quality is False


class TestCIQualityGateCLI:
    """End-to-end CLI exit codes for `phantom run --skip-publish --fail-on-quality-error`."""

    @staticmethod
    def _project(tmp_path: Path) -> Path:
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        _init_test_repo(project_dir)
        _write_test_manifest(project_dir / ".phantom.yml", project_dir)
        return project_dir

    @staticmethod
    def _invoke(project_dir: Path, make_image, extra_args: list[str]):
        from click.testing import CliRunner

        from phantom.cli import main

        runner = TestOrchestratorQualityGate._runner_producing(make_image)
        with patch("phantom.runners.get_runner", return_value=runner):
            return CliRunner().invoke(
                main, ["run", "-p", str(project_dir), "--skip-publish", *extra_args]
            )

    @pytest.mark.integration
    def test_exit_nonzero_on_error_frame(self, tmp_path: Path) -> None:
        result = self._invoke(
            self._project(tmp_path),
            TestOrchestratorQualityGate._blank_image,
            ["--fail-on-quality-error"],
        )
        assert result.exit_code == 1
        assert "quality" in result.output.lower()

    @pytest.mark.integration
    def test_exit_zero_when_quality_ok(self, tmp_path: Path) -> None:
        result = self._invoke(
            self._project(tmp_path),
            TestOrchestratorQualityGate._warning_only_image,
            ["--fail-on-quality-error"],
        )
        assert result.exit_code == 0

    @pytest.mark.integration
    def test_force_overrides_exit(self, tmp_path: Path) -> None:
        result = self._invoke(
            self._project(tmp_path),
            TestOrchestratorQualityGate._blank_image,
            ["--fail-on-quality-error", "--force"],
        )
        assert result.exit_code == 0
