"""Pydantic v2 models for the Phantom manifest schema.

Covers the complete .phantom.yml specification including all action types,
runner configurations, processing pipeline, and publishing options.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ── Shared Primitives ─────────────────────────────────


class Viewport(BaseModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ShadowOffset(BaseModel):
    x: int = 0
    y: int = 8


class Region(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class RetryConfig(BaseModel):
    max_attempts: int = Field(default=3, ge=1)
    backoff_ms: int = Field(default=1000, ge=0)


# ── Action Types ──────────────────────────────────────
# Discriminated union on the "type" field.


class NavigateAction(BaseModel):
    type: Literal["navigate"]
    url: str


class RouteAction(BaseModel):
    type: Literal["route"]
    path: str


class ClickAction(BaseModel):
    type: Literal["click"]
    selector: str | None = None
    x: int | None = None
    y: int | None = None
    button: Literal["left", "right", "middle"] = "left"
    count: int = 1

    @model_validator(mode="after")
    def require_target(self) -> ClickAction:
        if self.selector is None and (self.x is None or self.y is None):
            msg = "click action requires either 'selector' or both 'x' and 'y'"
            raise ValueError(msg)
        return self


class HoverAction(BaseModel):
    type: Literal["hover"]
    selector: str


class ScrollToAction(BaseModel):
    type: Literal["scroll_to"]
    selector: str
    block: Literal["start", "center", "end"] = "center"


class ScrollAction(BaseModel):
    type: Literal["scroll"]
    x: int = 0
    y: int = 0


class TypeAction(BaseModel):
    type: Literal["type"]
    selector: str | None = None
    text: str
    delay: int = Field(default=50, ge=0)


class PressAction(BaseModel):
    type: Literal["press"]
    key: str


class KeyboardShortcutAction(BaseModel):
    type: Literal["keyboard_shortcut"]
    keys: str


class KeystrokeAction(BaseModel):
    """TUI runner: send a single key."""

    type: Literal["keystroke"]
    key: str


class TypeTextAction(BaseModel):
    """TUI runner: type a string character by character."""

    type: Literal["type_text"]
    text: str
    delay: int = Field(default=80, ge=0)


class WaitAction(BaseModel):
    type: Literal["wait"]
    ms: int = Field(gt=0)


class WaitForAction(BaseModel):
    type: Literal["wait_for"]
    selector: str
    state: Literal["visible", "attached", "hidden", "detached"] = "visible"
    timeout: int = Field(default=10, gt=0)


class WaitForNetworkAction(BaseModel):
    type: Literal["wait_for_network"]
    state: Literal["idle", "no-pending"] = "idle"
    timeout: int = Field(default=10, gt=0)


class SetThemeAction(BaseModel):
    type: Literal["set_theme"]
    theme: Literal["dark", "light"]


class SetViewportAction(BaseModel):
    type: Literal["set_viewport"]
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class EvaluateAction(BaseModel):
    type: Literal["evaluate"]
    js: str


class SetCookieAction(BaseModel):
    type: Literal["set_cookie"]
    name: str
    value: str
    domain: str = "localhost"


class XdotoolAction(BaseModel):
    type: Literal["xdotool"]
    action: str


class XdgShortcutAction(BaseModel):
    type: Literal["xdg_shortcut"]
    shortcut: str


class ConditionalAction(BaseModel):
    type: Literal["conditional"]
    if_: dict[str, str] = Field(alias="if")
    then: list[Action]
    else_: list[Action] | None = Field(default=None, alias="else")

    model_config = {"populate_by_name": True}


Action = Annotated[
    NavigateAction
    | RouteAction
    | ClickAction
    | HoverAction
    | ScrollToAction
    | ScrollAction
    | TypeAction
    | PressAction
    | KeyboardShortcutAction
    | KeystrokeAction
    | TypeTextAction
    | WaitAction
    | WaitForAction
    | WaitForNetworkAction
    | SetThemeAction
    | SetViewportAction
    | EvaluateAction
    | SetCookieAction
    | XdotoolAction
    | XdgShortcutAction
    | ConditionalAction,
    Field(discriminator="type"),
]

# We need to rebuild ConditionalAction after Action is defined
# because it references Action in its fields.
ConditionalAction.model_rebuild()


# ── Ready Check ───────────────────────────────────────


class ReadyCheck(BaseModel):
    type: Literal["http", "tcp", "stdout_match", "delay", "screen_stable"]
    url: str | None = None
    port: int | None = None
    pattern: str | None = None
    seconds: int | None = None
    status_code: int = 200
    timeout: int = Field(default=30, gt=0)
    interval: int = Field(default=1, gt=0)

    # screen_stable parameters
    stability_window: int = Field(default=500, gt=0)
    check_interval: int = Field(default=100, gt=0)

    @model_validator(mode="after")
    def validate_ready_check_fields(self) -> ReadyCheck:
        match self.type:
            case "http":
                if not self.url:
                    raise ValueError("http ready_check requires 'url'")
            case "tcp":
                if self.port is None:
                    raise ValueError("tcp ready_check requires 'port'")
            case "stdout_match":
                if not self.pattern:
                    raise ValueError("stdout_match ready_check requires 'pattern'")
            case "delay":
                if self.seconds is None:
                    raise ValueError("delay ready_check requires 'seconds'")
        return self


# ── Setup Configuration ───────────────────────────────


class RunConfig(BaseModel):
    command: str
    env: dict[str, str] | None = None
    ready_check: ReadyCheck


class SetupConfig(BaseModel):
    type: str
    requires: list[str] | None = None

    @field_validator("type")
    @classmethod
    def validate_type_format(cls, v: str) -> str:
        if not re.match(r"^[a-z][a-z0-9-]*$", v):
            raise ValueError(
                f"Setup type '{v}' must match ^[a-z][a-z0-9-]*$ "
                "(lowercase, starting with a letter, may contain digits and hyphens)"
            )
        return v

    build: list[str] | None = None
    run: RunConfig
    teardown: list[str] | None = None
    runner_timeout: int = Field(default=300, gt=0)

    # Docker-compose specific
    compose_file: str | None = None
    compose_profiles: list[str] | None = None
    services: list[str] | None = None

    @model_validator(mode="after")
    def validate_docker_fields(self) -> SetupConfig:
        if self.type == "docker-compose" and not self.compose_file:
            raise ValueError("docker-compose setup requires 'compose_file'")
        return self


# ── Fixtures ──────────────────────────────────────────


class Fixture(BaseModel):
    name: str
    type: Literal["script", "http", "file_copy"]
    run: str | None = None
    method: str | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    body: str | None = None
    expected_status: int | None = None
    source: str | None = None
    destination: str | None = None
    timeout: int = Field(default=30, gt=0)

    @model_validator(mode="after")
    def validate_fixture_fields(self) -> Fixture:
        match self.type:
            case "script":
                if not self.run:
                    raise ValueError("script fixture requires 'run'")
            case "http":
                if not self.url:
                    raise ValueError("http fixture requires 'url'")
            case "file_copy":
                if not self.source or not self.destination:
                    raise ValueError("file_copy fixture requires 'source' and 'destination'")
        return self


# ── Capture Configuration ─────────────────────────────


class CaptureDefaults(BaseModel):
    viewport: Viewport | None = None
    theme: Literal["dark", "light", "system", "none"] = "dark"
    device_scale: int = Field(default=2, ge=1, le=3)
    full_page: bool = False
    wait_after_actions: int = Field(default=500, ge=0)
    timeout: int = Field(default=15, gt=0)
    retry: RetryConfig | None = None


class CaptureDefinition(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9\-]*$")
    name: str
    description: str | None = None
    route: str | None = None
    wait_for: str | None = None
    wait_for_state: Literal["visible", "attached", "hidden", "detached"] = "visible"
    output: str
    readme_target: str | None = None
    alt_text: str | None = None

    # Overrides from capture_defaults
    viewport: Viewport | None = None
    theme: Literal["dark", "light", "system", "none"] | None = None
    device_scale: int | None = Field(default=None, ge=1, le=3)
    full_page: bool | None = None
    wait_after_actions: int | None = Field(default=None, ge=0)
    timeout: int | None = Field(default=None, gt=0)

    actions: list[Action] = Field(default_factory=list)

    # Enhanced fields
    skip: bool = False
    depends_on: str | None = None
    parallel: bool = False
    format: Literal["png", "webp"] | None = None
    retry: RetryConfig | None = None

    @model_validator(mode="after")
    def validate_parallel_vs_depends(self) -> CaptureDefinition:
        if self.parallel and self.depends_on is not None:
            raise ValueError("capture cannot be both 'parallel' and 'depends_on' another capture")
        return self

    def resolve(self, defaults: CaptureDefaults | None) -> ResolvedCapture:
        """Merge this capture's fields with defaults, producing a fully-resolved capture."""
        d = defaults or CaptureDefaults()
        return ResolvedCapture(
            id=self.id,
            name=self.name,
            description=self.description,
            route=self.route,
            wait_for=self.wait_for,
            wait_for_state=self.wait_for_state,
            output=self.output,
            readme_target=self.readme_target,
            alt_text=self.alt_text or self.description,
            viewport=self.viewport or d.viewport or Viewport(width=1280, height=800),
            theme=self.theme or d.theme,
            device_scale=self.device_scale if self.device_scale is not None else d.device_scale,
            full_page=self.full_page if self.full_page is not None else d.full_page,
            wait_after_actions=(
                self.wait_after_actions
                if self.wait_after_actions is not None
                else d.wait_after_actions
            ),
            timeout=self.timeout if self.timeout is not None else d.timeout,
            actions=self.actions,
            skip=self.skip,
            depends_on=self.depends_on,
            parallel=self.parallel,
            format=self.format,
            retry=self.retry or d.retry or RetryConfig(),
        )


