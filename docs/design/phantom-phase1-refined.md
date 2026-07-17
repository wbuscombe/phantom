# Phantom — Refined Phase 1: Foundation

**Goal:** One project, end-to-end from `phantom run` to git commit, with publication-quality output and a tight developer feedback loop.

**Duration estimate removed per project convention — scope defined by exit criteria.**

---

## Design Changes from Original Phase 1

| Original Phase 1 | Refined Phase 1 | Rationale |
|-------------------|-----------------|-----------|
| Darkroom: resize + optimize only | Darkroom: resize + shadow + optimize + SSIM diff | Shadow is Phantom's signature visual treatment — deferring it makes the first demo look unfinished. SSIM diff prevents bloat from day one. |
| No README update | Sentinel-based README update | Without this, users must manually update image references — defeating the purpose. |
| No `phantom init` | Include `phantom init` | Critical for onboarding. A user's first interaction with Phantom should produce a working manifest in under a minute. |
| No `--dry-run` | Include `--dry-run` | Essential for manifest development. Users shouldn't have to push commits to verify their manifest works. |
| No `--capture <id>` | Include `--capture <id>` | Saves minutes during manifest iteration — re-running 1 capture instead of 5. |
| Display Manager (Xvfb) included | Deferred to Phase 2 | The Web Runner uses Playwright's built-in headless Chromium — no Xvfb needed. Display Manager is only needed for Desktop Runner (Phase 2). |
| No perceptual diff | SSIM diff included | Prevents git bloat from the very first run. Trivial to implement with scikit-image — one function call. |

---

## Phase 1 Scope — Definitive

### In scope:

**CLI Layer**
- `phantom run --project <name> [--manifest <path>] [--dry-run] [--capture <id>] [--skip-publish] [--force]`
- `phantom validate <manifest-path>`
- `phantom init` (interactive manifest scaffolding)
- `phantom status` (show last run, tracked projects)
- Click + Rich for CLI framework. Structured output via Rich console.

**Models (Pydantic v2)**
- Complete manifest schema (all fields from spec section 5.2, including enhancements: skip, depends_on, parallel, retry, groups, capture_defaults)
- Validation: required fields, type checking, unique capture IDs, output path safety, CSS selector syntax
- Only `setup.type: web` is functionally supported — other types parse and validate but raise "not yet implemented" at runtime

**Conductor**
- CLI trigger only (no webhooks, no cron)
- Manifest loading and validation
- Job state machine (QUEUED → CLONING → BUILDING → SEEDING → LAUNCHING → CAPTURING → PROCESSING → PUBLISHING → TEARDOWN → COMPLETED, plus FAILED and RETRYING)
- `fcntl.flock()` based locking (ADR-011)
- State persistence (last captured SHA per project, run history)

**Workspace Manager**
- Clone to ephemeral directory (`/var/phantom/workspace/{project}-{hash}/`)
- Fetch previous screenshots for diff comparison
- Cleanup after completion (always, including on failure)

**Web Runner**
- Playwright with headless Chromium (ADR-012: one browser instance, fresh context per capture)
- Actions: navigate, route, click, hover, type, press, keyboard_shortcut, scroll, scroll_to, wait, wait_for, wait_for_network, set_theme, set_viewport, evaluate, set_cookie, conditional (with else)
- Determinism injection: frozen animations, deterministic Date, deterministic Math.random, hidden carets, hidden scrollbars
- Ready checks: http, tcp, stdout_match, delay
- Per-capture retry with configurable backoff
- Diagnostic screenshot on failure

**Fixture System**
- Types: script, http, file_copy
- Sequential execution with per-fixture timeout
- Idempotency is the manifest author's responsibility; Phantom logs execution

**Darkroom Pipeline**
- Color normalize (sRGB enforcement via Pillow)
- EXIF strip (Pillow metadata removal)
- Crop (manual region only — auto-crop deferred to Phase 2)
- Resize (DPR-aware, max_width enforcement)
- Drop shadow (Pillow-based, configurable parameters per ADR-007)
- Optimize (pngquant + oxipng for PNG; WebP conversion if `format: webp`)
- SSIM diff (scikit-image, configurable threshold, ignore regions)

**Publisher**
- Sentinel-based README updater (scan for `<!-- phantom:id -->` pairs, replace content)
- Retina image tags (`<img src="..." width="..." alt="...">`)
- Git operations: add changed files, compose commit message, commit with configurable author, push
- Stale screenshot detection and cleanup (`publishing.cleanup_stale`)
- `[skip ci]` tag (configurable via `publishing.ci_skip_tag`)
- Dry-run mode: runs entire pipeline but skips git commit/push, prints what would be committed
- `--skip-publish`: captures and processes but doesn't touch git at all

**Logging**
- `structlog` with JSON lines to file + human-readable to stderr
- Log levels: debug, info, warning, error
- Secret redaction (GitHub tokens, Bearer tokens)
- Run summary report after each job

