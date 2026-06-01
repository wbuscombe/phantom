"""Conductor orchestrator — coordinates the full phantom run pipeline.

State machine:
    INIT → VALIDATING → WORKSPACE → BUILDING → SEEDING → LAUNCHING →
    CAPTURING → PROCESSING → PUBLISHING → TEARDOWN → COMPLETED

On failure at any stage: → TEARDOWN → FAILED
"""

from __future__ import annotations

import fcntl
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from phantom import __version__
from phantom.conductor.state import RunRecord, StateManager
from phantom.conductor.workspace import Workspace
from phantom.darkroom.pipeline import DarkroomPipeline
from phantom.exceptions import ConductorError, LockError
from phantom.publisher.readme import ReadmeUpdate, update_readme_file
from phantom.runners.base import BaseRunner, CaptureResult, RunnerContext

if TYPE_CHECKING:
    from phantom.darkroom.pipeline import PipelineResult
    from phantom.models import PhantomManifest

logger = structlog.get_logger()


class JobState(Enum):
    INIT = "init"
    VALIDATING = "validating"
    WORKSPACE = "workspace"
    BUILDING = "building"
    SEEDING = "seeding"
    LAUNCHING = "launching"
    CAPTURING = "capturing"
    PROCESSING = "processing"
    PUBLISHING = "publishing"
    TEARDOWN = "teardown"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class JobOptions:
    """Options that control job behavior."""

    dry_run: bool = False
    skip_publish: bool = False
    force: bool = False
    capture_id: str | None = None
    capture_ids: list[str] | None = None  # For incremental: specific captures to run
    group: str | None = None
    local_project: Path | None = None  # For local dev, skip clone
    if_changed: bool = False  # Skip if repo HEAD matches last captured SHA
    trigger_source: str = "cli"  # "cli", "webhook", "schedule"


@dataclass
class JobReport:
    """Summary report of a phantom run."""

    project: str
    state: JobState
    captures_total: int = 0
    captures_succeeded: int = 0
    captures_failed: int = 0
    captures_changed: int = 0
    captures_unchanged: int = 0
    files_committed: int = 0
    commit_sha: str | None = None
    readme_updated: bool = False
    stale_removed: int = 0
    duration_ms: int = 0
    error: str | None = None
    capture_results: list[CaptureResult] = field(default_factory=list)
    pipeline_results: list[PipelineResult] = field(default_factory=list)
    trigger_source: str = "cli"
    skipped_unchanged: bool = False
    blocked_by_quality: bool = False
    avg_diff_pct: float | None = None
    quality_reports: list[Any] = field(default_factory=list)
    consistency_report: Any | None = None


