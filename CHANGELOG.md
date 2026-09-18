# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `SECURITY.md` — vulnerability-reporting policy and supported-versions table; linked from the README.
- `.pre-commit-config.yaml` mirroring the CI ruff gate (opt-in via `pre-commit install`); documented in CONTRIBUTING.
- README: CI status badge, an **AI Analyst** section, a **Security** section, the `desktop`
  runner, the `analyze` / `diff` / `costs` / `snapshots` / `rollback` commands, the
  `--ai-*` / `--review` run flags, and the `ANTHROPIC_API_KEY` variable — all previously
  shipped but undocumented.
- ARCHITECTURE.md: the AI Analyst subsystem, `contract.py`, snapshots, utilities, and the exception hierarchy.
- `docs/SECURITY-PRACTICES.md`: a "Product Security Model" section (webhook HMAC, network posture, secret redaction).
- pyproject `[project.urls]` `Changelog` link and `Programming Language :: Python :: 3` /
  `:: 3 :: Only` / `Operating System :: OS Independent` classifiers.

### Changed
- `Development Status` classifier `3 - Alpha` → `4 - Beta`.
- `phantom doctor` no longer prints internal dependency-probe log lines above its results
  table (added an optional `level` override to `configure_logging`; use `-v` for detail).
- Consolidated the ruff configuration into `ruff.toml` (removed the duplicate, unused block
  from `pyproject.toml`); `mypy` config now sets `ignore_missing_imports` so local runs match CI.
- Genericized example / fixture project names and local paths in docs and tests.
- CI: the `test` job now runs the contract-conformance tier (`pytest tests/contract/`) as its
  own step, so a contract regression fails the build. The tier was previously not run in CI.
  pytest's no-tests-collected exit status (5) fails the step, so a path that collects nothing
  cannot pass.

### Fixed
- Onboarding and collaborator docs now state `Python 3.12+` (matching `requires-python`)
  and pin `phantom-docs>=0.4,<0.5` (the previous `>=0.3,<0.4` excluded the shipped 0.4.0).
- Corrected the Stage-3 manifest templates in `docs/onboarding-prompt.md` (web / TUI /
  desktop) — all three now pass `phantom validate`. They previously used an outdated schema
  (top-level `type`, `setup.install`, string `run`, `ready_check.strategy`/`timeout_ms`,
  top-level `web:` block, implicit-key actions) that the tool rejects.
- **Installing Phantom from a git ref with an AI feature enabled no longer fails.** When
  `phantom-version` was a git ref and `ai-analyst`, `ai-document` or `ai-auto` was set,
  `phantom-capture.yml`'s *Install Phantom* step composed
  `git+https://github.com/wbuscombe/phantom.git@<ref>[ai]`. pip reads everything after the
  URL's last `@` as the revision, so it tried to check out a nonexistent ref `<ref>[ai]`,
  with no extra, and that install could never succeed. Git refs now install as a PEP 508
  direct reference with the extra on the package name:
  `phantom-docs[ai] @ git+https://github.com/wbuscombe/phantom.git@<ref>`, or
  `phantom-docs @ ...` without AI, which installs the same package as before. Input names,
  accepted `phantom-version` forms and validation are unchanged, and version-specifier and
  exact-version installs compose byte-identical targets. The Security entry's "every
  accepted form installs exactly what it installed before" therefore holds except for this
  form, which never installed. Covered by `tests/unit/test_capture_workflow_install.py`.

### Removed
- An unreferenced sample screenshot binary (`Sample Generated Media/`).

### Security
- **CI now gates on workflow static analysis.** A `workflow-static-analysis` job runs
  `zizmor` and `actionlint` over every file in `.github/workflows/` on each push and pull
  request. The threshold is deliberate: a finding of High or above fails the build, while
  Medium and below are printed in the job log without failing it, so they stay visible
  rather than rotting unseen and can be closed on their merits later, after which the
  threshold tightens. Gating Medium today would have required either an unbounded
  remediation pass inside a gating change or a baseline file, which is suppression under
  another name; nothing here is suppressed, baselined, ignored, or downgraded. The scan
  runs online, because zizmor can only report the `impostor-commit` class when it can
  query upstream refs (see the rust-toolchain entry below). Given no token it falls back
  to offline mode, reports nothing and exits 0, so the job checks for the token first and
  fails closed rather than accepting that falsely clean pass. Both tools are pinned
  (`zizmor==1.30.1`, `actionlint-py==1.7.12.24`) so the gate's meaning cannot change
  without a commit, and the job requests only `contents: read`. The gate turns a pull
  request red but does not block a merge until it is marked a required check in branch
  protection, which is a separate settings change.
