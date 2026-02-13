# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
