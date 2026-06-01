# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- **Publish quality gate** (`Orchestrator._publish`): `phantom run` no longer commits or pushes a capture that fails an **error-severity** quality check (blank / too-small / bad-dimensions). Pass `--force` to publish anyway (for intentional low-entropy frames such as splash screens). Warning-severity issues remain advisory and still publish. CI is unaffected because it runs with `--skip-publish`. A blocked publish exits non-zero and sets `JobReport.blocked_by_quality`.
- **CI screenshot artifact is now opt-in and success-only**: the reusable `phantom-capture.yml` uploads `docs/screenshots/` as a workflow artifact only when the new `upload-screenshots-artifact` input is `true` **and** the run succeeded (previously `if: always()`). This prevents a sensitive or failed frame from becoming externally downloadable before review — independent of the `pr` publish gate.

### Fixed

- **Corrected auto-rollback documentation**: snapshots/rollback are a **manual** CLI tool, not an automatic safety net. The orchestrator never auto-creates snapshots and a failing quality check does not trigger a rollback; rollback is forward-only and cannot remove an already-pushed frame. Updated the `SnapshotManager` docstring, the 0.3.0 changelog entry, and the collaborator guide accordingly.

## [0.3.0] - 2026-02-28

### Added

- **Desktop Runner** for native GUI apps (SDL2, Swing, Qt, GTK) via Xvfb + xdotool + ImageMagick. Supports click, keystroke, type, drag, wait, and raw xdotool actions.
- **LLM provider abstraction** (`providers.py`) with `LLMProvider` protocol, `AnthropicProvider`, and per-model pricing table. Configurable via `PHANTOM_LLM_PROVIDER` and `PHANTOM_LLM_MODEL` env vars.
- **Screenshot visual review** (`--review` flag) sends captured screenshots to vision API for quality scoring, issue detection, and improvement suggestions. Off by default, $0.30 budget cap.
- **Manual snapshot/rollback CLI** (`phantom snapshots`, `phantom rollback`) via `SnapshotManager` to record and restore screenshot state on demand. (Manual only — not triggered automatically during a run; rollback is forward-only and cannot remove an already-pushed frame.)
- **Bot commit squash strategy** (`strategy: squash` in publishing config) commits to a side branch and squash-merges for a cleaner git history — one commit per screenshot update cycle.
- **Enhanced bot commit messages** with per-capture detail: updated/unchanged lists, quality summary, and capture count in subject line.
- **Desktop runner deps** in reusable workflow: xdotool and imagemagick added alongside xvfb.
- **Concurrency groups** for School-Work monorepo screenshot workflows to prevent git push race conditions.
- **Version range pinning** for consumer workflows (`>=0.2,<0.3` instead of exact pins).
- **`DesktopConfig` extensions**: `window_title`, `window_class`, `startup_wait_ms` fields; `import` as default screenshot method.

### Changed

- **Analyzer** refactored to use `LLMProvider` protocol instead of direct Anthropic SDK coupling.
- **CostTracker** now accepts a `model` parameter and uses per-model pricing from `MODEL_PRICING` table instead of hardcoded Sonnet pricing.
- **Reusable workflow** (`phantom-capture.yml`) default version changed from exact `0.2.0` to range `>=0.2,<0.3` with smarter install logic supporting version constraints, exact versions, and git refs.

## [0.2.0] - 2026-02-20

### Added

- **AI Analyst engine** (`phantom analyze`) for autonomous codebase analysis and manifest generation via Claude API.
- **Documentation Writer** (`--ai-document`) for AI-powered README screenshot placement with retina-aware img tags.
- **Full autonomous pipeline** (`--ai-auto`) combining analysis, capture, and documentation in a single command.
- **Cost tracking** (`phantom costs`) with budget enforcement for API calls ($0.50 default per run).
- **FileSelector** with project-type-specific file prioritization under 25K token budget.
- **Path-based CI trigger filtering** for push events in GitHub Actions workflows.
- **Reusable workflow inputs** for `ai-analyst`, `ai-document`, `ai-auto`, and `anthropic-key` secret.
- **Diff-aware incremental analysis** (`phantom analyze --full`, `--dry-run`) that reads git diffs to skip unchanged captures, reducing API costs for small changes.
- **DiffAnalyzer** classifies file changes as visual/non-visual per project type, maps changed files to affected captures, and recommends skip/incremental/full re-analysis.
- **Per-project analyst state** (`.phantom-state.json`) tracking last commit, manifest hash, cumulative costs/tokens, and analysis counts with atomic writes.
- **QualityChecker** for post-capture screenshot validation: blank detection, entropy, file size, transparency, color variety, dimensions, and aspect ratio checks.
- **Consistency checking** across multiple screenshots (size variance, aspect ratio uniformity).
- **`phantom diff`** command for quick diff analysis without API calls — shows recommendation and affected captures.
- **Enhanced `phantom costs`** with per-project breakdown: full/incremental/skipped runs, cumulative cost, average cost per run.
- **Incremental capture support** in orchestrator via `capture_ids` filtering on `JobOptions`.
- **GitHub Actions state caching** for incremental CI runs via `actions/cache@v4` on `.phantom-state.json`.
- **191 new tests** (180 unit + 11 integration) covering analyst engine, documentation writer, diff analyzer, quality checker, state management, and incremental analysis.

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

[0.3.0]: https://github.com/wbuscombe/phantom/releases/tag/v0.3.0
[0.2.0]: https://github.com/wbuscombe/phantom/releases/tag/v0.2.0
[0.1.0]: https://github.com/wbuscombe/phantom/releases/tag/v0.1.0
