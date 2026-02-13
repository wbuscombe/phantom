"""Git operations for committing and pushing processed screenshots.

Handles: staging files, composing commit messages, committing with
configurable author, pushing with conflict retry, and stale file cleanup.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

from phantom import __version__
from phantom.exceptions import GitOperationError, PushConflictError
from phantom.utils.process import run_command

if TYPE_CHECKING:
    from pathlib import Path

    from phantom.darkroom.pipeline import PipelineResult
    from phantom.models import CommitAuthor, PublishingConfig

logger = structlog.get_logger()

MAX_PUSH_RETRIES = 3


@dataclass
class CommitInfo:
    """Information about a git commit to be made."""

    message: str
    author_name: str
    author_email: str
    files: list[str] = field(default_factory=list)


@dataclass
class PublishResult:
    """Result of git publish operations."""

    committed: bool
    pushed: bool
    commit_sha: str | None = None
    files_added: int = 0
    files_removed: int = 0
    error: str | None = None


def compose_commit_message(
    project_name: str,
    pipeline_results: list[PipelineResult],
    publishing_config: PublishingConfig,
    readme_updated: bool = False,
    force: bool = False,
    trigger_source: str | None = None,
) -> str:
    """Build a descriptive commit message.

    Format:
        docs(screenshots): update via Phantom [skip ci]

        Project: my-project
        Changed: 3 | Unchanged: 2 | Failed: 0 | Total: 5
        Phantom: v0.1.0
        Trigger: cli

        Changed captures:
          - dashboard (5.2% diff)
          - settings (new)

        [skip ci]
    """
    changed = [r for r in pipeline_results if r.changed]
    unchanged = [r for r in pipeline_results if not r.changed]
    # Failed captures aren't in pipeline_results (they're filtered out earlier)

    # Use custom message template or default
    subject = publishing_config.commit_message

    # Append CI skip tag to subject line
    ci_tag = publishing_config.ci_skip_tag
    if ci_tag and ci_tag not in subject:
        subject = f"{subject} {ci_tag}"

    lines = [subject, ""]
    lines.append(f"Project: {project_name}")
    lines.append(
        f"Changed: {len(changed)} | Unchanged: {len(unchanged)} | Total: {len(pipeline_results)}"
    )
    lines.append(f"Phantom: v{__version__}")
    if trigger_source:
        lines.append(f"Trigger: {trigger_source}")

    # Diff details for changed captures
    if changed:
        lines.append("")
        lines.append("Changed captures:")
        for r in changed:
            diff_info = r.stage_results.get("diff")
            if diff_info and diff_info.metadata:
                pct = diff_info.metadata.get("diff_pct", "?")
                lines.append(f"  - {r.capture_id} ({pct}% diff)")
            else:
                lines.append(f"  - {r.capture_id} (new)")

    if unchanged:
        lines.append("")
        lines.append("Unchanged captures:")
        for r in unchanged:
            lines.append(f"  - {r.capture_id}")

    if readme_updated:
        lines.append("")
        lines.append("README sentinels updated.")

    if force:
        lines.append("")
        lines.append("Force mode: committed regardless of diff threshold.")

    return "\n".join(lines)


async def git_add(repo_dir: Path, files: list[str]) -> None:
    """Stage files for commit."""
    if not files:
        return

    result = await run_command(
        "git",
        "add",
        "--",
        *files,
        cwd=repo_dir,
        timeout=30,
    )
    if result.returncode != 0:
        raise GitOperationError(f"git add failed: {result.stderr[:500]}")


async def git_commit(
    repo_dir: Path,
    message: str,
    author: CommitAuthor,
) -> str | None:
    """Create a commit. Returns the commit SHA or None if nothing to commit."""
    # Check if there are staged changes
    status = await run_command(
        "git",
        "diff",
        "--cached",
        "--quiet",
        cwd=repo_dir,
        timeout=10,
    )
    if status.returncode == 0:
        # No staged changes
        logger.info("git_nothing_to_commit")
        return None

    result = await run_command(
        "git",
        "commit",
        "-m",
        message,
        "--author",
        f"{author.name} <{author.email}>",
        cwd=repo_dir,
        timeout=30,
    )
    if result.returncode != 0:
        raise GitOperationError(f"git commit failed: {result.stderr[:500]}")

    # Extract SHA from output
    sha_result = await run_command(
        "git",
        "rev-parse",
        "HEAD",
        cwd=repo_dir,
        timeout=5,
    )
    sha = sha_result.stdout.strip() if sha_result.returncode == 0 else None

    logger.info("git_committed", sha=sha)
    return sha


async def git_push(repo_dir: Path, branch: str) -> None:
    """Push commits to the remote."""
    result = await run_command(
        "git",
        "push",
        "origin",
        branch,
        cwd=repo_dir,
        timeout=60,
    )
    if result.returncode != 0:
        if "rejected" in result.stderr or "non-fast-forward" in result.stderr:
            raise PushConflictError(f"Push rejected (likely conflict): {result.stderr[:500]}")
        raise GitOperationError(f"git push failed: {result.stderr[:500]}")

    logger.info("git_pushed", branch=branch)


async def git_push_with_retry(
    repo_dir: Path,
    branch: str,
    max_retries: int = MAX_PUSH_RETRIES,
) -> None:
    """Push with conflict retry: pull --rebase then retry push.

    Args:
        repo_dir: Path to the git repository.
        branch: Branch to push.
        max_retries: Maximum number of push attempts.
    """
    for attempt in range(1, max_retries + 1):
        try:
            await git_push(repo_dir, branch)
            return
        except PushConflictError:
            if attempt >= max_retries:
                logger.error(
                    "git_push_exhausted_retries",
                    attempts=max_retries,
                    branch=branch,
                )
                raise

            logger.warning(
                "git_push_conflict_retry",
                attempt=attempt,
                max_retries=max_retries,
            )

            # Pull with rebase
            rebase_result = await run_command(
                "git",
                "pull",
                "--rebase",
                "origin",
                branch,
                cwd=repo_dir,
                timeout=60,
            )
            if rebase_result.returncode != 0:
                raise GitOperationError(
                    f"git pull --rebase failed during push retry: {rebase_result.stderr[:500]}"
                ) from None


async def preflight_check(repo_dir: Path, branch: str) -> None:
    """Validate the repository before publishing.

    Checks:
    - Working directory is clean (no unstaged changes)
    - We're on the correct branch
    - Remote is reachable
    """
    # Check for unstaged changes
    status_result = await run_command("git", "diff", "--quiet", cwd=repo_dir, timeout=10)
    if status_result.returncode != 0:
        logger.warning("preflight_dirty_workdir")

    # Check current branch
    branch_result = await run_command(
        "git", "rev-parse", "--abbrev-ref", "HEAD", cwd=repo_dir, timeout=5
    )
    current_branch = branch_result.stdout.strip()
    if current_branch != branch:
        logger.warning(
            "preflight_branch_mismatch",
            expected=branch,
            actual=current_branch,
        )

    # Check remote is reachable (best-effort)
    remote_result = await run_command(
        "git", "ls-remote", "--exit-code", "origin", cwd=repo_dir, timeout=15
    )
    if remote_result.returncode != 0:
        logger.warning("preflight_remote_unreachable")


async def find_stale_screenshots(
    repo_dir: Path,
    output_dir: str,
    known_outputs: set[str],
) -> list[str]:
    """Find screenshot files in the output directory not referenced by any capture.

    Args:
        repo_dir: Repository root.
        output_dir: Relative path to the screenshot output directory.
        known_outputs: Set of relative output paths from current captures.

    Returns:
        List of relative paths to stale files.
    """
    target = repo_dir / output_dir
    if not target.is_dir():
        return []

    stale: list[str] = []
    for f in target.iterdir():
        if f.is_file() and f.suffix in (".png", ".webp", ".jpg", ".jpeg"):
            rel_path = str(f.relative_to(repo_dir))
            if rel_path not in known_outputs:
                stale.append(rel_path)

    return stale


async def remove_stale_files(repo_dir: Path, stale_files: list[str]) -> int:
    """Remove stale screenshot files and stage the removals.

    Returns the number of files removed.
    """
    if not stale_files:
        return 0

    removed = 0
    for rel_path in stale_files:
        full_path = repo_dir / rel_path
        if full_path.exists():
            full_path.unlink()
            removed += 1
            logger.info("stale_removed", path=rel_path)

    if removed > 0:
        result = await run_command(
            "git",
            "add",
            "--all",
            "--",
            *[str(repo_dir / f) for f in stale_files],
            cwd=repo_dir,
            timeout=10,
        )
        if result.returncode != 0:
            logger.warning("stale_staging_failed", stderr=result.stderr[:200])

    return removed


async def publish(
    repo_dir: Path,
    pipeline_results: list[PipelineResult],
    publishing_config: PublishingConfig,
    project_name: str,
    readme_updated: bool = False,
    force: bool = False,
    dry_run: bool = False,
    trigger_source: str | None = None,
) -> PublishResult:
    """Execute the full publish workflow: add, commit, push.

    Args:
        repo_dir: Path to the git repository root.
        pipeline_results: Results from the darkroom pipeline.
        publishing_config: Publishing configuration from manifest.
        project_name: Project identifier.
        readme_updated: Whether the README was modified.
        force: Commit even if all captures are unchanged.
        dry_run: Log what would happen but don't modify git.
        trigger_source: What triggered this run (cli, webhook, schedule).

    Returns:
        PublishResult with commit details.
    """
    # Determine which files to commit
    changed_results = [r for r in pipeline_results if r.changed or force]

    if not changed_results and not readme_updated:
        logger.info("publish_skip_no_changes")
        return PublishResult(committed=False, pushed=False)

    # Build file list
    files_to_add: list[str] = []
    for r in changed_results:
        rel_path = str(r.output_path.relative_to(repo_dir))
        files_to_add.append(rel_path)

    # Include README if updated
    readme_candidates = ["README.md", "readme.md", "README.rst", "README"]
    for candidate in readme_candidates:
        readme_path = repo_dir / candidate
        if readme_path.exists() and readme_updated:
            files_to_add.append(candidate)
            break

    message = compose_commit_message(
        project_name,
        pipeline_results,
        publishing_config,
        readme_updated=readme_updated,
        force=force,
        trigger_source=trigger_source,
    )

    if dry_run:
        logger.info(
            "publish_dry_run",
            files=files_to_add,
            message_preview=message.split("\n")[0],
        )
        return PublishResult(
            committed=False,
            pushed=False,
            files_added=len(files_to_add),
        )

    # Stage files
    await git_add(repo_dir, files_to_add)

    # Commit
    sha = await git_commit(repo_dir, message, publishing_config.commit_author)
    if sha is None:
        return PublishResult(committed=False, pushed=False)

    # Push with retry
    pushed = False
    try:
        await git_push_with_retry(
            repo_dir,
            publishing_config.branch,
            max_retries=MAX_PUSH_RETRIES,
        )
        pushed = True
    except Exception as e:
        logger.warning("push_failed", error=str(e))
        return PublishResult(
            committed=True,
            pushed=False,
            commit_sha=sha,
            files_added=len(files_to_add),
            error=str(e),
        )

    return PublishResult(
        committed=True,
        pushed=pushed,
        commit_sha=sha,
        files_added=len(files_to_add),
    )
