# Phantom Spec — Enhancements & Fixes

**Applied against:** v0.2.0-draft (2026-02-12)
**Date:** 2026-02-12

This document specifies all changes to apply to the base spec. Organized by section.

---

## Section 3: New ADRs

### ADR-011: Flock-Based Process Locking
**Context:** The spec uses file-existence locking (`/var/phantom/phantom.lock`) with a 1-hour stale detection heuristic. If the Phantom process is killed (OOM, `kill -9`, power loss), the lock file persists and blocks subsequent runs until the age heuristic kicks in.
**Decision:** Use `fcntl.flock()` (Unix advisory file lock) instead of file-existence checks.
**Rationale:** `flock` is automatically released by the kernel when the holding process exits, regardless of how it exits. No stale lock detection needed. The lock file still exists on disk (for visibility via `ls`) but the lock state is kernel-managed. Python's `fcntl.flock()` maps directly to the syscall. The `phantom status` command can test the lock non-destructively via `LOCK_NB`.
**Consequences:** Not portable to Windows (acceptable — Xvfb doesn't exist on Windows either). Lock semantics are per-process, not per-thread, which matches Phantom's single-job concurrency model.

### ADR-012: Browser Instance Reuse Across Captures
**Context:** The Web Runner needs to capture multiple screenshots per project. Each capture could launch a new browser process or reuse one.
**Decision:** Launch one Chromium instance per job. Each capture gets a fresh `BrowserContext` (isolated cookies, storage, service workers) but shares the browser process.
**Rationale:** Chromium startup is 1-3 seconds. For a project with 10 captures, that's 10-30 seconds of pure overhead. Browser contexts provide full isolation (equivalent to incognito windows) without the process startup cost. Playwright's context API is designed exactly for this pattern.
**Consequences:** A browser crash (rare) fails all remaining captures in the job. This is acceptable — a crash indicates a systemic problem that would likely affect subsequent launches anyway. The runner should catch the crash, log diagnostics, and transition the job to FAILED.

### ADR-013: SSIM over Pixelmatch for Perceptual Diff
**Context:** The spec references `pixelmatch` for perceptual diffing, but there is no well-maintained Python binding. Options: subprocess to Node CLI, pure-Python reimplementation, or use SSIM (Structural Similarity Index) via scikit-image.
**Decision:** Use SSIM via `scikit-image.metrics.structural_similarity` as the default diff algorithm. Keep pixelmatch as an option via Node subprocess for users who prefer pixel-level comparison.
**Rationale:** SSIM is available as a single function call in scikit-image (already a common Python dependency). It produces a 0-1 similarity score that maps naturally to the threshold model. It's more perceptually meaningful than pixel-level comparison — it accounts for luminance, contrast, and structure rather than raw pixel differences. scikit-image is pip-installable with no native compilation issues on Linux.
**Consequences:** The default `diff.algorithm` changes from `pixelmatch` to `ssim`. Threshold semantics invert: SSIM returns similarity (1.0 = identical), so the threshold represents the *minimum similarity* to consider unchanged (default 0.95, equivalent to the old 5% diff threshold). pixelmatch remains available as `diff.algorithm: pixelmatch` for backward compatibility, requiring Node.js at runtime.

---

## Section 4.2: State Machine — Add RETRYING State

Replace the state machine note with:

```
Notes:
- FAILED can occur at any stage. Teardown always runs.
- RETRYING is entered when a transient failure triggers an automatic retry.
  The job returns to the stage that failed. Retry count is tracked per-stage.
- CAPTURING is partially-successful: individual captures can fail
  while others succeed. The job continues.
- State transitions are logged with timestamps and retry counts.
- State is persisted to disk so interrupted runs can report
  what stage they died in.
```

Add RETRYING to the diagram:

```
     FAILED ◄─── (max retries exceeded)
       ▲
       │
     RETRYING ◄── (transient failure at any stage)
       │
       └──────► (re-enter failed stage)
```

---

## Section 4.3: Concurrency — Fix Locking, Persist Queue

Replace file-based lock paragraph with:

**Implementation:** Process-level lock via `fcntl.flock()` on `/var/phantom/phantom.lock` (see ADR-011). If a run is already in progress, new triggers are queued to a persistent file (`/var/phantom/state/queue.json`, max configurable depth, default 5). The conductor processes the queue sequentially. On startup, the conductor checks the queue file and resumes any pending jobs, ensuring no work is lost across restarts.

**Queue persistence format:**

```json
{
  "queue": [
    {
      "project": "example-app",
      "ref": "v2.1.0",
      "trigger": "release",
      "queued_at": "2026-02-12T03:00:00Z"
    }
  ]
}
```

---

## Section 5.2: Manifest Schema — Enhanced Fields

### New capture fields (add to capture definition):

```yaml
captures:
  - id: dashboard
    # ... existing fields ...

    # NEW: Temporarily disable this capture without removing it.
    skip: false                          # default false. If true, capture is skipped with a log message.

    # NEW: Declare dependency on another capture's state.
    # When set, this capture runs in the same browser context as the dependency
    # (no fresh context), preserving navigation state, cookies, and DOM.
    depends_on: null                     # Capture ID, or null for independent (default).

    # NEW: Allow parallel execution with other independent captures.
    parallel: false                      # default false. Only effective when depends_on is null.

    # NEW: Per-capture format override.
    format: null                         # png | webp | null (inherit from processing.format)

    # NEW: Per-capture retry configuration.
    retry:
      max_attempts: 3                    # Total attempts (1 = no retry). Default from capture_defaults.
      backoff_ms: 1000                   # Wait between retries. Doubles each attempt.
```

### New capture_defaults fields:

```yaml
capture_defaults:
  # ... existing fields ...
  retry:
    max_attempts: 3
    backoff_ms: 1000
```

### Enhanced publishing section:

```yaml
publishing:
  branch: "main"
  commit_author:                         # NEW: Configurable commit author.
    name: "Phantom Bot"                  # Default: "Phantom Bot"
    email: "phantom@noreply"             # Default: "phantom@noreply"
  ci_skip_tag: "[skip ci]"              # NEW: Configurable CI skip tag.
                                         # GitHub: "[skip ci]", GitLab: "[ci skip]",
                                         # none: "" (empty string to omit)
  commit_message: "docs(screenshots): update via Phantom"  # ci_skip_tag appended automatically
  strategy: direct
  readme_update: true
  cleanup_stale: true                    # NEW: Remove screenshot files that no longer
                                         # correspond to any capture in the manifest.
                                         # Compares files in output directories against
                                         # capture output paths. Default true.
```

### New capture groups (add to top-level schema):

```yaml
# NEW: Optional capture grouping for selective runs.
# Usage: phantom run --group hero-shots
groups:
  hero-shots:
    - dashboard
    - casting-active
  mobile:
    - mobile-admin
  all-settings:
    - settings
```

---

## Section 5.3: Action Types — Add `else` to Conditional

Replace the conditional action:

```yaml
- type: conditional
  if:
    selector_exists: ".onboarding-modal"
  then:
    - { type: click, selector: ".dismiss-onboarding" }
    - { type: wait, ms: 500 }
  else:                                  # NEW: Optional else branch.
    - { type: wait, ms: 100 }           # Execute if condition is false.
```

---

## Section 5.7: Docker Compose — Fix Duplicate Key Bug

The Docker Compose example has `setup:` defined twice. Fix by merging teardown into the first `setup:` block:

```yaml
setup:
  type: docker-compose
  compose_file: "docker-compose.yml"
  compose_profiles: ["demo"]
  services:
    - api
    - frontend
    - redis
  ready_check:
    type: http
    url: "http://localhost:8080"
    timeout: 60
  teardown:                              # FIXED: Merged into single setup block.
    - "docker compose down -v --remove-orphans"
```

---

## Section 6.1: Conductor — Fix Clone Depth, Add Runner Timeout

### Fix shallow clone:

Replace `git clone --depth 1` strategy with:

```
Clone strategy:
- git clone --depth 1 --branch {ref} {repo} repo/
- For previous screenshot fetch: git fetch --depth 2 origin {branch}
  Then: git show HEAD~1:{path} for each screenshot path.
  If HEAD~1 doesn't exist (first commit on branch), all captures are
  treated as new (always "changed").

Alternative (more efficient for repos with many screenshots):
- Before cloning, fetch only the previous screenshot blobs:
  git archive --remote={repo} {branch} -- docs/screenshots/ | tar x -C previous/
  This avoids deepening the clone entirely.
```

### Add runner-level timeout:

Add to conductor configuration:

```yaml
runner_timeout: 300                      # NEW: Max seconds for entire runner session
                                         # (build + seed + launch + all captures).
                                         # Kills the runner if exceeded. Default 300 (5 min).
                                         # Override per-project in manifest:
                                         # setup.runner_timeout: 600
```

---

## Section 6.3: Workspace Manager — Fix Previous Fetch

Replace the "Previous versions" paragraph:

**Previous versions** are fetched via `git archive` from the remote before the clone is deepened, or via `git show` after a `git fetch --depth 2`. The fetch strategy is chosen based on the number of screenshots: for fewer than 20 files, individual `git show` calls are faster; for more, `git archive` of the output directory is used. If the previous version doesn't exist (new capture, first run), the capture is always considered "changed."

---

## Section 7.1: Runner Interface — Make run_all Overridable

Change `run_all` from a concrete method to a default implementation that subclasses can override:

```python
    async def run_all(self, ctx: RunnerContext) -> list[CaptureResult]:
        """Execute all captures. Override for custom sequencing (e.g.,
        dependency-aware ordering, parallel execution of independent captures).

        Default: sequential execution in manifest order.
        """
        results = []
        for capture_def in ctx.manifest.captures:
            if capture_def.skip:
                ctx.logger.info("capture_skipped", capture_id=capture_def.id)
                continue
            result = await self.capture(ctx, capture_def)
            results.append(result)
            ctx.logger.info("capture_complete",
                          capture_id=capture_def.id,
                          success=result.success,
                          duration_ms=result.duration_ms)
        return results
```

---

## Section 7.2: Web Runner — Clarify Browser Reuse, Enhance Determinism

Add after "Stack: Playwright (Python async API) with Chromium":

**Browser lifecycle (ADR-012):** One Chromium instance is launched per job via `playwright.chromium.launch()`. Each capture gets a fresh `browser.new_context()` with the capture's viewport, device scale, and color scheme settings. This provides full cookie/storage isolation while avoiding the 1-3 second browser startup overhead per capture. Captures with `depends_on` share their dependency's context instead of creating a new one.

Replace the determinism helpers with an enhanced version:

```javascript
// Freeze CSS animations and transitions
document.querySelectorAll('*').forEach(el => {
  el.style.animationPlayState = 'paused';
  el.style.transitionDuration = '0s';
});

// Deterministic time
const PHANTOM_NOW = new Date('2026-01-15T10:30:00Z');
const OriginalDate = Date;
window.Date = class extends OriginalDate {
  constructor(...args) {
    super(...(args.length ? args : [PHANTOM_NOW]));
  }
  static now() { return PHANTOM_NOW.getTime(); }
};

// Deterministic random (seedable PRNG for consistent layouts)
let _seed = 42;
Math.random = () => {
  _seed = (_seed * 16807) % 2147483647;
  return (_seed - 1) / 2147483646;
};

// Deterministic timezone
// Handled via Playwright's timezoneId context option: 'America/New_York'

// Disable cursor blink
document.querySelectorAll('input, textarea').forEach(el => {
  el.style.caretColor = 'transparent';
});

// Disable scrollbars for clean captures
document.documentElement.style.overflow = 'hidden';
document.documentElement.style.scrollbarWidth = 'none';
```

---

## Section 7.3: Terminal Runner — Specify screen_stable

Add under "Terminal readiness detection":

**`screen_stable` parameters:**
- `stability_window`: Duration in ms during which no new output must arrive (default 500ms).
- `check_interval`: How often to sample the screen buffer (default 100ms).
- `method`: `hash` (CRC32 of the full screen buffer) or `diff` (character-level comparison against previous sample). Default `hash`.
- A screen is "stable" when `stability_window / check_interval` consecutive samples produce identical hashes.
- Maximum wait before declaring timeout: inherits from `ready_check.timeout`.

---

## Section 7.4: Desktop Runner — CDP Fallback

Add under "Tauri hybrid mode":

**CDP connection failure handling:**
If `webview_debug_port` is configured but the CDP connection fails (connection refused, timeout, protocol error):
1. Log a warning with the specific error.
2. Fall back to xdotool-only mode for this capture.
3. The capture proceeds but without DOM-level selectors — only coordinate-based clicks and keyboard shortcuts are available.
4. Actions that require DOM access (e.g., `wait_for` with a CSS selector, `click` with a selector) are skipped with a warning. Coordinate-based alternatives in the action list are used if present.
5. The `CaptureResult.metadata` includes `cdp_fallback: true` so downstream systems know the capture used degraded automation.

---

## Section 8.1: Darkroom Pipeline — New Stages

Insert between Crop and Resize:

```
┌─────────────────────┐
│  1.5 EXIF Strip      │  NEW: Remove all metadata (software, timestamps,
│     Input: PNG       │  GPS, color profile name). Reduces file size by
│     Output: PNG      │  1-5 KB and prevents information leakage.
│                      │  Preserves sRGB color space tag only.
└──────────┬──────────┘
```

Insert before Crop:

```
┌─────────────────────┐
│  0. Color Normalize  │  NEW: Convert to sRGB color space if input uses
│     Input: PNG       │  a different profile (e.g., Display P3 from macOS).
│     Output: PNG      │  Ensures consistent rendering across browsers.
└──────────┬──────────┘
```

Specify auto-crop algorithm:

**Auto-crop detection:** Sample a 1px border on all four edges. If all pixels in a border row/column are within a color distance threshold (Euclidean distance in RGB space < 10) of each other, the border is considered uniform and trimmed. Repeat inward until a non-uniform row/column is found. A minimum padding of 2px is always preserved to prevent edge artifacts.

---

## Section 8.4: Perceptual Diff — SSIM Default

Replace the diff implementation with:

```python
from skimage.metrics import structural_similarity as ssim
from PIL import Image
import numpy as np

async def diff(current: Path, previous: Path, threshold: float,
               ignore_regions: list[Region],
               algorithm: str = "ssim") -> DiffResult:
    """Compare two images and return whether they differ meaningfully.

    Args:
        threshold: For SSIM, minimum similarity to consider unchanged (default 0.95).
                   For pixelmatch, maximum diff percentage (default 0.05).
        algorithm: "ssim" (default, pure Python) or "pixelmatch" (requires Node.js).
    """

    if algorithm == "ssim":
        img_a = np.array(Image.open(current).convert("RGB"))
        img_b = np.array(Image.open(previous).convert("RGB"))

        # Resize previous to match current if dimensions changed
        if img_a.shape != img_b.shape:
            img_b = np.array(Image.open(previous).convert("RGB").resize(
                (img_a.shape[1], img_a.shape[0]), Image.LANCZOS))

        # Apply ignore_region masks
        for region in ignore_regions:
            img_a[region.y:region.y+region.h, region.x:region.x+region.w] = 0
            img_b[region.y:region.y+region.h, region.x:region.x+region.w] = 0

        similarity = ssim(img_a, img_b, channel_axis=2)
        return DiffResult(
            changed=similarity < threshold,
            similarity=similarity,
            diff_pct=1.0 - similarity
        )

    elif algorithm == "pixelmatch":
        # Subprocess to Node CLI — requires node and pixelmatch-cli
        # npm install -g pixelmatch-cli
        result = await run_process(
            "pixelmatch", str(current), str(previous),
            "/dev/null",  # diff output image (unused)
            "--threshold", "0.1",
            timeout=30
        )
        diff_pixels = int(result.stdout.strip())
        total_pixels = img_a.shape[0] * img_a.shape[1]
        diff_pct = diff_pixels / total_pixels
        return DiffResult(changed=diff_pct > threshold, diff_pct=diff_pct)
```

Update the manifest diff config:

```yaml
  diff:
    enabled: true
    threshold: 0.95                      # CHANGED: Now similarity threshold (1.0 = identical)
    algorithm: ssim                      # CHANGED: ssim (default) | pixelmatch
    ignore_regions: []
```

---

## Section 9.1: Publisher — Stale Screenshot Cleanup

Add after the sentinel update logic:

**Stale screenshot cleanup** (when `publishing.cleanup_stale: true`):

```
1. Scan all output directories referenced by the manifest's captures.
2. List all .png and .webp files in those directories.
3. Compare against the set of capture output paths in the manifest.
4. Files present on disk but not referenced by any capture are "stale."
5. Stage stale files for deletion: git rm {stale_path}
6. Include in commit message: "Removed stale: old-feature.png"
7. Safety: only operates on files within directories that contain at least
   one manifest-referenced screenshot. Never touches unrelated directories.
```

**Output path change handling:**

When a capture's `output` path is modified between runs, the Publisher treats the old path as stale (cleaned up) and the new path as a new file (committed). The sentinel in the README is updated to reference the new path.

---

## Section 9.2: Publisher Git — Configurable Author, CI Skip

Replace hardcoded values:

```
3. Commit:
   a. Compose message: "{manifest.publishing.commit_message} {manifest.publishing.ci_skip_tag}"
   b. Include details: "Updated: dashboard, casting-active (2 of 4 captures changed)"
   c. If cleanup_stale removed files: "Removed stale: old-feature.png"
   d. git commit --author="{publishing.commit_author.name} <{publishing.commit_author.email}>"
```

---

## Section 10.3: AI Director Tools — Add Missing Tools

Add to DIRECTOR_TOOLS:

```python
    {
        "name": "scroll",
        "description": "Scroll the page by a given amount or to a specific element.",
        "parameters": {"direction": "up | down", "amount": "int (pixels)",
                       "selector": "string (optional, scroll to element)"}
    },
    {
        "name": "get_url",
        "description": "Get the current page URL and title.",
    },
    {
        "name": "wait",
        "description": "Wait for a specified duration or for an element to appear.",
        "parameters": {"ms": "int", "selector": "string (optional)"}
    },
```

---

## Section 10.4: Director Budget — Token-Aware Cost

Replace the budget paragraph:

The Director tracks two budgets:

1. **Action budget:** Hard limit of `max_exploration_steps` (default 50) actions per run. Each tool call costs 1 step.

2. **Token budget:** Estimated token consumption is tracked per tool call. `observe` calls (which send a screenshot to the LLM) cost ~2000 tokens each. Text-only tool calls cost ~200 tokens. The Director has a `max_tokens` budget (default 500,000) and will stop exploration when 90% of either budget is consumed. Actual API costs are logged per-run for billing visibility.

```yaml
director:
  enabled: false
  model: "claude-sonnet-4-20250514"
  max_exploration_steps: 50
  max_tokens: 500000                     # NEW: Token budget for API cost control.
  # ... rest unchanged
```

---

## Section 12.2: Security — Fix Permissions, Expand Network, Add Screenshot Scanning

### Fix file permissions:

```
- /etc/phantom/.env (640 root:phantom)   # FIXED: 640 allows group read
```

### Expand network allowlist:

Replace the narrow registry list with:

```
Network restrictions (configurable in conductor.yml):

build_phase_allowlist:
  # Package registries and their CDNs (required for npm/pip/cargo install)
  - "registry.npmjs.org"
  - "registry.yarnpkg.com"
  - "*.npmjs.org"                        # npm tarball CDN
  - "pypi.org"
  - "files.pythonhosted.org"            # PyPI package downloads
  - "crates.io"
  - "static.crates.io"                  # Crate downloads
  - "github.com"
  - "*.githubusercontent.com"           # GitHub release assets (esbuild, swc, etc.)
  - "objects.githubusercontent.com"     # Git LFS objects

  # Common binary download hosts (npm postinstall scripts)
  - "registry.npmmirror.com"            # Fallback mirror

capture_phase_allowlist:
  - "localhost"
  - "127.0.0.1"
  - "::1"
  # All other outbound blocked during capture.

# Users can extend via conductor.yml:
# network.build_extra_hosts: ["my-private-registry.com"]
```

### Add screenshot secret scanning:

```
Screenshot content scanning:
- After each capture, before publishing, run a lightweight scan for
  common secret patterns visible in the screenshot text.
- Implementation: OCR the screenshot (via Tesseract or Playwright's
  accessibility tree dump) and check for patterns:
  - API keys (ghp_, sk-live_, AKIA, etc.)
  - Connection strings (postgres://, mongodb://, redis://)
  - Bearer tokens, JWTs
  - IP addresses outside RFC 1918 ranges
- If a potential secret is detected:
  - Log a warning with the capture ID and pattern matched.
  - Mark the capture as requires_review in the CaptureResult.
  - Do NOT auto-publish. Require --force or manual approval.
- This is a best-effort safeguard, not a guarantee. It catches the
  obvious cases (visible env vars, debug output with tokens).
- Can be disabled per-project: security.screenshot_scan: false
```

---

## Section 15: Distribution — Add CLI Commands

### Add `phantom init`:

```bash
$ phantom init
? Project type: (web / tui / desktop / docker-compose) web
? Project name: my-project
? Dev server command: npm run dev
? Dev server port: 3000
? Number of initial captures: 3

Created .phantom.yml with 3 capture stubs.
Edit the file to fill in routes, selectors, and output paths.
Run `phantom validate` to check your manifest.
```

Generates a minimal but valid `.phantom.yml` with TODO markers for fields that need user input.

### Add `phantom run` flags:

```bash
phantom run --project example-app                    # Full run (existing)
phantom run --project example-app --dry-run           # NEW: Build, launch, capture — but don't commit
phantom run --project example-app --capture dashboard # NEW: Run single capture only
phantom run --project example-app --group hero-shots  # NEW: Run capture group
phantom run --project example-app --skip-publish      # NEW: Capture + process, skip git
phantom run --project example-app --force             # NEW: Commit even if below diff threshold
```

### Add `phantom diff`:

```bash
$ phantom diff example-app
Comparing against last published screenshots...
  dashboard:       12.3% changed (above 5% threshold — would update)
  casting-active:  0.8% changed (below threshold — would skip)
  mobile-admin:    NEW (no previous version)
```

### Add shell completions:

```bash
# Install completions (via click's built-in support)
phantom --install-completion bash    # >> ~/.bashrc
phantom --install-completion zsh     # >> ~/.zshrc
phantom --install-completion fish    # >> ~/.config/fish/completions/
```

---

## Section 16.1: Infrastructure — Increase Resources

| Component | Old | New | Rationale |
|-----------|-----|-----|-----------|
| Disk | 50 GB | 80 GB | Rust target dirs are 5-15 GB; node_modules add up |
| Swap | (none) | 4 GB | Prevents OOM during Chromium + Rust build overlap |

Add to provisioning checklist (after step 2):

```
2.5 Configure swap:
   - fallocate -l 4G /swapfile
   - chmod 600 /swapfile
   - mkswap /swapfile
   - swapon /swapfile
   - echo '/swapfile none swap sw 0 0' >> /etc/fstab
   - sysctl vm.swappiness=10  # Prefer RAM, use swap as safety net
```

---

## Section 20: Failure Modes — Queue Persistence Recovery

Add to section 20.2 recovery table:

| Failure | Detection | Recovery | Max Retries |
|---------|-----------|----------|-------------|
| Phantom restart with queued jobs | Queue file exists on startup | Resume queue processing from first pending entry | N/A |
| Phantom crash mid-job | Lock held but process dead (flock released) | Next trigger finds no lock, proceeds normally. Partial workspace is cleaned up on next run. | N/A |

---

## Section 21: Performance — Browser Reuse Impact

Add row to performance table:

| Phase | Old Budget | New Budget | Notes |
|-------|-----------|-----------|-------|
| Capture (each) | <10s | <8s | Browser reuse saves 1-3s per capture |
| **Total (5 captures)** | **<3 min** | **<2.5 min** | Cumulative savings from reuse + SSIM (faster than subprocess pixelmatch) |