class ResolvedCapture(BaseModel):
    """A capture with all defaults applied. Used by runners at execution time."""

    id: str
    name: str
    description: str | None
    route: str | None
    wait_for: str | None
    wait_for_state: Literal["visible", "attached", "hidden", "detached"]
    output: str
    readme_target: str | None
    alt_text: str | None
    viewport: Viewport
    theme: Literal["dark", "light", "system", "none"]
    device_scale: int
    full_page: bool
    wait_after_actions: int
    timeout: int
    actions: list[Action]
    skip: bool
    depends_on: str | None
    parallel: bool
    format: Literal["png", "webp"] | None
    retry: RetryConfig


# ── Processing (Darkroom) ─────────────────────────────


class BorderConfig(BaseModel):
    style: Literal["drop-shadow", "rounded", "outline", "none"] = "drop-shadow"
    shadow_color: str = "rgba(0,0,0,0.3)"
    shadow_offset: ShadowOffset = Field(default_factory=ShadowOffset)
    shadow_blur: int = Field(default=24, ge=0)
    padding: int = Field(default=32, ge=0)
    background: str = "transparent"
    corner_radius: int = Field(default=8, ge=0)


class DiffConfig(BaseModel):
    enabled: bool = True
    threshold: float = Field(default=0.95, ge=0.0, le=1.0)
    algorithm: Literal["ssim", "pixelmatch"] = "ssim"
    ignore_regions: list[Region] = Field(default_factory=list)


