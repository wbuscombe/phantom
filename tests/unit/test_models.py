"""Tests for Phantom manifest parsing and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from phantom.exceptions import ManifestValidationError
from phantom.models import (
    CaptureDefaults,
    CaptureDefinition,
    PhantomManifest,
    ResolvedCapture,
    Viewport,
    load_manifest,
)

MANIFESTS = Path(__file__).parent.parent / "fixtures" / "manifests"


# ── Loading valid manifests ───────────────────────────


class TestValidManifests:
    def test_load_valid_web(self) -> None:
        m = load_manifest(MANIFESTS / "valid-web.yml")
        assert m.project == "test-app"
        assert m.name == "Test Application"
        assert m.phantom == "1"
        assert m.setup.type == "web"

    def test_load_minimal(self) -> None:
        m = load_manifest(MANIFESTS / "minimal.yml")
        assert m.project == "minimal-app"
        assert len(m.captures) == 1
        assert m.captures[0].id == "home"
        # Defaults should be applied
        assert m.processing.format == "png"
        assert m.processing.border.style == "drop-shadow"
        assert m.publishing.branch == "main"

    def test_load_valid_tui(self) -> None:
        m = load_manifest(MANIFESTS / "valid-tui.yml")
        assert m.setup.type == "tui"
        assert m.tui is not None
        assert m.tui.terminal.width == 120
        assert m.tui.renderer == "silicon"

    def test_captures_parsed(self) -> None:
        m = load_manifest(MANIFESTS / "valid-web.yml")
        assert len(m.captures) == 5
        ids = [c.id for c in m.captures]
        assert ids == ["dashboard", "detail-view", "settings", "mobile-view", "skipped-capture"]

    def test_capture_actions_parsed(self) -> None:
        m = load_manifest(MANIFESTS / "valid-web.yml")
        detail = next(c for c in m.captures if c.id == "detail-view")
        assert len(detail.actions) == 3
        assert detail.actions[0].type == "click"
        assert detail.actions[1].type == "wait_for"
        assert detail.actions[2].type == "wait"

    def test_fixtures_parsed(self) -> None:
        m = load_manifest(MANIFESTS / "valid-web.yml")
        assert len(m.fixtures) == 3
        assert m.fixtures[0].type == "script"
        assert m.fixtures[1].type == "http"
        assert m.fixtures[2].type == "file_copy"

    def test_groups_parsed(self) -> None:
        m = load_manifest(MANIFESTS / "valid-web.yml")
        assert m.groups is not None
        assert m.get_group("hero") == ["dashboard", "detail-view"]
        assert m.get_group("mobile") == ["mobile-view"]

    def test_processing_defaults(self) -> None:
        m = load_manifest(MANIFESTS / "minimal.yml")
        assert m.processing.optimize is True
        assert m.processing.max_width == 2800
        assert m.processing.border.style == "drop-shadow"
        assert m.processing.border.shadow_blur == 24
        assert m.processing.diff.enabled is True
        assert m.processing.diff.threshold == 0.95
        assert m.processing.diff.algorithm == "ssim"

    def test_publishing_defaults(self) -> None:
        m = load_manifest(MANIFESTS / "minimal.yml")
        assert m.publishing.commit_author.name == "Phantom Bot"
        assert m.publishing.ci_skip_tag == "[skip ci]"
        assert m.publishing.strategy == "direct"
        assert m.publishing.cleanup_stale is True

    def test_capture_skip_flag(self) -> None:
        m = load_manifest(MANIFESTS / "valid-web.yml")
        skipped = next(c for c in m.captures if c.id == "skipped-capture")
        assert skipped.skip is True

    def test_capture_depends_on(self) -> None:
        m = load_manifest(MANIFESTS / "valid-web.yml")
        detail = next(c for c in m.captures if c.id == "detail-view")
        assert detail.depends_on == "dashboard"

    def test_capture_parallel(self) -> None:
        m = load_manifest(MANIFESTS / "valid-web.yml")
        settings = next(c for c in m.captures if c.id == "settings")
        assert settings.parallel is True

    def test_ready_check_parsed(self) -> None:
        m = load_manifest(MANIFESTS / "valid-web.yml")
        rc = m.setup.run.ready_check
        assert rc.type == "http"
        assert rc.url == "http://localhost:3456"
        assert rc.timeout == 30

    def test_tui_ready_check_stdout_match(self) -> None:
        m = load_manifest(MANIFESTS / "valid-tui.yml")
        rc = m.setup.run.ready_check
        assert rc.type == "stdout_match"
        assert rc.pattern == "Ready"


# ── Invalid manifests ─────────────────────────────────


class TestInvalidManifests:
    def test_missing_project(self) -> None:
        with pytest.raises(ValidationError):
            load_manifest(MANIFESTS / "invalid-missing-project.yml")

    def test_duplicate_capture_ids(self) -> None:
        with pytest.raises(ManifestValidationError, match="Duplicate capture IDs"):
            load_manifest(MANIFESTS / "invalid-duplicate-ids.yml")

    def test_bad_action_missing_selector(self) -> None:
        with pytest.raises(ValidationError, match="click action requires"):
            load_manifest(MANIFESTS / "invalid-bad-action.yml")

    def test_escape_path(self) -> None:
        with pytest.raises(ManifestValidationError, match="not contain '\\.\\.'"):
            load_manifest(MANIFESTS / "invalid-escape-path.yml")

    def test_circular_dependencies(self) -> None:
        with pytest.raises(ManifestValidationError, match="Circular dependency"):
            load_manifest(MANIFESTS / "invalid-circular-deps.yml")

    def test_bad_group_reference(self) -> None:
        with pytest.raises(ManifestValidationError, match="nonexistent-capture"):
            load_manifest(MANIFESTS / "invalid-bad-group.yml")

    def test_nonexistent_file(self) -> None:
        from phantom.exceptions import ManifestNotFoundError

        with pytest.raises(ManifestNotFoundError):
            load_manifest("/nonexistent/path.yml")


# ── Capture resolution ────────────────────────────────


class TestCaptureResolution:
    def test_resolve_with_defaults(self) -> None:
        defaults = CaptureDefaults(
            viewport=Viewport(width=1280, height=800),
            theme="dark",
            device_scale=2,
            wait_after_actions=500,
            timeout=15,
        )
        cap = CaptureDefinition(
            id="test",
            name="Test",
            output="docs/test.png",
        )
        resolved = cap.resolve(defaults)
        assert resolved.viewport.width == 1280
        assert resolved.theme == "dark"
        assert resolved.device_scale == 2
        assert resolved.wait_after_actions == 500
        assert resolved.timeout == 15

    def test_resolve_override_viewport(self) -> None:
        defaults = CaptureDefaults(viewport=Viewport(width=1280, height=800))
        cap = CaptureDefinition(
            id="mobile",
            name="Mobile",
            output="docs/mobile.png",
            viewport=Viewport(width=390, height=844),
        )
        resolved = cap.resolve(defaults)
        assert resolved.viewport.width == 390
        assert resolved.viewport.height == 844

    def test_resolve_override_theme(self) -> None:
        defaults = CaptureDefaults(theme="dark")
        cap = CaptureDefinition(
            id="light",
            name="Light",
            output="docs/light.png",
            theme="light",
        )
        resolved = cap.resolve(defaults)
        assert resolved.theme == "light"

    def test_resolve_no_defaults(self) -> None:
        cap = CaptureDefinition(
            id="bare",
            name="Bare",
            output="docs/bare.png",
        )
        resolved = cap.resolve(None)
        # Should get hardcoded fallbacks
        assert resolved.viewport.width == 1280
        assert resolved.viewport.height == 800
        assert resolved.theme == "dark"
        assert resolved.device_scale == 2

    def test_resolve_alt_text_falls_back_to_description(self) -> None:
        cap = CaptureDefinition(
            id="desc",
            name="Desc",
            description="Some description",
            output="docs/desc.png",
        )
        resolved = cap.resolve(None)
        assert resolved.alt_text == "Some description"

    def test_resolve_all_from_manifest(self) -> None:
        m = load_manifest(MANIFESTS / "valid-web.yml")
        resolved = m.resolve_captures()
        assert len(resolved) == 5
        assert all(isinstance(r, ResolvedCapture) for r in resolved)

        # Dashboard overrides viewport
        dashboard = resolved[0]
        assert dashboard.viewport.width == 1440
        assert dashboard.viewport.height == 900

        # Mobile overrides viewport
        mobile = next(r for r in resolved if r.id == "mobile-view")
        assert mobile.viewport.width == 390


# ── Action validation ─────────────────────────────────


class TestActionValidation:
    def test_click_with_selector(self) -> None:
        m = load_manifest(MANIFESTS / "valid-web.yml")
        detail = next(c for c in m.captures if c.id == "detail-view")
        click_action = detail.actions[0]
        assert click_action.type == "click"
        assert click_action.selector == ".card:first-child"

    def test_click_requires_target(self) -> None:
        with pytest.raises(ValidationError, match="click action requires"):
            CaptureDefinition(
                id="bad",
                name="Bad",
                output="docs/bad.png",
                actions=[{"type": "click"}],
            )

    def test_click_with_coordinates(self) -> None:
        cap = CaptureDefinition(
            id="coords",
            name="Coords",
            output="docs/coords.png",
            actions=[{"type": "click", "x": 100, "y": 200}],
        )
        assert cap.actions[0].type == "click"
        assert cap.actions[0].x == 100

    def test_wait_for_action(self) -> None:
        m = load_manifest(MANIFESTS / "valid-web.yml")
        detail = next(c for c in m.captures if c.id == "detail-view")
        wf = detail.actions[1]
        assert wf.type == "wait_for"
        assert wf.selector == ".detail-panel"
        assert wf.timeout == 5

    def test_scroll_to_action(self) -> None:
        m = load_manifest(MANIFESTS / "valid-web.yml")
        settings = next(c for c in m.captures if c.id == "settings")
        scroll = settings.actions[0]
        assert scroll.type == "scroll_to"
        assert scroll.selector == "#advanced-settings"

    def test_keystroke_action(self) -> None:
        m = load_manifest(MANIFESTS / "valid-tui.yml")
        main_view = m.captures[0]
        assert main_view.actions[0].type == "keystroke"
        assert main_view.actions[0].key == "i"

    def test_type_text_action(self) -> None:
        m = load_manifest(MANIFESTS / "valid-tui.yml")
        search = m.captures[1]
        tt = search.actions[1]
        assert tt.type == "type_text"
        assert tt.text == "query"
        assert tt.delay == 80


# ── Ready check validation ───────────────────────────


class TestReadyCheckValidation:
    def test_http_requires_url(self) -> None:
        with pytest.raises(ValidationError, match="http ready_check requires 'url'"):
            PhantomManifest(
                phantom="1",
                project="test",
                name="Test",
                setup={
                    "type": "web",
                    "run": {
                        "command": "npm run dev",
                        "ready_check": {"type": "http", "timeout": 10},
                    },
                },
                captures=[{"id": "home", "name": "Home", "output": "docs/home.png"}],
            )

    def test_tcp_requires_port(self) -> None:
        with pytest.raises(ValidationError, match="tcp ready_check requires 'port'"):
            PhantomManifest(
                phantom="1",
                project="test",
                name="Test",
                setup={
                    "type": "web",
                    "run": {
                        "command": "npm run dev",
                        "ready_check": {"type": "tcp", "timeout": 10},
                    },
                },
                captures=[{"id": "home", "name": "Home", "output": "docs/home.png"}],
            )

    def test_stdout_match_requires_pattern(self) -> None:
        with pytest.raises(ValidationError, match="stdout_match ready_check requires 'pattern'"):
            PhantomManifest(
                phantom="1",
                project="test",
                name="Test",
                setup={
                    "type": "web",
                    "run": {
                        "command": "npm run dev",
                        "ready_check": {"type": "stdout_match", "timeout": 10},
                    },
                },
                captures=[{"id": "home", "name": "Home", "output": "docs/home.png"}],
            )

    def test_delay_requires_seconds(self) -> None:
        with pytest.raises(ValidationError, match="delay ready_check requires 'seconds'"):
            PhantomManifest(
                phantom="1",
                project="test",
                name="Test",
                setup={
                    "type": "web",
                    "run": {
                        "command": "npm run dev",
                        "ready_check": {"type": "delay"},
                    },
                },
                captures=[{"id": "home", "name": "Home", "output": "docs/home.png"}],
            )


# ── Fixture validation ────────────────────────────────


class TestFixtureValidation:
    def test_script_requires_run(self) -> None:
        with pytest.raises(ValidationError, match="script fixture requires 'run'"):
            PhantomManifest(
                phantom="1",
                project="test",
                name="Test",
                setup={
                    "type": "web",
                    "run": {
                        "command": "npm run dev",
                        "ready_check": {
                            "type": "http",
                            "url": "http://localhost:3000",
                            "timeout": 10,
                        },
                    },
                },
                fixtures=[{"name": "bad", "type": "script"}],
                captures=[{"id": "home", "name": "Home", "output": "docs/home.png"}],
            )

    def test_http_requires_url(self) -> None:
        with pytest.raises(ValidationError, match="http fixture requires 'url'"):
            PhantomManifest(
                phantom="1",
                project="test",
                name="Test",
                setup={
                    "type": "web",
                    "run": {
                        "command": "npm run dev",
                        "ready_check": {
                            "type": "http",
                            "url": "http://localhost:3000",
                            "timeout": 10,
                        },
                    },
                },
                fixtures=[{"name": "bad", "type": "http"}],
                captures=[{"id": "home", "name": "Home", "output": "docs/home.png"}],
            )

    def test_file_copy_requires_source_and_dest(self) -> None:
        with pytest.raises(ValidationError, match="file_copy fixture requires"):
            PhantomManifest(
                phantom="1",
                project="test",
                name="Test",
                setup={
                    "type": "web",
                    "run": {
                        "command": "npm run dev",
                        "ready_check": {
                            "type": "http",
                            "url": "http://localhost:3000",
                            "timeout": 10,
                        },
                    },
                },
                fixtures=[{"name": "bad", "type": "file_copy", "source": "foo.png"}],
                captures=[{"id": "home", "name": "Home", "output": "docs/home.png"}],
            )


# ── Edge cases ────────────────────────────────────────


class TestEdgeCases:
    def test_project_id_must_be_kebab_case(self) -> None:
        with pytest.raises(ValidationError, match="project"):
            PhantomManifest(
                phantom="1",
                project="Not Kebab Case",
                name="Test",
                setup={
                    "type": "web",
                    "run": {
                        "command": "npm run dev",
                        "ready_check": {
                            "type": "http",
                            "url": "http://localhost:3000",
                            "timeout": 10,
                        },
                    },
                },
                captures=[{"id": "home", "name": "Home", "output": "docs/home.png"}],
            )

    def test_capture_id_must_be_kebab_case(self) -> None:
        with pytest.raises(ValidationError, match="id"):
            CaptureDefinition(
                id="Not Valid",
                name="Test",
                output="docs/test.png",
            )

    def test_at_least_one_capture_required(self) -> None:
        with pytest.raises(ValidationError):
            PhantomManifest(
                phantom="1",
                project="test",
                name="Test",
                setup={
                    "type": "web",
                    "run": {
                        "command": "npm run dev",
                        "ready_check": {
                            "type": "http",
                            "url": "http://localhost:3000",
                            "timeout": 10,
                        },
                    },
                },
                captures=[],
            )

    def test_wrong_schema_version(self) -> None:
        with pytest.raises(ManifestValidationError, match="Unsupported schema version"):
            PhantomManifest(
                phantom="2",
                project="test",
                name="Test",
                setup={
                    "type": "web",
                    "run": {
                        "command": "npm run dev",
                        "ready_check": {
                            "type": "http",
                            "url": "http://localhost:3000",
                            "timeout": 10,
                        },
                    },
                },
                captures=[{"id": "home", "name": "Home", "output": "docs/home.png"}],
            )

    def test_parallel_and_depends_on_conflict(self) -> None:
        with pytest.raises(ValidationError, match="cannot be both"):
            CaptureDefinition(
                id="conflict",
                name="Conflict",
                output="docs/conflict.png",
                parallel=True,
                depends_on="other",
            )

    def test_nonexistent_group(self) -> None:
        m = load_manifest(MANIFESTS / "valid-web.yml")
        with pytest.raises(KeyError, match="nonexistent"):
            m.get_group("nonexistent")

    def test_docker_compose_requires_compose_file(self) -> None:
        with pytest.raises(ValidationError, match=r"docker-compose.*requires.*compose_file"):
            PhantomManifest(
                phantom="1",
                project="test",
                name="Test",
                setup={
                    "type": "docker-compose",
                    "run": {
                        "command": "docker compose up",
                        "ready_check": {
                            "type": "http",
                            "url": "http://localhost:3000",
                            "timeout": 10,
                        },
                    },
                },
                captures=[{"id": "home", "name": "Home", "output": "docs/home.png"}],
            )

    def test_depends_on_nonexistent_capture(self) -> None:
        with pytest.raises(ManifestValidationError, match="does not exist"):
            PhantomManifest(
                phantom="1",
                project="test",
                name="Test",
                setup={
                    "type": "web",
                    "run": {
                        "command": "npm run dev",
                        "ready_check": {
                            "type": "http",
                            "url": "http://localhost:3000",
                            "timeout": 10,
                        },
                    },
                },
                captures=[
                    {
                        "id": "home",
                        "name": "Home",
                        "output": "docs/home.png",
                        "depends_on": "ghost",
                    },
                ],
            )
