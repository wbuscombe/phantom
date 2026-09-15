"""release.yml "Create GitHub Release" step: handling of the pushed tag name.

Git accepts tag names containing shell metacharacters, and any ``v*`` tag push starts the
release workflow, so the tag must reach the shell as data (the runner's own
``GITHUB_REF_NAME``), never as script text.

The step's ``run:`` script is read from the workflow file, any expression in it is rendered
the way the runner renders it before the shell sees the script, and the result is executed
with ``bash -e`` (how the Actions runner executes a Linux step with no ``shell:`` set), with
``gh`` replaced by a stub that only records its arguments. Nothing touches the network.

* Behaviour: hostile but valid tag names reach ``gh`` verbatim and run nothing.
* Positive control: the same tag names do execute when rendered into the script text the
  way the old ``${{ github.ref_name }}`` interpolation did, so the harness can see an
  injection.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
RELEASE_JOB = "github-release"
RELEASE_STEP = "Create GitHub Release"
SENTINEL = "@SENTINEL@"
EXPRESSION = re.compile(r"\$\{\{\s*(.*?)\s*\}\}", re.DOTALL)
INTERPOLATED_SCRIPT = 'gh release create "${{ github.ref_name }}" --generate-notes\n'

_RECORDING_STUB = """#!/bin/sh
printf '%s\\0' "$@" >> "$PHANTOM_TEST_CALLS/gh"
"""

HOSTILE_TAGS = [
    pytest.param(f"v1.0.0$(>{SENTINEL})", id="subst"),
    pytest.param(f"v1.0.0`>{SENTINEL}`", id="backtick"),
    pytest.param(f'v1.0.0";>{SENTINEL};"', id="dquote-breakout"),
    pytest.param(f'v1.0.0"&&>{SENTINEL}||"', id="dquote-breakout-and"),
]


@dataclass
class ReleaseRun:
    returncode: int
    output: str
    gh: list[str] | None


def _release_step() -> dict[str, Any]:
    workflow = YAML(typ="safe").load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"][RELEASE_JOB]["steps"]
    matches = [step for step in steps if step.get("name") == RELEASE_STEP]
    assert len(matches) == 1, f"expected exactly one {RELEASE_STEP!r} step"
    step: dict[str, Any] = matches[0]
    return step


def _render(script: str, tag: str) -> str:
    """Substitute tag-derived expressions into the script text, as the runner does."""
    values = {"github.ref_name": tag, "github.ref": f"refs/tags/{tag}"}

    def substitute(match: re.Match[str]) -> str:
        assert match.group(1) in values, f"unhandled expression {match.group(0)!r}"
        return values[match.group(1)]

    return EXPRESSION.sub(substitute, script)


def _arm(tag: str, sentinel: Path) -> str:
    """Point a payload's redirection at ``sentinel`` (a path that needs no quoting)."""
    assert re.fullmatch(r"[A-Za-z0-9._/-]+", str(sentinel)), sentinel
    return tag.replace(SENTINEL, str(sentinel))


def _run(tmp_path: Path, tag: str, script: str) -> ReleaseRun:
    """Render ``script`` for a push of ``tag`` and execute it against a recording ``gh``."""
    bash = shutil.which("bash")
    assert bash is not None, "bash is required to execute the workflow step"
    bin_dir, calls = tmp_path / "bin", tmp_path / "calls"
    bin_dir.mkdir()
    calls.mkdir()
    stub = bin_dir / "gh"
    stub.write_text(_RECORDING_STUB)
    stub.chmod(0o755)
    script_path = tmp_path / "step.sh"
    script_path.write_text(_render(script, tag))
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "PHANTOM_TEST_CALLS": str(calls),
        "GH_TOKEN": "test-token",
        "GITHUB_REF": f"refs/tags/{tag}",
        "GITHUB_REF_NAME": tag,
    }
    proc = subprocess.run(
        [bash, "-e", str(script_path)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    recorded = calls / "gh"
    gh = recorded.read_text(encoding="utf-8").split("\0")[:-1] if recorded.exists() else None
    return ReleaseRun(proc.returncode, proc.stdout + proc.stderr, gh)


def test_ordinary_tag_creates_the_release(tmp_path: Path) -> None:
    run = _run(tmp_path, "v0.5.0", _release_step()["run"])
    assert run.returncode == 0, run.output
    assert run.gh == ["release", "create", "v0.5.0", "--generate-notes"]


@pytest.mark.parametrize("tag", HOSTILE_TAGS)
def test_payload_is_a_valid_tag_name(tmp_path: Path, tag: str) -> None:
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is required to check tag-name validity")
    armed = _arm(tag, tmp_path / "sentinel")
    check = subprocess.run(
        [git, "check-ref-format", f"refs/tags/{armed}"], capture_output=True, check=False
    )
    assert check.returncode == 0, f"git rejects {armed!r}, so no push could deliver it"


@pytest.mark.parametrize("tag", HOSTILE_TAGS)
def test_hostile_tag_reaches_gh_verbatim(tmp_path: Path, tag: str) -> None:
    sentinel = tmp_path / "sentinel"
    armed = _arm(tag, sentinel)
    run = _run(tmp_path, armed, _release_step()["run"])
    assert not sentinel.exists(), f"tag {armed!r} executed a command: {run.output}"
    assert run.returncode == 0, run.output
    assert run.gh == ["release", "create", armed, "--generate-notes"]


@pytest.mark.parametrize("tag", HOSTILE_TAGS)
def test_positive_control_interpolated_tag_executes(tmp_path: Path, tag: str) -> None:
    sentinel = tmp_path / "sentinel"
    _run(tmp_path, _arm(tag, sentinel), INTERPOLATED_SCRIPT)
    assert sentinel.exists(), "payload did not execute; the harness cannot see an injection"