class ProcessingConfig(BaseModel):
    format: Literal["png", "webp"] = "png"
    optimize: bool = True
    max_width: int = Field(default=2800, gt=0)
    border: BorderConfig = Field(default_factory=BorderConfig)
    diff: DiffConfig = Field(default_factory=DiffConfig)


# ── Publishing ────────────────────────────────────────


class CommitAuthor(BaseModel):
    name: str = "Phantom Bot"
    email: str = "phantom@noreply"


class PublishingConfig(BaseModel):
    branch: str = "main"
    commit_author: CommitAuthor = Field(default_factory=CommitAuthor)
    ci_skip_tag: str = "[skip ci]"
    commit_message: str = "docs(screenshots): update via Phantom"
    strategy: Literal["direct", "pr"] = "direct"
    readme_update: bool = True
    cleanup_stale: bool = True

    # PR-specific options
    pr_title: str | None = None
    pr_labels: list[str] | None = None
    pr_auto_merge: bool | None = None


# ── Triggers ──────────────────────────────────────────


class TriggerConfig(BaseModel):
    type: Literal["release", "schedule", "push"]
    cron: str | None = None
    branches: list[str] | None = None
    paths: list[str] | None = None

    @model_validator(mode="after")
    def validate_trigger_fields(self) -> TriggerConfig:
        if self.type == "schedule" and not self.cron:
            raise ValueError("schedule trigger requires 'cron'")
        return self


# ── TUI Configuration ─────────────────────────────────


class TerminalConfig(BaseModel):
    width: int = Field(default=120, gt=0)
    height: int = Field(default=40, gt=0)


class RendererConfig(BaseModel):
    font: str = "JetBrains Mono"
    font_size: int = Field(default=14, gt=0)
    theme: str = "Catppuccin Mocha"
    line_numbers: bool = False
    padding: int = Field(default=20, ge=0)
    background: str = "#1e1e2e"
    window_controls: bool = True
    corner_radius: int = Field(default=8, ge=0)


class TUIConfig(BaseModel):
    terminal: TerminalConfig = Field(default_factory=TerminalConfig)
    renderer: Literal["silicon", "freeze", "termshot"] = "silicon"
    renderer_config: RendererConfig = Field(default_factory=RendererConfig)


# ── Desktop Configuration ─────────────────────────────


class DisplayConfig(BaseModel):
    resolution: str = "1920x1080"
    depth: int = 24
    dpi: int = 96


class DesktopConfig(BaseModel):
    display: DisplayConfig = Field(default_factory=DisplayConfig)
    window_manager: Literal["openbox", "fluxbox", "none"] = "openbox"
    window_manager_theme: str = "Nightmare"
    screenshot_method: Literal["maim", "scrot", "xdotool", "import"] = "import"
    screenshot_target: Literal["window", "screen", "region"] = "window"
    webview_debug_port: int | None = None
    window_title: str | None = None
    window_class: str | None = None
    startup_wait_ms: int = Field(default=3000, ge=0)


