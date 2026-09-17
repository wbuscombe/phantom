"""phantom-capture.yml "Run captures" step: the flag vector reaching ``phantom run``.

The step builds its flags conditionally and then invokes ``phantom run``. Before this
test the invocation was ``phantom run $FLAGS``: an unquoted expansion (shellcheck
SC2086) that relied on word splitting to turn one string into several arguments. The
value is composed entirely of literals, so the finding was a correctness issue rather
than an injection one; but the obvious "fix", quoting the string as ``"$FLAGS"``, would
have collapsed every flag into a single argument and broken every consumer run.

This repository's CI never executes the reusable workflow, so that breakage would first
surface on a consumer. The test therefore reads the step's ``run:`` script from the
workflow file, renders its ``${{ inputs.* }}`` expressions the way the runner would, and
executes it verbatim with ``bash -e`` and a ``phantom`` stub that records its argv.
Nothing is installed, nothing is captured and nothing touches the network.

* Compatibility: for every combination of the four boolean inputs, ``phantom run``
  receives exactly the argument vector the word-splitting form produced.
* Anti-inertness: ``test_collapsed_expansion_is_detected`` renders the naive quoting fix
  (``"${FLAGS[*]}"``, one joined word) and shows the harness catches the collapse.
"""

from __future__ import annotations

import itertools
import os
import re
import shutil
import subprocess
import tempfile
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML

REPO_ROOT = Path(__file__).resolve().parents[2]
CAPTURE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "phantom-capture.yml"
CAPTURE_STEP = "Run captures"
BASE_FLAGS = ["--project", ".", "--skip-publish", "--fail-on-quality-error"]
INPUTS = ("force-publish", "ai-auto", "ai-analyst", "ai-document")
EXPRESSION = re.compile(r"\$\{\{\s*inputs\.([a-z-]+)\s*\}\}")

_RECORDING_STUB = """#!/bin/sh
printf '%s\\0' "$@" >> "$PHANTOM_TEST_CALLS/phantom"
"""


def _load(path: Path) -> Any:
    return YAML(typ="safe").load(path.read_text(encoding="utf-8"))


@cache
def _capture_step() -> dict[str, Any]:
    steps = _load(CAPTURE_WORKFLOW)["jobs"]["capture"]["steps"]
    matches = [step for step in steps if step.get("name") == CAPTURE_STEP]
    assert len(matches) == 1, f"expected exactly one {CAPTURE_STEP!r} step"
    step: dict[str, Any] = matches[0]
    return step


def _render(script: str, selected: dict[str, bool]) -> str:
    """Substitute the boolean inputs as the runner does, leaving the rest of the bytes."""

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        assert name in selected, f"unexpected input {name!r} in the step script"
        return "true" if selected[name] else "false"

    rendered = EXPRESSION.sub(replace, script)
    assert "${{" not in rendered, "an expression was left unrendered"
    return rendered


def _recorded(path: Path) -> list[str] | None:
    if not path.exists():
        return None
    return path.read_bytes().decode("utf-8", "surrogateescape").split("\0")[:-1]


def _run(tmp_path: Path, script: str) -> tuple[int, str, list[str] | None]:
    """Execute ``script`` against a recording ``phantom`` stub; return argv it saw."""
    bash = shutil.which("bash")
    assert bash is not None, "bash is required to execute the workflow step"
    work = Path(tempfile.mkdtemp(dir=tmp_path))
    bin_dir, calls = work / "bin", work / "calls"
    bin_dir.mkdir()
    calls.mkdir()
    stub = bin_dir / "phantom"
    stub.write_text(_RECORDING_STUB)
    stub.chmod(0o755)
    script_path = work / "step.sh"
    script_path.write_text(script)
    proc = subprocess.run(
        [bash, "-e", str(script_path)],
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(work),
            "PHANTOM_TEST_CALLS": str(calls),
            "PHANTOM_MODE": "1",
        },
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr, _recorded(calls / "phantom")


def _expected(selected: dict[str, bool]) -> list[str]:
    """The argument vector the word-splitting form produced, by the step's own branching."""
    flags = ["run", *BASE_FLAGS]
    if selected["force-publish"]:
        flags.append("--force")
    if selected["ai-auto"]:
        flags.append("--ai-auto")
    else:
        if selected["ai-analyst"]:
            flags.append("--ai-analyst")
        if selected["ai-document"]:
            flags.append("--ai-document")
    return flags


COMBINATIONS = [
    pytest.param(
        dict(zip(INPUTS, values, strict=True)),
        id="-".join(name for name, value in zip(INPUTS, values, strict=True) if value) or "none",
    )
    for values in itertools.product((False, True), repeat=len(INPUTS))
]


# ── Compatibility: each combination composes its exact argument vector ──


@pytest.mark.parametrize("selected", COMBINATIONS)
def test_flags_reach_phantom_as_separate_arguments(
    tmp_path: Path, selected: dict[str, bool]
) -> None:
    returncode, output, argv = _run(tmp_path, _render(_capture_step()["run"], selected))
    assert returncode == 0, output
    assert argv == _expected(selected), output


# ── Anti-inertness: the harness catches a collapsed expansion ──


def test_collapsed_expansion_is_detected(tmp_path: Path) -> None:
    """The naive SC2086 fix joins the flags into one word; the assertion above rejects it."""
    selected = dict.fromkeys(INPUTS, False)
    script = _render(_capture_step()["run"], selected)
    assert '"${FLAGS[@]}"' in script, "the step no longer expands the array element-wise"
    collapsed = script.replace('"${FLAGS[@]}"', '"${FLAGS[*]}"')
    returncode, output, argv = _run(tmp_path, collapsed)
    assert returncode == 0, output
    assert argv == ["run", " ".join(BASE_FLAGS)], output
    assert argv != _expected(selected)


# ── Structure: no unquoted expansion is left in the step ──


def test_step_has_no_unquoted_flag_expansion() -> None:
    script = _capture_step()["run"]
    assert re.search(r"(?<!\")\$\{?FLAGS\b(?!\[@\]\"|\[\*\]\")", script) is None, script
    assert 'phantom run "${FLAGS[@]}"' in script
