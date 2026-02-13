"""Integration test for package building."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent


@pytest.mark.integration
class TestPackageBuild:
    def test_build_produces_wheel_and_sdist(self, tmp_path: Path) -> None:
        """python -m build should produce both .whl and .tar.gz."""
        # Ensure build module is available
        try:
            import build  # noqa: F401
        except ImportError:
            pytest.skip("'build' package not installed (pip install build)")

        result = subprocess.run(
            [sys.executable, "-m", "build", "--outdir", str(tmp_path)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, f"Build failed:\n{result.stderr}"

        whl_files = list(tmp_path.glob("*.whl"))
        tar_files = list(tmp_path.glob("*.tar.gz"))
        assert len(whl_files) == 1, f"Expected 1 wheel, found {len(whl_files)}"
        assert len(tar_files) == 1, f"Expected 1 sdist, found {len(tar_files)}"

        # Check wheel name contains phantom_docs
        assert "phantom_docs" in whl_files[0].name
