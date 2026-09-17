"""release.yml token permissions: each job holds only what its own steps use.

The release workflow runs on any ``v*`` tag push. Its token scopes used to be granted at the
workflow level (``contents: write`` and ``id-token: write``), so every job held both, including
``build``, which installs tooling from PyPI and runs the freshly built package. The workflow
level now grants nothing and each job declares its own ``permissions:``.

These tests read the workflow file. They do not run a release and cannot prove the grants are
sufficient at runtime. They pin both directions of drift, which CI would not otherwise notice:

* Widening: no job holds a scope beyond the one its steps use, and nothing is granted at the
  workflow level for a job to inherit.
* Narrowing: the two write scopes the release path needs are still present, in the jobs whose
  steps use them. Dropping either would otherwise surface only as a failed release.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"

EXPECTED_JOB_PERMISSIONS = {
    # actions/checkout
    "build": {"contents": "read"},
    # pypa/gh-action-pypi-publish via Trusted Publishing (OIDC) and PEP 740 attestations
    "publish": {"id-token": "write"},
    # gh release create (and actions/checkout)
    "github-release": {"contents": "write"},
}


def _workflow() -> dict[str, Any]:
    return YAML(typ="safe").load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))


def _steps(job: str) -> list[dict[str, Any]]:
    return _workflow()["jobs"][job]["steps"]


def test_workflow_level_grants_nothing() -> None:
    workflow = _workflow()
    # An absent block would fall back to the repository default, which lives outside this file.
    assert "permissions" in workflow
    assert workflow["permissions"] == {}


def test_every_job_declares_its_own_permissions() -> None:
    undeclared = [name for name, job in _workflow()["jobs"].items() if "permissions" not in job]
    assert undeclared == []


@pytest.mark.parametrize("job", sorted(EXPECTED_JOB_PERMISSIONS))
def test_job_holds_exactly_the_permissions_its_steps_use(job: str) -> None:
    jobs = _workflow()["jobs"]
    assert job in jobs
    assert jobs[job]["permissions"] == EXPECTED_JOB_PERMISSIONS[job]


def test_publish_uses_trusted_publishing_so_needs_id_token() -> None:
    publishers = [
        step
        for step in _steps("publish")
        if str(step.get("uses", "")).startswith("pypa/gh-action-pypi-publish@")
    ]
    assert len(publishers) == 1
    # The action takes the OIDC (id-token) path only when no password is supplied. If a
    # password is ever added, id-token: write is no longer the grant this job needs.
    assert "password" not in (publishers[0].get("with") or {})


def test_github_release_creates_the_release_so_needs_contents_write() -> None:
    scripts = [str(step.get("run", "")) for step in _steps("github-release")]
    assert any("gh release create" in script for script in scripts)
