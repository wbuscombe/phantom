"""CONTRACT.md §2 — Config contract (`.phantom.yml` schema).

Verifies required/optional fields, defaults, the `phantom: "1"` version gate,
and — most importantly for forward-compatibility — that unknown keys are
IGNORED and NEVER fatal, at both the top level and nested levels.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from phantom.exceptions import ManifestValidationError
from phantom.models import PhantomManifest


def _minimal() -> dict[str, Any]:
    """A minimal valid manifest as a plain dict."""
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
        "captures": [
            {"id": "home", "name": "Home", "output": "docs/screenshots/home.png"},
        ],
    }


# ── Required fields ───────────────────────────────────


class TestRequiredFields:
    def test_minimal_manifest_parses(self) -> None:
        m = PhantomManifest.model_validate(_minimal())
        assert m.project == "demo-app"
        assert m.setup.type == "web"
        assert len(m.captures) == 1

    @pytest.mark.parametrize("missing", ["phantom", "project", "name", "setup", "captures"])
    def test_missing_required_field_is_fatal(self, missing: str) -> None:
        data = _minimal()
        del data[missing]
        with pytest.raises((ValidationError, ManifestValidationError)):
            PhantomManifest.model_validate(data)

    def test_at_least_one_capture_required(self) -> None:
        data = _minimal()
        data["captures"] = []
        with pytest.raises(ValidationError):
            PhantomManifest.model_validate(data)


# ── Schema version gate ───────────────────────────────


class TestSchemaVersion:
    def test_version_1_accepted(self) -> None:
        PhantomManifest.model_validate(_minimal())

    @pytest.mark.parametrize("version", ["2", "1.0", "0", "v1"])
    def test_non_1_version_is_fatal(self, version: str) -> None:
        data = _minimal()
        data["phantom"] = version
        with pytest.raises(ManifestValidationError):
            PhantomManifest.model_validate(data)


# ── Optional fields + defaults ────────────────────────


class TestDefaults:
    def test_optional_collections_default_empty(self) -> None:
        m = PhantomManifest.model_validate(_minimal())
        assert m.fixtures == []
        assert m.triggers == []
        assert m.capture_defaults is None
        assert m.groups is None

    def test_processing_defaults(self) -> None:
        m = PhantomManifest.model_validate(_minimal())
        assert m.processing.format == "png"
        assert m.processing.optimize is True

    def test_publishing_defaults(self) -> None:
        m = PhantomManifest.model_validate(_minimal())
        assert m.publishing.branch == "main"
        assert m.publishing.strategy == "direct"

    def test_ready_check_timeout_default(self) -> None:
        # Health contract cross-check: default readiness timeout is declared.
        m = PhantomManifest.model_validate(_minimal())
        assert m.setup.run.ready_check.timeout == 30


# ── Forward compatibility: unknown keys ignored, never fatal ──


class TestUnknownKeysIgnored:
    def test_unknown_top_level_key_ignored(self) -> None:
        data = _minimal()
        data["future_top_level_feature"] = {"anything": [1, 2, 3]}
        m = PhantomManifest.model_validate(data)
        assert m.project == "demo-app"
        assert not hasattr(m, "future_top_level_feature")

    def test_unknown_nested_setup_key_ignored(self) -> None:
        data = _minimal()
        data["setup"]["future_setup_field"] = "ignored"
        data["setup"]["run"]["future_run_field"] = True
        m = PhantomManifest.model_validate(data)
        assert m.setup.type == "web"

    def test_unknown_nested_capture_key_ignored(self) -> None:
        data = _minimal()
        data["captures"][0]["future_capture_field"] = {"x": 1}
        m = PhantomManifest.model_validate(data)
        assert m.captures[0].id == "home"

    def test_unknown_ready_check_key_ignored(self) -> None:
        data = _minimal()
        data["setup"]["run"]["ready_check"]["future_probe"] = "graphql"
        m = PhantomManifest.model_validate(data)
        assert m.setup.run.ready_check.type == "http"

    def test_unknown_processing_key_ignored(self) -> None:
        data = _minimal()
        data["processing"] = {"format": "png", "future_stage": {"enabled": True}}
        m = PhantomManifest.model_validate(data)
        assert m.processing.format == "png"

    def test_unknown_key_is_never_fatal_across_a_full_manifest(self) -> None:
        # Sprinkle unknown keys everywhere; parsing must still succeed.
        data = copy.deepcopy(_minimal())
        data["capture_defaults"] = {"theme": "dark", "future_default": 1}
        data["publishing"] = {"strategy": "pr", "future_publish": "x"}
        data["captures"][0]["future"] = "y"
        data["setup"]["future"] = "z"
        m = PhantomManifest.model_validate(data)
        assert m.publishing.strategy == "pr"
        assert m.capture_defaults is not None
        assert m.capture_defaults.theme == "dark"
