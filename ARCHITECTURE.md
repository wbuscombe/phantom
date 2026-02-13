# Architecture

This document describes Phantom's internal architecture for contributors and plugin authors.

## System Overview

```
                    ┌─────────────────────────────────────┐
                    │              CLI Layer               │
                    │  phantom run / init / doctor / ...   │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │         Conductor Layer              │
                    │                                      │
                    │  ┌────────────┐  ┌───────────────┐  │
                    │  │Orchestrator│  │  State Manager │  │
                    │  │  (FSM)     │  │  (JSON store)  │  │
                    │  └─────┬──────┘  └───────────────┘  │
                    │        │                             │
                    │  ┌─────▼──────┐  ┌───────────────┐  │
                    │  │ Workspace  │  │   Fixtures     │  │
                    │  └────────────┘  └───────────────┘  │
                    │                                      │
                    │  ┌────────────┐  ┌───────────────┐  │
                    │  │  Webhook   │  │   Scheduler    │  │
                    │  │  Listener  │  │   (cron)       │  │
                    │  └─────┬──────┘  └──────┬────────┘  │
                    │        └───────┬────────┘           │
                    │           ┌────▼────┐               │
                    │           │  Queue  │               │
                    │           └─────────┘               │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │          Runner Layer                │
                    │                                      │
                    │  ┌─────┐  ┌─────┐  ┌────────────┐  │
                    │  │ Web │  │ TUI │  │Docker Comp.│  │
                    │  └──┬──┘  └──┬──┘  └─────┬──────┘  │
                    │     └────────┴───────────┘          │
                    │         BaseRunner ABC               │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │         Darkroom Layer               │
                    │  crop → border → optimize → diff    │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │        Publisher Layer               │
                    │  README sentinels → git commit/push  │
                    └─────────────────────────────────────┘
```

## Component Descriptions

### CLI (`cli.py`)

Click-based command group. Thin layer that parses arguments, loads the manifest, and delegates to the conductor. All output uses Rich for formatting.

### Conductor (`conductor/`)

The orchestration layer that coordinates a capture run.

- **Orchestrator** — Finite state machine driving the pipeline from INIT through COMPLETED or FAILED. Manages locking, workspace creation, runner lifecycle, and error recovery.
- **Workspace** — Creates isolated working directories under `/tmp/phantom/workspace/`, manages local project symlinks and previous screenshot fetching.
- **State Manager** — Persists run history as JSON (`~/.phantom/state.json`), tracks per-project last SHA and diff percentages.
- **Requirements** — Checks system tool availability (`which` + version parsing) with OS-specific install hints.
- **Fixtures** — Executes pre-capture setup (scripts, HTTP calls, file copies).
- **Queue** — Async job queue with configurable concurrency and deduplication.
- **Scheduler** — Cron-based scheduling via croniter for time-triggered runs.
- **Webhook Listener** — aiohttp server handling GitHub push/release webhooks with HMAC verification.

### Runners (`runners/`)

Pluggable execution backends implementing the `BaseRunner` ABC:

- **`setup(ctx)`** — Build the project (run build commands)
- **`launch(ctx)`** — Start the application and wait for ready check
- **`capture(ctx, capture_def)`** — Execute actions and take a screenshot
- **`teardown(ctx)`** — Stop the application and clean up

The runner registry (`runners/__init__.py`) maps type names to classes. Built-in runners are registered at import time; external plugins use the `phantom.runners` entry-point group.

### Darkroom (`darkroom/`)

Image processing pipeline with stages:

1. **Crop** — Region extraction if specified
2. **Border** — Drop shadow, rounded corners, or outline
3. **Optimize** — Lossless PNG optimization or WebP conversion
4. **Diff** — SSIM comparison against previous screenshot to detect changes

### Publisher (`publisher/`)

- **Git** — Commits processed screenshots, handles branch strategy (direct commit or PR), stale file cleanup, push with conflict retry.
- **README** — Finds `<!-- phantom:id -->` sentinel pairs and injects `<img>` tags with proper sizing.

### Models (`models.py`)

Pydantic v2 models for the complete `.phantom.yml` schema. Discriminated union for action types, model validators for cross-field constraints, and a `resolve_captures()` method that merges per-capture overrides with defaults.

## Orchestrator State Machine

```
INIT → VALIDATING → WORKSPACE → BUILDING → SEEDING → LAUNCHING →
CAPTURING → PROCESSING → PUBLISHING → TEARDOWN → COMPLETED

On failure at any stage: → TEARDOWN → FAILED
```

Each transition is logged via structlog with timestamps. The orchestrator acquires an flock-based per-project lock to prevent concurrent runs.

## Data Flow

```
.phantom.yml
    │
    ▼ (load_manifest)
PhantomManifest
    │
    ▼ (resolve_captures)
list[ResolvedCapture]
    │
    ▼ (runner.capture)
list[CaptureResult]       ← raw screenshots in workspace/raw/
    │
    ▼ (darkroom.process)
list[PipelineResult]      ← processed images in workspace/processed/
    │
    ▼ (copy_outputs_to_project)
Final images in project dir (e.g., docs/screenshots/)
    │
    ▼ (publish)
Git commit + push
```

## Directory Structure

```
/tmp/phantom/workspace/
├── .locks/
│   └── my-project.lock
└── my-project/
    ├── project/          # Symlink to local project or git clone
    ├── raw/              # Raw screenshots from runners
    └── processed/        # Darkroom output
```

## Extension Points

1. **Runner plugins** — Implement `BaseRunner`, register via `phantom.runners` entry point
2. **Darkroom stages** — Pipeline is a list of stages; new stages can be inserted
3. **Ready checks** — `ReadyCheck` model supports http, tcp, stdout_match, delay, screen_stable
4. **Action types** — Discriminated union in `models.py`; runners handle known types
5. **Publishing strategies** — direct commit or PR; extensible for other targets

## Design Principles

- **YAML-first** — Everything is configured in the manifest, not in code
- **Fail fast** — Validate eagerly (manifest, requirements, workspace) before starting expensive operations
- **Idempotent** — Running twice with the same inputs produces the same result (diff detection skips unchanged captures)
- **Structured logging** — All operations emit structured events via structlog for observability
- **Async I/O** — Subprocesses and network calls are async for responsiveness
- **Plugin-friendly** — Core interfaces are stable; runners are the primary extension point