**Testing**
- Unit tests: manifest parsing (valid + invalid), action validation, darkroom stage math, README sentinel parsing, commit message generation, log redaction
- Integration tests: Web Runner against a minimal test HTTP server (included in `tests/fixtures/test-web-app/`), Darkroom pipeline against reference images
- Test fixtures: valid/invalid manifests, minimal Express app, reference screenshots

### Out of scope (deferred):

| Deferred | Target Phase |
|----------|-------------|
| Terminal Runner (pyte + silicon) | Phase 2 |
| Desktop Runner (Xvfb + xdotool + maim) | Phase 2 |
| Docker Runner (compose lifecycle) | Phase 2 |
| Display Manager (Xvfb lifecycle) | Phase 2 |
| Auto-crop detection algorithm | Phase 2 |
| Annotation system (arrows, highlights) | Phase 4 |
| Webhook listener | Phase 3 |
| Cron/schedule triggers | Phase 3 |
| PR-based publishing | Phase 3 |
| Job queue (multiple projects) | Phase 3 |
| `phantom gc` command | Phase 3 |
| `phantom diff` command | Phase 3 |
| AI Director | Phase 5 |
| Screenshot secret scanning (OCR) | Phase 3 |
| PyPI/Docker distribution | Phase 4 |
| Shell completions | Phase 4 |

---

## Phase 1 Sub-Phases

### 1A: Project Skeleton + Models

**Delivers:** A valid Python package that parses manifests and exits.

```
- pyproject.toml (project metadata, dependencies, entry points)
- ruff.toml (linter config)
- src/phantom/__init__.py (version)
- src/phantom/cli.py (Click group with run, validate, init, status stubs)
- src/phantom/models.py (Pydantic v2 models for entire manifest schema)
- src/phantom/exceptions.py (PhantomError hierarchy)
- tests/conftest.py
- tests/unit/test_models.py (comprehensive manifest parsing tests)
- tests/fixtures/manifests/*.yml (valid + invalid test manifests)
```

**Exit criteria:**
- `phantom validate tests/fixtures/manifests/valid-web.yml` → exit 0 with structured output
- `phantom validate tests/fixtures/manifests/invalid-missing-project.yml` → exit 1 with clear error
- `pytest tests/unit/test_models.py` → all pass
- `ruff check src/` → clean
- `mypy src/` → clean

### 1B: Workspace + Web Runner

**Delivers:** Raw screenshots captured from a live web app.

```
- src/phantom/conductor/workspace.py
- src/phantom/conductor/requirements.py (check node, npm, etc.)
- src/phantom/conductor/fixtures.py
- src/phantom/runners/base.py (BaseRunner ABC, CaptureResult, RunnerContext)
- src/phantom/runners/actions.py (action type executor)
- src/phantom/runners/web.py (Playwright web runner)
- tests/fixtures/test-web-app/ (minimal Express app with known UI)
- tests/integration/test_web_runner.py
```

**Exit criteria:**
- Web Runner builds and launches the test web app
- All action types execute without error against the test app
- `raw/` directory contains non-blank PNGs at correct dimensions
- Ready check (http type) works with timeout and interval
- Fixtures (all three types) execute in correct order
- Diagnostic screenshot is captured when a capture fails
- `pytest tests/integration/test_web_runner.py` → all pass

### 1C: Darkroom Pipeline

**Delivers:** Publication-quality processed screenshots.

```
- src/phantom/darkroom/base.py (DarkroomStage ABC)
- src/phantom/darkroom/pipeline.py
- src/phantom/darkroom/stages/color.py
- src/phantom/darkroom/stages/exif.py
- src/phantom/darkroom/stages/crop.py
- src/phantom/darkroom/stages/resize.py
- src/phantom/darkroom/stages/border.py (drop shadow)
- src/phantom/darkroom/stages/optimize.py
- src/phantom/darkroom/stages/diff.py (SSIM)
- tests/unit/test_darkroom_stages.py
- tests/integration/test_darkroom_pipeline.py
- tests/fixtures/screenshots/ (reference input/output pairs)
```

**Exit criteria:**
- Drop shadow renders correctly with transparent background
- 2x input resized to max_width preserving aspect ratio
- pngquant + oxipng reduce file size by >30% on test image
- SSIM diff correctly identifies changed vs unchanged screenshots (threshold 0.95)
- SSIM diff returns "changed" for new captures (no previous version)
- EXIF metadata is stripped from output
- Each stage is independently testable (unit tests per stage)
- Full pipeline produces output matching reference within SSIM 0.99

### 1D: Publisher + Conductor Integration

**Delivers:** End-to-end `phantom run` producing a git commit.

```
- src/phantom/publisher/git.py
- src/phantom/publisher/readme.py
- src/phantom/conductor/orchestrator.py
- src/phantom/conductor/state.py
- src/phantom/conductor/manifest.py (loader wrapping models.py)
- src/phantom/utils/logging.py
- src/phantom/utils/process.py
- tests/unit/test_readme_updater.py
- tests/unit/test_git_operations.py
- tests/integration/test_publisher.py
- tests/e2e/test_full_run.py
```

