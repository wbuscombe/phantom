"""CONTRACT.md §4 — Artifact contract.

Screenshots are written to project-root-relative ``output:`` paths; by
convention they live under ``docs/screenshots/`` (the directory the CI smoke
job collects). Paths may never be absolute or escape the project root. Formats
are ``png`` (default) or ``webp``.
"""

from __future__ import annotations

from typing import Any

import pytest

from phantom.contract import DEFAULT_ARTIFACT_DIR
from phantom.exceptions import ManifestValidationError
from phantom.models import PhantomManifest

SUPPORTED_FORMATS = {"png", "webp"}


def _minimal_with_output(output: str) -> dict[str, Any]:
    return {
        "phantom": "1",
        "project": "demo-app",
        "name": "Demo App",
        "setup": {
            "type": "web",
            "run": {
                "command": "python server.py",
                "ready_check": {"type": "http", "url": "http://localhost:3000"},
            },
        },
        "captures": [{"id": "home", "name": "Home", "output": output}],
    }


def test_default_artifact_dir_constant() -> None:
    assert DEFAULT_ARTIFACT_DIR == "docs/screenshots"


def test_relative_output_under_docs_screenshots_is_accepted() -> None:
    m = PhantomManifest.model_validate(_minimal_with_output("docs/screenshots/home.png"))
    assert m.captures[0].output == "docs/screenshots/home.png"


@pytest.mark.parametrize(
    "bad_output",
    [
        "/etc/passwd.png",
        "/tmp/home.png",
        "../outside.png",
        "docs/../../escape.png",
    ],
)
def test_absolute_or_escaping_output_is_fatal(bad_output: str) -> None:
    with pytest.raises(ManifestValidationError):
        PhantomManifest.model_validate(_minimal_with_output(bad_output))


def test_shipped_captures_write_relative_paths(shipped_manifest: PhantomManifest) -> None:
    for cap in shipped_manifest.captures:
        assert not cap.output.startswith("/")
        assert ".." not in cap.output.split("/")


def test_shipped_captures_use_documented_dir(shipped_manifest: PhantomManifest) -> None:
    # Convention: all shipped fixtures land under DEFAULT_ARTIFACT_DIR.
    for cap in shipped_manifest.captures:
        assert cap.output.startswith(DEFAULT_ARTIFACT_DIR + "/")


def test_capture_format_is_png_or_webp(shipped_manifest: PhantomManifest) -> None:
    # Per-capture override (may be None -> falls back to processing.format).
    for cap in shipped_manifest.captures:
        assert cap.format is None or cap.format in SUPPORTED_FORMATS
    assert shipped_manifest.processing.format in SUPPORTED_FORMATS


def test_output_extension_matches_a_supported_format(shipped_manifest: PhantomManifest) -> None:
    for cap in shipped_manifest.captures:
        assert cap.output.rsplit(".", 1)[-1] in SUPPORTED_FORMATS