- **The capture step no longer relies on word splitting to pass its flags.**
  `phantom-capture.yml`'s *Run captures* step built its flags as a string and invoked
  `phantom run $FLAGS`, an unquoted expansion (shellcheck SC2086, reported by actionlint at
  `phantom-capture.yml:250`). The value is composed only of literal flag text (the four
  `${{ inputs.* }}` expressions in that block are `type: boolean` and only select which
  literal flags are appended), so the finding is a quoting-correctness issue, not the
  caller-controlled-value class fixed in the *Install Phantom* and *Create GitHub Release*
  steps. It is fixed as such: the flags are now a bash array expanded as
  `"${FLAGS[@]}"`, so no value is ever word-split or glob-expanded. Quoting the string
  instead (`"$FLAGS"`) would have collapsed every flag into one argument; the argument
  vector is unchanged for all sixteen input combinations, verified by
  `tests/unit/test_capture_workflow_flags.py`, which executes the step's own script.
- **CI and release checkouts no longer persist the job's credential in the git config.**
  `actions/checkout` writes an authentication header into `.git/config` by default, where
  any later step, or anything that archives the workspace, can read it (zizmor
  `artipacked`). The four checkouts whose jobs never use it now set
  `persist-credentials: false`: both `ci.yml` jobs (lint and test run only ruff, mypy,
  pip and pytest) and both `release.yml` checkouts (the build job builds and uploads an
  artifact; the github-release job's `gh release create` authenticates through `GH_TOKEN`).
  The capture workflow's checkout keeps the credential deliberately: its publish steps run
  `git push`, which uses exactly that persisted header.
- **The reusable workflow no longer interpolates `phantom-version` into a shell script.**
  `phantom-capture.yml`'s *Install Phantom* step substituted the caller's input directly
  into the script text, so any repository calling the workflow could run arbitrary commands
  on the runner with the job's `contents: write` / `pull-requests: write` token and any
  secret passed to it. The value (and the `ai-*` flags used by the same step) now reaches
  the shell only through a step-level `env:` mapping, and is validated before any install
  target is built: a PyPI version constraint on release numbers (e.g. `>=0.4,<0.5`,
  `==0.4.*`), an exact `N.N.N` version (installed as `==N.N.N`), or a git ref limited to
  `A-Za-z0-9._/-` with no leading `-`, no leading, trailing or repeated `/`, and no `..`.
  Every accepted form installs exactly what it installed before. Anything else, including
  an empty value, now fails the step before `pip` runs; values that used to be passed
  through but are outside those forms (spaces, prerelease/local/epoch versions, four-part
  versions, `===`, caller-supplied extras or markers) are rejected. Covered by
  `tests/unit/test_capture_workflow_install.py`, which executes the step's own script.
- **The release workflow no longer interpolates the tag name into a shell script.**
  `release.yml`'s *Create GitHub Release* step substituted `github.ref_name` directly into
  the script text. Git permits shell metacharacters in tag names, so a crafted `v*` tag push
  could run commands on the runner with the job's token (`contents: write`, `id-token: write`).
  The step now reads the tag from the runner-provided `GITHUB_REF_NAME` environment variable,
  double-quoted, so the name reaches `gh` as one literal argument. Ordinary tags create the
  same release as before. Covered by `tests/unit/test_release_workflow_tag.py`, which
  executes the step's own script.
- **The release workflow's token is now scoped per job.** `release.yml` granted
  `contents: write` and `id-token: write` at the workflow level, so all three jobs held both,
  including `build`, which installs tooling from PyPI and runs the freshly built package. The
  workflow level now grants nothing, and each job requests only what its own steps use:
  `build` gets `contents: read` (checkout), `publish` gets `id-token: write` (PyPI Trusted
  Publishing and PEP 740 attestations), and `github-release` gets `contents: write`
  (`gh release create`). The release path is not exercised by this change; if a release fails
  on permissions, widen only the grant that failed. Covered by
  `tests/unit/test_release_workflow_permissions.py`, which reads the workflow file.
- **The pinned `dtolnay/rust-toolchain` action now references a commit that upstream still
  keeps on a live branch.** `phantom-capture.yml`'s *Setup Rust toolchain (tui)* step pinned a
  commit that upstream later orphaned by force-pushing the branch it came from. GitHub resolves
  a commit across a repository's whole fork network, so such a pin keeps resolving and keeps
  installing long after no branch or tag in the upstream repository contains it. By inspection
  it is then indistinguishable from a commit that never belonged to the project, and no one
  upstream is maintaining the code it points at. The pin now tracks the current tip of
  `stable`, with the ref name and the date it was taken recorded in a comment beside it, so the
  next refresh is a one-line change. Static analysis reports this class as `impostor-commit`,
  but only when it can query the upstream refs: an offline run of the same scanner over the
  same file reports nothing at all. Because this upstream rebases `stable` routinely, the pin
  is expected to need refreshing again.

### Documentation
- CONTRACT.md §1: clarify that a consumer making **zero** outbound network calls trivially
  satisfies the allowlist (it is a ceiling, not a requirement) — usability note from the
  Network Monitor pilot. Additive clarification, **no contract-version change**.
- CI: bump all workflow action pins (checkout/setup-python/upload-artifact/download-artifact/
  cache) to current Node-24 releases (were Node-20-deprecated); `ci.yml`'s unpinned `@v4`/`@v5`
  now SHA-pinned too.

## [0.4.0] - 2026-07-11

This release freezes the **Phantom Consumer Contract at `contract-version: 1.0.0`**
(see [`CONTRACT.md`](CONTRACT.md)) — the interface consumer apps and the CI
smoke job depend on. The contract version is tracked independently of the
package version and is exposed as `phantom.__contract_version__`.

### Added

- **`CONTRACT.md` (contract-version 1.0.0)** — the frozen boot / config / health
  / artifact / versioning contract, with an explicit non-goals section.
- **`phantom.contract` module** — the machine-checkable source of truth:
  `CONTRACT_VERSION`, `PHANTOM_MODE_ENV`, `is_phantom_mode()`, `app_env()`,
  `DEFAULT_ARTIFACT_DIR`, `DEFAULT_READY_TIMEOUT_SECONDS`, `LOOPBACK_HOSTS`,
  `manifest_allowlist()`, `is_host_allowed()`. Package now exposes
  `phantom.__contract_version__` / `phantom.CONTRACT_VERSION`.
- **Contract conformance suite** (`tests/contract/`, 77 tests) mechanically
  verifying every Part-2 promise: mode detection, `PHANTOM_MODE=1` injection at
  all four runners' spawn points, schema parsing incl. unknown-key tolerance,
  ready-check timeout declaration, artifact path safety, and the network
  allowlist.
- **`docs/smoke-job-spec.md`** — specification for the reusable CI smoke job
  Step 3 will implement (inputs, steps, pass/fail semantics, consumer
  requirements), written against contract 1.0.0.

### Changed

- **`PHANTOM_MODE=1` is now guaranteed by Phantom itself** for every launched
  consumer app, across the `web`, `docker-compose`, `tui`, and `desktop`
  runners (via `phantom.contract.app_env()`). Previously demo mode activated
  only if the invoking shell or the manifest's `setup.run.env` set the
  variable; it is now injected by default (a manifest's explicit `run.env` may
  still override it). This makes the boot contract hold for direct/local
  invocations, not just the reusable CI workflow.
- **Version bumped to 0.4.0.** Consumers pin `phantom-docs==0.4.*` and assert
  `phantom.__contract_version__ == "1.x"` ([`CONTRACT.md` §5](CONTRACT.md#5-versioning-rules)).

### Security

- **Publish quality gate** (`Orchestrator._publish`): `phantom run` no longer commits or pushes a capture that fails an **error-severity** quality check (blank / too-small / bad-dimensions). Pass `--force` to publish anyway (for intentional low-entropy frames such as splash screens). Warning-severity issues remain advisory and still publish. CI is unaffected because it runs with `--skip-publish`. A blocked publish exits non-zero and sets `JobReport.blocked_by_quality`.
- **CI screenshot artifact is now opt-in and success-only**: the reusable `phantom-capture.yml` uploads `docs/screenshots/` as a workflow artifact only when the new `upload-screenshots-artifact` input is `true` **and** the run succeeded (previously `if: always()`). This prevents a sensitive or failed frame from becoming externally downloadable before review — independent of the `pr` publish gate.
- **CI commit path now fails closed on quality**: the local publish gate above does not run in CI (which uses `--skip-publish`), so previously the workflow's own git steps committed a frame regardless of quality. The reusable `phantom-capture.yml` now runs `phantom run --skip-publish --fail-on-quality-error` — an error-severity capture exits non-zero, fails the job, and the now-explicitly `success()`-gated commit/push steps are skipped, so nothing is committed. New `force-publish` workflow input (and `phantom run --fail-on-quality-error` CLI flag) override the gate; `--force` still bypasses everything.

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