class Orchestrator:
    """Coordinates the full phantom run pipeline."""

    def __init__(
        self,
        manifest: PhantomManifest,
        options: JobOptions,
        workspace_root: Path | None = None,
        state_manager: StateManager | None = None,
    ) -> None:
        self._manifest = manifest
        self._options = options
        self._workspace_root = workspace_root or Path("/tmp/phantom/workspace")
        self._state_mgr = state_manager or StateManager()
        self._state = JobState.INIT
        self._lock_fd: int | None = None
        self._workspace: Workspace | None = None

    @property
    def state(self) -> JobState:
        return self._state

    async def run(self) -> JobReport:
        """Execute the full pipeline. Returns a report regardless of outcome."""
        start = time.monotonic()
        report = JobReport(
            project=self._manifest.project,
            state=JobState.INIT,
            trigger_source=self._options.trigger_source,
        )

        try:
            # Acquire lock
            self._acquire_lock()

            # Check --if-changed: compare HEAD against last captured SHA
            if self._options.if_changed and self._check_unchanged():
                report.state = JobState.COMPLETED
                report.skipped_unchanged = True
                logger.info(
                    "job_skipped_unchanged",
                    project=self._manifest.project,
                )
                return report

            # Set up workspace
            self._transition(JobState.WORKSPACE)
            workspace = self._create_workspace()
            self._workspace = workspace

            # Build runner
            self._transition(JobState.BUILDING)
            runner = self._create_runner()
            ctx = self._build_runner_context(workspace)

            # Setup (build commands)
            await runner.setup(ctx)

            # Seed (fixtures)
            self._transition(JobState.SEEDING)
            await self._run_fixtures(workspace)

            # Launch application
            self._transition(JobState.LAUNCHING)
            await runner.launch(ctx)

            # Capture
            self._transition(JobState.CAPTURING)
            capture_results = await self._run_captures(runner, ctx)
            report.capture_results = capture_results
            report.captures_total = len(capture_results)
            report.captures_succeeded = sum(1 for r in capture_results if r.success)
            report.captures_failed = sum(1 for r in capture_results if not r.success)

            # Teardown the runner (application) before processing
            self._transition(JobState.TEARDOWN)
            await runner.teardown(ctx)

            # Process through darkroom
            self._transition(JobState.PROCESSING)
            pipeline_results = await self._process_captures(capture_results, workspace)
            report.pipeline_results = pipeline_results
            report.captures_changed = sum(1 for r in pipeline_results if r.changed)
            report.captures_unchanged = sum(1 for r in pipeline_results if not r.changed)

            # Calculate average diff percentage
            report.avg_diff_pct = self._compute_avg_diff_pct(pipeline_results)

            # Copy processed files to project dir
            self._copy_outputs_to_project(pipeline_results, workspace)

            # Quality checks (warnings only, don't block)
            quality_reports, consistency_report = self._check_quality(pipeline_results, workspace)
            report.quality_reports = quality_reports
            report.consistency_report = consistency_report

            # Publish
            self._transition(JobState.PUBLISHING)
            await self._publish(pipeline_results, workspace, report)

            self._transition(JobState.COMPLETED)
            report.state = JobState.COMPLETED

        except LockError as e:
            report.state = JobState.FAILED
            report.error = str(e)
            logger.error("job_lock_failed", error=str(e))

        except Exception as e:
            report.state = JobState.FAILED
            report.error = str(e)
            logger.error(
                "job_failed",
                state=self._state.value,
                error=str(e),
            )
            # Attempt teardown if we have a workspace
            if self._workspace:
                try:
                    runner_for_teardown = self._create_runner()
                    ctx_for_teardown = self._build_runner_context(self._workspace)
                    await runner_for_teardown.teardown(ctx_for_teardown)
                except Exception:
                    pass

        finally:
            # Release lock
            self._release_lock()

            # Record run in state
            elapsed = int((time.monotonic() - start) * 1000)
            report.duration_ms = elapsed
            self._record_run(report)

            # Emit structured run report
            self._emit_run_report(report)

        return report

    def _check_unchanged(self) -> bool:
        """Check if the project is unchanged since last capture.

        Compares current repo HEAD against the last captured SHA in state.
        Returns True if unchanged (should skip).
        """
        last_sha = self._state_mgr.get_last_sha(self._manifest.project)
        if not last_sha:
            return False

        # For local projects, get the HEAD SHA from the project dir
        if self._options.local_project:
            head_sha = self._get_local_head_sha(self._options.local_project)
            if head_sha and head_sha == last_sha:
                logger.info(
                    "if_changed_skip",
                    project=self._manifest.project,
                    sha=head_sha[:8],
                )
                return True

        return False

    @staticmethod
    def _get_local_head_sha(project_dir: Path) -> str | None:
        """Get the HEAD SHA of a local git repository."""
        import subprocess

        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None

    def _acquire_lock(self) -> None:
        """Acquire flock-based lock to prevent concurrent runs (ADR-011)."""
        lock_dir = self._workspace_root / ".locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_file = lock_dir / f"{self._manifest.project}.lock"

        try:
            fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_fd = fd
            logger.debug("lock_acquired", project=self._manifest.project)
        except OSError as e:
            raise LockError(
                f"Another Phantom instance is running for project "
                f"'{self._manifest.project}'. If this is incorrect, "
                f"remove {lock_file}"
            ) from e

    def _release_lock(self) -> None:
        """Release the flock."""
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None

    def _transition(self, new_state: JobState) -> None:
        """Transition to a new state with logging."""
        old = self._state
        self._state = new_state
        logger.info(
            "job_state",
            from_state=old.value,
            to_state=new_state.value,
            timestamp=time.time(),
        )

    def _create_workspace(self) -> Workspace:
        """Create and set up the workspace."""
        workspace = Workspace(self._workspace_root, self._manifest.project)
        workspace.create()

        if self._options.local_project:
            workspace.use_local(self._options.local_project)
        else:
            raise ConductorError("Remote clone not yet supported. Use --project with a local path.")

        return workspace

    def _create_runner(self) -> BaseRunner:
        """Create the appropriate runner based on setup type."""
        from phantom.runners import get_runner

        return get_runner(self._manifest.setup.type)

    def _build_runner_context(self, workspace: Workspace) -> RunnerContext:
        """Build a RunnerContext for the runner."""
        return RunnerContext(
            project_dir=workspace.project_dir,
            raw_output_dir=workspace.raw_dir,
            manifest=self._manifest,
        )

    async def _run_fixtures(self, workspace: Workspace) -> None:
        """Execute manifest fixtures."""
        if not self._manifest.fixtures:
            return

        from phantom.conductor.fixtures import run_fixtures

        env = self._manifest.setup.run.env or {}
        await run_fixtures(self._manifest.fixtures, workspace.project_dir, env)

    async def _run_captures(self, runner: BaseRunner, ctx: RunnerContext) -> list[CaptureResult]:
        """Run captures, optionally filtered by --capture, --capture-ids, or --group."""

        # If --capture is specified, filter to just that capture
        if self._options.capture_id:
            resolved = ctx.manifest.resolve_captures()
            target = next((c for c in resolved if c.id == self._options.capture_id), None)
            if target is None:
                raise ConductorError(f"Capture '{self._options.capture_id}' not found in manifest")
            if target.skip:
                logger.info("capture_skipped", capture_id=target.id)
                return []
            result = await runner._capture_with_retry(ctx, target)
            return [result]

        # If capture_ids list is specified (incremental mode), filter to those
        if self._options.capture_ids:
            target_ids = set(self._options.capture_ids)
            resolved = ctx.manifest.resolve_captures()
            results: list[CaptureResult] = []
            for cap in resolved:
                if cap.id in target_ids and not cap.skip:
                    result = await runner._capture_with_retry(ctx, cap)
                    results.append(result)
            return results

        # If --group is specified, filter to group members
        if self._options.group:
            group_ids = set(ctx.manifest.get_group(self._options.group))
            resolved = ctx.manifest.resolve_captures()
            results = []
            for cap in resolved:
                if cap.id in group_ids and not cap.skip:
                    result = await runner._capture_with_retry(ctx, cap)
                    results.append(result)
            return results

        # Default: run all
        return await runner.run_all(ctx)

    async def _process_captures(
        self, capture_results: list[CaptureResult], workspace: Workspace
    ) -> list[PipelineResult]:
        """Process successful captures through the darkroom pipeline."""

        pipeline = DarkroomPipeline()
        results: list[PipelineResult] = []

        # Fetch previous screenshots for diff
        output_paths = [cap.output for cap in self._manifest.captures]
        previous_map = await workspace.fetch_previous_screenshots(
            output_paths, self._manifest.publishing.branch
        )

        for capture_result in capture_results:
            if not capture_result.success or capture_result.output_path is None:
                continue

            # Find the capture definition for output path mapping
            cap_def = next(
                (c for c in self._manifest.captures if c.id == capture_result.capture_id),
                None,
            )
            previous_path = previous_map.get(cap_def.output) if cap_def else None

            result = await pipeline.process(
                capture_id=capture_result.capture_id,
                raw_path=capture_result.output_path,
                output_dir=workspace.processed_dir,
                processing_config=self._manifest.processing,
                previous_path=previous_path,
            )
            results.append(result)

        return results

    @staticmethod
    def _compute_avg_diff_pct(pipeline_results: list[PipelineResult]) -> float | None:
        """Compute the average diff percentage across changed captures."""
        diffs: list[float] = []
        for r in pipeline_results:
            if r.changed:
                diff_stage = r.stage_results.get("diff")
                if diff_stage and diff_stage.metadata:
                    pct = diff_stage.metadata.get("diff_pct")
                    if isinstance(pct, (int, float)):
                        diffs.append(float(pct))
        return sum(diffs) / len(diffs) if diffs else None

    def _copy_outputs_to_project(
        self, pipeline_results: list[PipelineResult], workspace: Workspace
    ) -> None:
        """Copy processed outputs to their final locations in the project directory."""
        import shutil

        for result in pipeline_results:
            if not result.output_path.exists():
                continue

            cap_def = next(
                (c for c in self._manifest.captures if c.id == result.capture_id),
                None,
            )
            if not cap_def:
                continue

            dest = workspace.project_dir / cap_def.output
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(result.output_path, dest)
            # Update the result's output_path to point to the final location
            result.output_path = dest

    async def _publish(
        self,
        pipeline_results: list[PipelineResult],
        workspace: Workspace,
        report: JobReport,
    ) -> None:
        """Handle README updates and git publishing."""
        if self._options.skip_publish:
            logger.info("publish_skipped", reason="--skip-publish flag")
            return

        # Quality gate (RC-A.1): never commit/push a capture that failed an
        # error-severity quality check unless --force was given. Warnings stay
        # advisory; only error-severity issues (blank/too-small/bad-dimensions)
        # block, so intentional low-entropy frames (splash screens) still
        # publish. QualityReport.passed is False iff an error-severity issue
        # was found (see analyst.quality.QualityChecker).
        failed = [qr for qr in report.quality_reports if not getattr(qr, "passed", True)]
        if failed and not self._options.force:
            report.blocked_by_quality = True
            error_issues = [
                issue.message
                for qr in failed
                for issue in getattr(qr, "issues", [])
                if getattr(issue, "severity", "") == "error"
            ]
            logger.error(
                "publish_blocked_quality",
                captures=[getattr(qr, "capture_id", "?") for qr in failed],
                issues=error_issues,
                hint="re-run with --force to publish anyway",
            )
            return

        # Update README sentinels
        readme_updated = False
        if self._manifest.publishing.readme_update:
            readme_updated = self._update_readme(pipeline_results, workspace)
            report.readme_updated = readme_updated

        # Handle stale cleanup
        if self._manifest.publishing.cleanup_stale:
            stale_count = await self._cleanup_stale(pipeline_results, workspace)
            report.stale_removed = stale_count

        # Git publish
        from phantom.publisher.git import publish

        pub_result = await publish(
            repo_dir=workspace.project_dir,
            pipeline_results=pipeline_results,
            publishing_config=self._manifest.publishing,
            project_name=self._manifest.project,
            readme_updated=readme_updated,
            force=self._options.force,
            dry_run=self._options.dry_run,
        )

        report.commit_sha = pub_result.commit_sha
        report.files_committed = pub_result.files_added

    def _update_readme(self, pipeline_results: list[PipelineResult], workspace: Workspace) -> bool:
        """Update README sentinel regions with new image tags."""
        # Build updates from pipeline results, checking all configured readme targets
        updates: dict[str, ReadmeUpdate] = {}

        for result in pipeline_results:
            if not result.changed and not self._options.force:
                continue

            cap_def = next(
                (c for c in self._manifest.captures if c.id == result.capture_id),
                None,
            )
            if not cap_def or not cap_def.readme_target:
                continue

            resolved = cap_def.resolve(self._manifest.capture_defaults)
            logical_width = resolved.viewport.width

            updates[cap_def.readme_target] = ReadmeUpdate(
                capture_id=cap_def.readme_target,
                img_path=cap_def.output,
                alt_text=resolved.alt_text or resolved.name,
                logical_width=logical_width,
            )

        if not updates:
            return False

        # Find README file
        readme_path = None
        for name in ["README.md", "readme.md", "README.rst", "README"]:
            candidate = workspace.project_dir / name
            if candidate.exists():
                readme_path = candidate
                break

        if readme_path is None:
            # Warn about captures with readme_target but no README
            for capture_id in updates:
                logger.warning(
                    "readme_target_no_readme",
                    capture_id=capture_id,
                )
            return False

        readme_result = update_readme_file(readme_path, updates)
        return readme_result.updated

    async def _cleanup_stale(
        self, pipeline_results: list[PipelineResult], workspace: Workspace
    ) -> int:
        """Remove screenshots not referenced by any capture."""
        from phantom.publisher.git import find_stale_screenshots, remove_stale_files

        known_outputs = {cap.output for cap in self._manifest.captures}

        # Determine output directory from first capture's output path
        if not self._manifest.captures:
            return 0

        first_output = self._manifest.captures[0].output
        output_dir = str(Path(first_output).parent)

        stale = await find_stale_screenshots(workspace.project_dir, output_dir, known_outputs)

        if stale:
            logger.info("stale_screenshots_found", count=len(stale), files=stale)
            return await remove_stale_files(workspace.project_dir, stale)

        return 0

    def _check_quality(
        self,
        pipeline_results: list[PipelineResult],
        workspace: Workspace,
    ) -> tuple[list[Any], Any | None]:
        """Run quality checks on processed screenshots. Returns (reports, consistency)."""
        try:
            from phantom.analyst.quality import QualityChecker
        except ImportError:
            return [], None

        checker = QualityChecker()
        reports = []

        for result in pipeline_results:
            # Find the final output path in the project dir
            cap_def = next(
                (c for c in self._manifest.captures if c.id == result.capture_id),
                None,
            )
            if not cap_def:
                continue

            output_path = workspace.project_dir / cap_def.output
            if not output_path.exists():
                continue

            try:
                qr = checker.check_screenshot(output_path, result.capture_id)
                reports.append(qr)

                if not qr.passed:
                    logger.warning(
                        "quality_check_failed",
                        capture_id=result.capture_id,
                        issues=[i.message for i in qr.issues if i.severity == "error"],
                    )
                elif qr.issues:
                    logger.info(
                        "quality_check_warnings",
                        capture_id=result.capture_id,
                        warnings=[i.message for i in qr.issues],
                    )
            except Exception as e:
                logger.warning(
                    "quality_check_error",
                    capture_id=result.capture_id,
                    error=str(e),
                )

        consistency = None
        if reports:
            try:
                consistency = checker.check_consistency(reports)
                if consistency.issues:
                    logger.info(
                        "quality_consistency_warnings",
                        issues=[i.message for i in consistency.issues],
                    )
            except Exception as e:
                logger.warning("quality_consistency_error", error=str(e))

        return reports, consistency

    def _record_run(self, report: JobReport) -> None:
        """Record this run in the state manager."""
        record = RunRecord(
            timestamp=StateManager.now(),
            project=report.project,
            status=report.state.value,
            captures_total=report.captures_total,
            captures_changed=report.captures_changed,
            captures_failed=report.captures_failed,
            commit_sha=report.commit_sha,
            duration_ms=report.duration_ms,
            error=report.error,
            trigger_source=report.trigger_source,
            diff_pct=report.avg_diff_pct,
        )
        try:
            self._state_mgr.record_run(record)
        except Exception as e:
            logger.warning("state_record_failed", error=str(e))

    def _emit_run_report(self, report: JobReport) -> None:
        """Emit a structured run report to logs."""
        changed_captures = [r.capture_id for r in report.pipeline_results if r.changed]
        unchanged_captures = [r.capture_id for r in report.pipeline_results if not r.changed]
        failed_captures = [r.capture_id for r in report.capture_results if not r.success]

        logger.info(
            "run_report",
            project=report.project,
            status=report.state.value,
            trigger=report.trigger_source,
            phantom_version=__version__,
            captures_total=report.captures_total,
            captures_succeeded=report.captures_succeeded,
            captures_failed=report.captures_failed,
            captures_changed=report.captures_changed,
            captures_unchanged=report.captures_unchanged,
            changed_ids=changed_captures,
            unchanged_ids=unchanged_captures,
            failed_ids=failed_captures,
            commit_sha=report.commit_sha,
            readme_updated=report.readme_updated,
            stale_removed=report.stale_removed,
            duration_ms=report.duration_ms,
            avg_diff_pct=report.avg_diff_pct,
            skipped_unchanged=report.skipped_unchanged,
        )
