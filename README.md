# Phantom

**Automated documentation screenshots for software projects.**

[![PyPI](https://img.shields.io/pypi/v/phantom-docs)](https://pypi.org/project/phantom-docs/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## The Problem

Documentation screenshots go stale. Every UI change means manually re-capturing images, cropping them, adding drop shadows, updating the README, and committing. Most teams give up and let their docs rot.

## The Solution

Phantom automates the entire pipeline: **launch your app, execute actions, capture screenshots, process them, and commit the results** — all from a single YAML manifest.

```yaml
# .phantom.yml
phantom: "1"
project: "my-app"
name: "My App"

setup:
  type: web
  build:
    - npm ci
  run:
    command: "npm run dev"
    ready_check:
      type: http
      url: "http://localhost:3000"

captures:
  - id: dashboard
    name: "Dashboard"
    route: "/"
    output: "docs/screenshots/dashboard.png"
    actions:
      - type: wait_for
        selector: ".dashboard-loaded"
      - type: set_theme
        theme: dark
```

```bash
phantom run -p ./my-app
```

## Installation

```bash
pipx install phantom-docs
# or
pip install phantom-docs
```

For web runner captures, install Playwright browsers:

```bash
playwright install chromium
```

Check your setup:

```bash
phantom doctor
```

## Quick Start

```bash
# 1. Initialize a manifest (auto-detects project type)
phantom init

# 2. Edit .phantom.yml with your routes and captures

# 3. Run the pipeline
phantom run -p .
```

## Onboard Your Project

The fastest way to set up Phantom for an existing project is with [Claude Code](https://claude.ai/claude-code). Copy the [onboarding prompt](docs/onboarding-prompt.md) into Claude Code while in your project's root directory — it will analyze your codebase and generate everything Phantom needs:

- Framework-specific demo mode playbooks (Flask, React, SDL2, Java Swing, TUI)
- `.phantom.yml` manifest with progressive verification at every stage
- GitHub Actions workflow for automated updates
- README sentinels for screenshot placement
- Action timing rules and screenshot quality checks
- Desktop Runner support for native GUI apps

```bash
# From your project directory:
cat path/to/phantom/docs/onboarding-prompt.md | pbcopy  # macOS
# Then paste into Claude Code
```

## Consumer Contract

Phantom freezes the interface your app and CI depend on in
**[`CONTRACT.md`](CONTRACT.md)** — currently **`contract-version: 1.0.0`**. It
covers the `PHANTOM_MODE=1` boot semantics, the `.phantom.yml` schema
(unknown keys are always ignored, never fatal), the readiness/timeout signal,
and the `docs/screenshots/` artifact directory.

Pin the package by minor range and assert on the contract version — the same
discipline as pinning a Docker image tag rather than `latest`:

```python
import phantom
assert phantom.__contract_version__.startswith("1.")   # contract major 1
# requirements: phantom-docs==0.4.*
```

Phantom guarantees `PHANTOM_MODE=1` in your app's environment on every capture,
across all runners. Conformance is machine-checked in
[`tests/contract/`](tests/contract/); the CI smoke job that consumes the
contract is specified in [`docs/smoke-job-spec.md`](docs/smoke-job-spec.md).

## Runners

Phantom supports multiple runner types for different kinds of applications:

| Runner | Type | Use Case | Key Tools |
|--------|------|----------|-----------|
| **Web** | `web` | Browser-based apps | Playwright, Node |
| **TUI** | `tui` | Terminal applications | pyte, silicon |
| **Docker Compose** | `docker-compose` | Containerized apps | Docker |

Runners are pluggable — see [Writing Runner Plugins](docs/writing-runners.md) for the extension API.

## Manifest Reference

The `.phantom.yml` manifest has these top-level sections:

```yaml
phantom: "1"              # Schema version
project: "my-app"         # Unique project ID (kebab-case)
name: "My App"            # Display name

setup:                     # How to build and run the project
  type: web                # Runner type
  build: [...]             # Build commands
  run:                     # Run configuration
    command: "..."
    ready_check: { ... }

capture_defaults:          # Defaults applied to all captures
  viewport: { width: 1280, height: 800 }
  theme: dark

captures:                  # Screenshot definitions
  - id: hero
    name: "Hero screenshot"
    route: "/"
    output: "docs/hero.png"
    actions: [...]

processing:                # Image processing pipeline
  format: png
  border:
    style: drop-shadow

publishing:                # Git commit settings
  branch: main
  strategy: direct         # or "pr"
  readme_update: true
```

See [docs/manifest-reference.md](docs/manifest-reference.md) for the complete field reference.

## CLI Reference

| Command | Description |
|---------|-------------|
| `phantom run -p <path>` | Run the capture pipeline |
| `phantom validate <manifest>` | Validate a manifest file |
| `phantom init` | Scaffold a new `.phantom.yml` |
| `phantom doctor` | Check system dependencies |
| `phantom status` | Show run history |
| `phantom serve` | Start webhook listener + scheduler |
| `phantom gc` | Clean up stale workspaces |

### Common Options

| Option | Description |
|--------|-------------|
| `--dry-run` | Run pipeline without git commits |
| `--capture <id>` | Run a single capture |
| `--group <name>` | Run a named group of captures |
| `--skip-publish` | Capture and process, skip git |
| `--force` | Commit even if below diff threshold |
| `--if-changed` | Skip if repo HEAD unchanged |
| `--verbose` / `-v` | Enable debug logging |

## How It Works

```
 .phantom.yml
      │
      ▼
 ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
 │ Validate  │────▶│  Build   │────▶│  Launch  │────▶│ Capture  │
 │ Manifest  │     │ Project  │     │   App    │     │ Screenshots│
 └──────────┘     └──────────┘     └──────────┘     └──────────┘
                                                          │
      ┌───────────────────────────────────────────────────┘
      ▼
 ┌──────────┐     ┌──────────┐     ┌──────────┐
 │ Darkroom │────▶│  README  │────▶│   Git    │
 │ Process  │     │  Update  │     │ Publish  │
 └──────────┘     └──────────┘     └──────────┘
```

1. **Validate** — Parse and validate the manifest with Pydantic
2. **Build** — Run build commands (`npm ci`, `cargo build`, etc.)
3. **Launch** — Start the app and wait for ready check
4. **Capture** — Execute actions and take screenshots
5. **Darkroom** — Process images (crop, borders, optimize, diff)
6. **README** — Update sentinel regions with new image tags
7. **Publish** — Commit and push (or open a PR)

## Configuration

### Environment Variables

| Variable | Description |
|----------|-------------|
| `PHANTOM_MODE` | Set to `1` in your app's environment by Phantom on every capture; your app switches to deterministic demo mode. See [`CONTRACT.md`](CONTRACT.md). |
| `PHANTOM_WEBHOOK_SECRET` | HMAC secret for webhook verification |
| `PHANTOM_MANIFEST_MAP` | Repo-to-manifest mapping for `serve` mode |

### README Sentinels

Add markers to your README for automatic image updates:

```markdown
<!-- phantom:hero -->
<!-- /phantom:hero -->
```

Phantom will inject the `<img>` tag between these markers when a capture with `readme_target: hero` changes.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, running tests, and contribution guidelines.

## License

[MIT](LICENSE) — Copyright 2026 Will Buscombe
