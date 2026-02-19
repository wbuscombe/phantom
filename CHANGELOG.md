# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **AI Analyst engine** (`phantom analyze`) for autonomous codebase analysis and manifest generation via Claude API.
- **Documentation Writer** (`--ai-document`) for AI-powered README screenshot placement with retina-aware img tags.
- **Full autonomous pipeline** (`--ai-auto`) combining analysis, capture, and documentation in a single command.
- **Cost tracking** (`phantom costs`) with budget enforcement for API calls ($0.50 default per run).
- **FileSelector** with project-type-specific file prioritization under 25K token budget.
- **Path-based CI trigger filtering** for push events in GitHub Actions workflows.
- **Reusable workflow inputs** for `ai-analyst`, `ai-document`, `ai-auto`, and `anthropic-key` secret.
- **126 new tests** (115 unit + 11 integration) for analyst engine and documentation writer, all with mocked API calls.

### Fixed

- **Entry point detection** now prefers TUI-related scripts (`yt-tui`) over CLI tools (`yt`) for projects with multiple `[project.scripts]` entries.
- **Project display name** extracted from README H1 heading instead of using raw package name; kebab-case/snake_case names converted to Title Case.
- **Retry config** (`max_attempts: 2, backoff_ms: 1000`) added to generated manifest `capture_defaults`.

## [0.1.0] - 2026-02-12

### Added

- **Manifest schema** (`.phantom.yml`) with Pydantic v2 validation, covering setup, captures, processing, publishing, triggers, and runner-specific configs.
- **Web runner** using Playwright for browser-based screenshot capture with full action support (navigate, click, type, scroll, wait, evaluate, set cookies, themes).
- **TUI runner** for terminal application screenshots via pyte terminal emulation and silicon/freeze rendering.
- **Docker Compose runner** for containerized application screenshots with compose lifecycle management.
- **Darkroom image processing pipeline** with stages: crop, border (drop-shadow, rounded, outline), optimize, format conversion, and SSIM-based diff detection.
- **README sentinel system** for automatic image tag injection between `<!-- phantom:id -->` markers.
- **Git publisher** with direct-commit and PR strategies, stale screenshot cleanup, and conflict retry.
- **CLI commands**: `phantom run`, `phantom validate`, `phantom init`, `phantom status`, `phantom serve`, `phantom gc`, `phantom doctor`.
- **Conductor orchestrator** with full state machine (INIT through COMPLETED/FAILED), flock-based locking, workspace management, and structured run reports.
- **Webhook listener** (GitHub push/release events) with HMAC signature verification.
- **Job queue** with configurable concurrency, deduplication, and priority scheduling.
- **Cron scheduler** for time-based trigger execution via croniter.
- **State persistence** (JSON-based) tracking per-project run history, last SHA, and diff percentages.
- **Runner plugin registry** with built-in runner registration and `phantom.runners` entry-point discovery for external plugins.
- **`phantom doctor`** command for system dependency checking with OS-specific install hints.
- **Auto-detection** in `phantom init` for project type based on marker files (package.json, Cargo.toml, docker-compose.yml, etc.).
- **246+ unit and integration tests** covering models, runners, darkroom, publisher, orchestrator, CLI, webhooks, queue, scheduler, and state management.

[0.1.0]: https://github.com/wbuscombe/phantom/releases/tag/v0.1.0
