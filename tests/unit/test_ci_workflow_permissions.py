"""ci.yml token permissions: each job holds only what its own steps use.

CI runs on every push to main and every pull request. Its jobs used to declare no
``permissions:``, so their token scopes came from the repository's default workflow-permissions
setting, which lives outside this file and can be widened without a commit. The workflow level
now grants nothing and each job declares its own block.

These tests read the workflow file. They pin the widening direction, which nothing else catches:
the workflow-static-analysis gate (zizmor, regular persona) reports neither a job-level
``contents: write`` nor a removed workflow-level block while every job still declares its own,
and CI never fails because a job holds more than it uses. A job added to the workflow has to be
added here too, with the grant its steps need.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

EXPECTED_JOB_PERMISSIONS = {
    # actions/checkout
    "lint": {"contents": "read"},
    # actions/checkout
    "test": {"contents": "read"},
    # actions/checkout; zizmor's online lookups read public action repositories, needing no scope
    "workflow-static-analysis": {"contents": "read"},
}


def _workflow() -> dict[str, Any]:
    return YAML(typ="safe").load(CI_WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_level_grants_nothing() -> None:
    workflow = _workflow()
    # An absent block would fall back to the repository default, which lives outside this file.
    assert "permissions" in workflow
    assert workflow["permissions"] == {}


def test_every_job_has_an_expected_grant() -> None:
    assert sorted(_workflow()["jobs"]) == sorted(EXPECTED_JOB_PERMISSIONS)


@pytest.mark.parametrize("job", sorted(EXPECTED_JOB_PERMISSIONS))
def test_job_holds_exactly_the_permissions_its_steps_use(job: str) -> None:
    jobs = _workflow()["jobs"]
    assert job in jobs
    assert jobs[job].get("permissions") == EXPECTED_JOB_PERMISSIONS[job]


@pytest.mark.parametrize("job", sorted(EXPECTED_JOB_PERMISSIONS))
def test_contents_read_is_used_by_a_checkout(job: str) -> None:
    steps = _workflow()["jobs"][job]["steps"]
    assert any(str(step.get("uses", "")).startswith("actions/checkout@") for step in steps)