# ── AI Director ───────────────────────────────────────


class DirectorConfig(BaseModel):
    enabled: bool = False
    model: str = "claude-sonnet-4-20250514"
    explore: bool = True
    auto_caption: bool = True
    suggest_captures: bool = True
    max_exploration_steps: int = Field(default=50, gt=0)
    max_tokens: int = Field(default=500_000, gt=0)


# ── Top-Level Manifest ────────────────────────────────


class PhantomManifest(BaseModel):
    """Root model for .phantom.yml files."""

    phantom: str = Field(description="Schema version, must be '1'")
    project: str = Field(pattern=r"^[a-z0-9][a-z0-9\-]*$")
    name: str
    description: str | None = None

    setup: SetupConfig
    fixtures: list[Fixture] = Field(default_factory=list)
    capture_defaults: CaptureDefaults | None = None
    captures: list[CaptureDefinition] = Field(min_length=1)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    publishing: PublishingConfig = Field(default_factory=PublishingConfig)
    triggers: list[TriggerConfig] = Field(default_factory=list)

    groups: dict[str, list[str]] | None = None

    # Runner-specific configs
    tui: TUIConfig | None = None
    desktop: DesktopConfig | None = None
    director: DirectorConfig | None = None

    @model_validator(mode="after")
    def validate_manifest(self) -> PhantomManifest:
        errors: list[str] = []

        # Schema version check
        if self.phantom != "1":
            errors.append(f"Unsupported schema version '{self.phantom}', expected '1'")

        # Unique capture IDs
        ids = [c.id for c in self.captures]
        dupes = [i for i in ids if ids.count(i) > 1]
        if dupes:
            errors.append(f"Duplicate capture IDs: {', '.join(set(dupes))}")

        # Output paths don't escape project root
        for cap in self.captures:
            if cap.output.startswith("/") or ".." in cap.output.split("/"):
                errors.append(
                    f"Capture '{cap.id}' output path must be relative "
                    f"and not contain '..': {cap.output}"
                )

        # depends_on references exist
        id_set = set(ids)
        for cap in self.captures:
            if cap.depends_on and cap.depends_on not in id_set:
                errors.append(
                    f"Capture '{cap.id}' depends_on '{cap.depends_on}' which does not exist"
                )

        # Group references exist
        if self.groups:
            for group_name, group_ids in self.groups.items():
                for gid in group_ids:
                    if gid not in id_set:
                        errors.append(
                            f"Group '{group_name}' references capture '{gid}' which does not exist"
                        )

        # Circular dependency check
        if not errors:
            self._check_circular_deps(errors)

        if errors:
            from phantom.exceptions import ManifestValidationError

            raise ManifestValidationError(errors)

        return self

    def _check_circular_deps(self, errors: list[str]) -> None:
        """Detect circular capture dependencies via DFS."""
        dep_map: dict[str, str] = {}
        for cap in self.captures:
            if cap.depends_on:
                dep_map[cap.id] = cap.depends_on

        for start_id in dep_map:
            visited: set[str] = set()
            current = start_id
            while current in dep_map:
                if current in visited:
                    errors.append(f"Circular dependency detected involving capture '{current}'")
                    return
                visited.add(current)
                current = dep_map[current]

    def resolve_captures(self) -> list[ResolvedCapture]:
        """Resolve all captures with defaults applied."""
        return [cap.resolve(self.capture_defaults) for cap in self.captures]

    def get_group(self, group_name: str) -> list[str]:
        """Get capture IDs in a group. Raises KeyError if group doesn't exist."""
        if not self.groups or group_name not in self.groups:
            raise KeyError(f"Group '{group_name}' not defined in manifest")
        return self.groups[group_name]


# ── Manifest Loading ──────────────────────────────────


def load_manifest(path: str | Any) -> PhantomManifest:
    """Load and validate a .phantom.yml file.

    Args:
        path: Path to the manifest file (str or Path).

    Returns:
        Validated PhantomManifest instance.

    Raises:
        ManifestNotFoundError: File doesn't exist.
        ManifestValidationError: File fails schema validation.
    """
    from pathlib import Path as PathClass

    from ruamel.yaml import YAML

    from phantom.exceptions import ManifestNotFoundError

    p = PathClass(path)
    if not p.exists():
        raise ManifestNotFoundError(f"Manifest not found: {p}")

    yaml = YAML()
    with p.open() as f:
        data = yaml.load(f)

    if not isinstance(data, dict):
        from phantom.exceptions import ManifestValidationError

        raise ManifestValidationError(
            ["Manifest must be a YAML mapping, got " + type(data).__name__]
        )

    return PhantomManifest.model_validate(data)
