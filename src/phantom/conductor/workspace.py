"""Workspace management — ephemeral directories for capture jobs.

Each job gets an isolated workspace with the following structure:
    {workspace_root}/{project}-{hash}/
        repo/           - Git clone or symlink to local path
        raw/            - Raw captures from runner
        processed/      - Darkroom output
        previous/       - Previous versions (for diff)
"""

from __future__ import annotations

import hashlib
import shutil
import time
from pathlib import Path

import structlog

from phantom.exceptions import WorkspaceError
from phantom.utils.process import run_command

logger = structlog.get_logger()


class Workspace:
    """Manages an ephemeral workspace for a single capture job."""

    def __init__(self, root: Path, project: str) -> None:
        short_hash = hashlib.sha256(f"{project}-{time.time()}".encode()).hexdigest()[:8]
        self.base = root / f"{project}-{short_hash}"
        self.project_dir = self.base / "repo"
        self.raw_dir = self.base / "raw"
        self.processed_dir = self.base / "processed"
        self.previous_dir = self.base / "previous"
        self.project = project

    def create(self) -> None:
        """Create the workspace directory structure."""
        logger.info("workspace_create", path=str(self.base))
        for d in [self.base, self.raw_dir, self.processed_dir, self.previous_dir]:
            d.mkdir(parents=True, exist_ok=True)

    async def clone(self, repo_url: str, ref: str = "HEAD") -> None:
        """Clone a repository into the workspace.

        Args:
            repo_url: Git clone URL (HTTPS or SSH).
            ref: Branch, tag, or commit to checkout.
        """
        logger.info("workspace_clone", repo=repo_url, ref=ref)
        args = ["git", "clone", "--depth", "1"]
        if ref != "HEAD":
            args.extend(["--branch", ref])
        args.extend([repo_url, str(self.project_dir)])

        result = await run_command(*args, timeout=60)
        if result.returncode != 0:
            raise WorkspaceError(f"Git clone failed: {result.stderr[:500]}")

    def use_local(self, local_path: Path) -> None:
        """Use a local directory as the project source (for development/testing).

        Creates a symlink instead of cloning. The original directory is not modified —
        captures and processed outputs go to the workspace's raw/ and processed/ dirs.
        """
        if not local_path.is_dir():
            raise WorkspaceError(f"Local path is not a directory: {local_path}")

        logger.info("workspace_local", path=str(local_path))
        # Symlink so builds happen in the original location
        self.project_dir.symlink_to(local_path.resolve())

    async def fetch_previous_screenshots(
        self, output_paths: list[str], branch: str = "main"
    ) -> dict[str, Path]:
        """Fetch previous versions of screenshots for diff comparison.

        Args:
            output_paths: List of output paths from capture definitions.
            branch: Branch to fetch from.

        Returns:
            Mapping of output path -> local path of previous version.
            Missing files are silently skipped.
        """
        fetched: dict[str, Path] = {}

        for output_path in output_paths:
            dest = self.previous_dir / Path(output_path).name
            result = await run_command(
                "git",
                "show",
                f"{branch}:{output_path}",
                cwd=self.project_dir,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout:
                # git show outputs binary content, but run_command decodes as utf-8.
                # For binary files, we need to use git directly.
                fetch_result = await _fetch_blob(self.project_dir, branch, output_path, dest)
                if fetch_result:
                    fetched[output_path] = dest

        logger.info(
            "previous_fetched",
            total=len(output_paths),
            found=len(fetched),
        )
        return fetched

    def cleanup(self) -> None:
        """Remove the entire workspace directory."""
        if self.base.exists():
            logger.info("workspace_cleanup", path=str(self.base))
            # Unlink symlink first if it exists
            if self.project_dir.is_symlink():
                self.project_dir.unlink()
            shutil.rmtree(self.base, ignore_errors=True)


async def _fetch_blob(repo_dir: Path, branch: str, file_path: str, dest: Path) -> bool:
    """Fetch a single binary blob from git and write to dest."""
    import asyncio

    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "show",
            f"{branch}:{file_path}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=repo_dir,
        )
        stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode == 0 and stdout:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(stdout)
            return True
    except (TimeoutError, OSError):
        pass
    return False