**Exit criteria:**
- Sentinels in README are correctly updated with `<img>` tags
- Retina images use `width` attribute at logical (1x) dimensions
- Commit message includes project name, changed/unchanged counts, diff percentages
- Configurable commit author appears in git log
- `[skip ci]` tag (or configured alternative) is in commit message
- Stale screenshot cleanup removes orphaned files
- `--dry-run` completes full pipeline, prints report, makes zero git changes
- `--capture dashboard` runs only the specified capture
- `--skip-publish` captures and processes but makes no git changes
- `--force` commits even when below diff threshold
- `fcntl.flock()` prevents concurrent runs
- State file tracks last captured SHA
- `phantom status` shows last run summary
- `pytest tests/e2e/test_full_run.py` → passes (against test-web-app with local git repo)

### 1E: Init + Polish

**Delivers:** Onboarding experience and production readiness.

```
- src/phantom/cli.py (init command implementation)
- src/phantom/utils/validation.py
- .github/workflows/ci.yml
- tests/unit/test_init.py
```

**Exit criteria:**
- `phantom init` produces a valid `.phantom.yml` via interactive prompts
- Generated manifest passes `phantom validate`
- CI pipeline runs lint + unit + integration + e2e on push
- `ruff check .` → clean across entire codebase
- `mypy src/` → clean across entire codebase
- All tests pass in CI (Ubuntu latest)

---

## Phase 1 Dependency Graph

```
1A: Skeleton + Models
 │
 ├──► 1B: Workspace + Web Runner  (needs models for manifest)
 │     │
 │     └──► 1C: Darkroom Pipeline  (needs raw screenshots to process)
 │           │
 │           └──► 1D: Publisher + Conductor  (needs processed assets to commit)
 │                 │
 │                 └──► 1E: Init + Polish  (needs working pipeline for validation)
 │
 └──► (1C can start in parallel if using reference test images instead of live captures)
```

---

## Phase 1 Dependencies (Python)

```toml
[project]
name = "phantom-docs"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "click>=8.1",
    "rich>=13.0",
    "pydantic>=2.5",
    "ruamel.yaml>=0.18",
    "structlog>=24.1",
    "Pillow>=10.2",
    "scikit-image>=0.22",
    "playwright>=1.41",
    "gitpython>=3.1",
    "httpx>=0.26",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "ruff>=0.2",
    "mypy>=1.8",
    "pytest-cov>=4.1",
]
```

## Phase 1 System Dependencies

| Dependency | Required | Installation | Checked by |
|-----------|----------|-------------|------------|
| Python 3.12+ | Yes | System | `phantom` startup |
| Chromium (via Playwright) | Yes | `playwright install chromium` | Web Runner setup |
| pngquant | Yes | `apt install pngquant` or `brew install pngquant` | Darkroom optimize stage |
| oxipng | Yes | `cargo install oxipng` or `apt install oxipng` | Darkroom optimize stage |
| Git | Yes | System (pre-installed) | Publisher startup |
| Node.js 18+ | For JS projects | System/nvm | Conductor requirements check |

---

## Phase 1 Test Web App

A minimal Express app included at `tests/fixtures/test-web-app/` for integration and e2e testing:

```
test-web-app/
├── package.json
├── server.js          # Express server, port from env PORT (default 3456)
└── public/
    ├── index.html     # Dashboard page with .device-card elements
    ├── settings.html  # Settings page with #advanced-settings section
    └── style.css      # Dark theme, deterministic layout (no animations)
```

**Requirements:**
- Supports `prefers-color-scheme` media query for dark/light switching
- Has `.device-card` elements for `wait_for` testing
- Has clickable elements for action testing
- Has a scrollable section for `scroll_to` testing
- Has a form input for `type` action testing
- Responds to `/api/seed` POST for fixture testing (returns 201)
- No external dependencies (just Express)
- Deterministic layout (fixed data, no randomness, no animations)

**Why not a static HTML file?** The test app needs to support HTTP fixtures, ready checks against a running server, and navigation between routes. A static file can't test these paths.

---

## First Real Target

After the test-web-app validates the pipeline, the first real project to onboard is a
representative dashboard app (`example-app`). This requires:

1. **Demo mode support in the app** — `PHANTOM_MODE=1` environment variable that:
   - Bypasses external device/service discovery (mocks the list)
   - Seeds the UI with realistic demo data
   - Disables any real network calls to third-party APIs

2. **Seed script** — `scripts/seed-demo.js` that populates the app with:
   - 3 demo devices (Living Room, Office, Bedroom)
   - 2 active sessions with sample content columns
   - Realistic usernames, avatars, and post content

3. **`.phantom.yml`** — Manifest targeting 4-5 hero captures:
   - Dashboard (populated, dark mode)
   - Active session
   - Device setup flow
   - Mobile admin view
   - Settings panel

This work happens in the target app's repo, not in Phantom. It validates that the Demo Readiness Standard (section 11) is achievable for a real project.
