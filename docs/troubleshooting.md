# Troubleshooting

This guide covers common issues you may encounter when using Phantom, along with their symptoms, likely causes, and step-by-step solutions.

---

## Table of Contents

1. [Using `phantom doctor`](#1-using-phantom-doctor)
2. [Playwright missing or not installed](#2-playwright-missing-or-not-installed)
3. [Silicon not found](#3-silicon-not-found)
4. [Docker not running](#4-docker-not-running)
5. [Webhook signature failures](#5-webhook-signature-failures)
6. [Git push conflicts](#6-git-push-conflicts)
7. [Blank screenshots](#7-blank-screenshots)
8. [Ready check timeouts](#8-ready-check-timeouts)
9. [Manifest validation errors](#9-manifest-validation-errors)
10. [Permission errors](#10-permission-errors)
11. [Performance tips](#11-performance-tips)

---

## 1. Using `phantom doctor`

The `phantom doctor` command is your first line of defense when something is not working. It probes all known system dependencies across every runner type and reports which tools are present, which are missing, and how to install them.

### Running it

```bash
phantom doctor
```

By default, `doctor` only shows missing tools. To see all checks, including passing ones, use the `--verbose` flag:

```bash
phantom doctor -v
```

### Understanding the output

The output is a table with five columns:

| Column | Meaning |
|--------|---------|
| **Tool** | The system binary being checked (e.g., `git`, `node`, `silicon`) |
| **Status** | `OK` (found on PATH) or `MISSING` |
| **Version** | The detected version, or `-` if the tool was not found |
| **Runner** | Which runner type requires this tool (`common`, `web`, `tui`, `docker-compose`) |
| **Install hint** | An OS-appropriate install command, shown only for missing tools |

Below the table, `doctor` lists all registered runners and a summary count of OK vs. missing tools.

### What to do with the results

- **All dependencies satisfied** -- You are good to go. If you are still having problems, the issue is likely in your manifest or application rather than missing system tools.
- **Tools missing for a runner you do not use** -- You can safely ignore these. For example, if you only use the `web` runner, a missing `silicon` (required by the `tui` runner) is not a problem.
- **Tools missing for a runner you do use** -- Follow the install hint shown in the table. After installing, run `phantom doctor` again to confirm.

### Common issues doctor does not catch

`phantom doctor` checks that tools exist on your PATH and can report their version. It does **not** verify:

- That Playwright browsers are installed (see [section 2](#2-playwright-missing-or-not-installed))
- That Docker daemon is actually running (see [section 4](#4-docker-not-running))
- That your manifest is valid (use `phantom validate` for that)
- That your application builds and starts successfully

---

## 2. Playwright missing or not installed

The `web` runner uses Playwright with headless Chromium to capture browser-based applications. Playwright has two parts: the Python package and the browser binaries. Both must be present.

### Symptoms

**Python package missing:**

```
ModuleNotFoundError: No module named 'playwright'
```

**Browser binaries not installed:**

```
playwright._impl._errors.Error: Executable doesn't exist at /path/to/chromium
```

or

```
BrowserType.launch: Browser is not installed or not found
```

### Solution

**Step 1: Install the Playwright Python package.**

This is included as a dependency of `phantom-docs` and should already be installed. If not:

```bash
pip install playwright
```

**Step 2: Install the Chromium browser binary.**

This is the step most people miss. Playwright does not ship browser binaries with the Python package -- you must download them separately:

```bash
playwright install chromium
```

This downloads a known-good version of Chromium managed by Playwright. You do not need to install Chrome or Chromium through your system package manager.

**Step 3: Verify.**

```bash
python -c "from playwright.sync_api import sync_playwright; print('OK')"
phantom doctor -v
```

### Notes

- If you are running in CI, add `playwright install chromium` to your setup step.
- On Linux, Playwright may require additional system libraries. Run `playwright install-deps chromium` to install them.
- You do not need Firefox or WebKit. Phantom only uses Chromium.

---

## 3. Silicon not found

The `tui` runner uses [silicon](https://github.com/Aloxaf/silicon) to render terminal screen buffers (captured via pyte) into PNG images. If silicon is not on your PATH, TUI captures will fail.

### Symptoms

```
RunnerSetupError: silicon is required for TUI captures but was not found on PATH.
Install it: https://github.com/Aloxaf/silicon
  brew install silicon  (macOS)
  cargo install silicon (from source)
```

Or from `phantom doctor`:

```
Tool      Status    Version  Runner  Install hint
silicon   MISSING   -        tui     brew install silicon
```

### Solution

**macOS (Homebrew):**

```bash
brew install silicon
```

**From source (any platform with Rust):**

```bash
cargo install silicon
```

If you do not have Rust installed:

```bash
# macOS
brew install rust

# Linux
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env
```

Then install silicon:

```bash
cargo install silicon
```

**Step 3: Verify.**

```bash
which silicon
silicon --version
phantom doctor -v
```

### Notes

- Silicon requires fonts to render text. If you see rendering errors, make sure you have the font specified in your manifest's `tui.renderer_config.font` installed on your system. The default is `JetBrains Mono`.
- If you only use the `web` or `docker-compose` runners, you do not need silicon at all.

---

## 4. Docker not running

The `docker-compose` runner requires Docker to be installed and the Docker daemon to be actively running.

### Symptoms

**Docker not installed:**

```
RequirementError: Required tool 'docker' is not installed. brew install --cask docker
```

**Docker daemon not started:**

```
error during connect: ... Is the docker daemon running?
```

or

```
Cannot connect to the Docker daemon at unix:///var/run/docker.sock
```

**Permission denied:**

```
Got permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock
```

### Solution

**Docker not installed:**

```bash
# macOS
brew install --cask docker

# Linux
# Follow the official guide: https://docs.docker.com/engine/install/
```

**Docker daemon not started:**

- **macOS:** Open the Docker Desktop application. The whale icon in the menu bar indicates Docker is running.
- **Linux (systemd):**
  ```bash
  sudo systemctl start docker
  sudo systemctl enable docker  # start on boot
  ```

**Permission denied (Linux):**

Add your user to the `docker` group:

```bash
sudo usermod -aG docker $USER
```

Then log out and log back in (or run `newgrp docker`) for the group change to take effect. Verify with:

```bash
docker ps
```

**Verify everything works:**

```bash
docker info
docker compose version
phantom doctor -v
```

### Notes

- Phantom calls `docker compose` (the V2 plugin syntax), not the standalone `docker-compose` binary. Make sure you have Docker Compose V2 installed. It ships with Docker Desktop on macOS and recent Docker Engine packages on Linux.
- If your manifest specifies `compose_file`, make sure that file exists at the path relative to your project root.

---

## 5. Webhook signature failures

When running `phantom serve`, the webhook listener validates incoming GitHub webhook payloads using HMAC-SHA256 signatures. Signature mismatches cause the listener to reject the request with a 403 status.

### Symptoms

In the Phantom server logs:

```
webhook_signature_rejected  error="Signature mismatch"
```

or

```
webhook_signature_rejected  error="Missing X-Hub-Signature-256 header"
```

GitHub shows the webhook delivery as failed with a `403` response:

```json
{"error": "Invalid signature"}
```

### Likely causes

1. **Mismatched secret** -- The `PHANTOM_WEBHOOK_SECRET` environment variable does not match the secret configured in your GitHub webhook settings.
2. **Missing secret** -- The environment variable is not set at all.
3. **Invalid signature format** -- The `X-Hub-Signature-256` header is absent or malformed (must start with `sha256=`).

### Solution

**Step 1: Verify the environment variable is set.**

```bash
echo $PHANTOM_WEBHOOK_SECRET
```

If it is empty, set it before running `phantom serve`:

```bash
export PHANTOM_WEBHOOK_SECRET="your-secret-here"
phantom serve
```

**Step 2: Verify the GitHub webhook secret matches.**

1. Go to your GitHub repository **Settings > Webhooks**.
2. Click on your Phantom webhook.
3. In the **Secret** field, confirm the value matches your `PHANTOM_WEBHOOK_SECRET` exactly. Secrets are case-sensitive and whitespace-sensitive.
4. If you need to change it, update the secret and click **Update webhook**.

**Step 3: Test with a ping event.**

After updating the secret, click **Redeliver** on a recent delivery or trigger a new event. Check the Phantom server logs for `webhook_received` (success) instead of `webhook_signature_rejected`.

**Step 4: Debug the signature manually (advanced).**

If you have the raw payload body and want to verify offline:

```python
import hmac, hashlib

secret = "your-secret"
payload = b'...'  # raw request body bytes
expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
print(f"sha256={expected}")
```

Compare the output against the `X-Hub-Signature-256` header value from GitHub.

### Notes

- The `PHANTOM_WEBHOOK_SECRET` environment variable is **required** for `phantom serve`. The server will refuse to start without it.
- Make sure the webhook content type in GitHub is set to `application/json`.
- The webhook endpoint is `POST /webhook/github`. You can verify the server is running by hitting `GET /health`.

---

## 6. Git push conflicts

After capturing and processing screenshots, Phantom commits and pushes the results to your repository. If the remote branch has advanced since Phantom cloned or started, the push will be rejected.

### Symptoms

In the Phantom run report:

```
PushConflictError: Push rejected (likely conflict): ...non-fast-forward...
```

or in logs:

```
git_push_conflict_retry  attempt=1  max_retries=3
```

### How Phantom handles this

Phantom has built-in retry logic for push conflicts. When a push is rejected:

1. It runs `git pull --rebase origin <branch>` to rebase Phantom's commit on top of the latest remote.
2. It retries the push.
3. This repeats up to 3 times (configurable via `MAX_PUSH_RETRIES` in `publisher/git.py`).

Most conflicts resolve automatically because Phantom only modifies screenshot files and README sentinel regions, which rarely conflict with application code changes.

### When automatic retry fails

If all 3 retries are exhausted, the run fails with:

```
git_push_exhausted_retries  attempts=3  branch=main
```

This happens when:

- The branch is receiving very rapid pushes (e.g., a CI pipeline merging multiple PRs simultaneously).
- A rebase conflict occurs because someone else modified the same screenshot files or README sentinel regions that Phantom is updating.

### Manual resolution

**Step 1: Check the workspace.**

Phantom workspaces are stored under `/tmp/phantom/workspace/`. Find the latest one for your project:

```bash
ls -lt /tmp/phantom/workspace/ | grep your-project
```

**Step 2: Resolve the conflict manually.**

```bash
cd /tmp/phantom/workspace/your-project-<hash>/repo
git status
git pull --rebase origin main
# Resolve any conflicts
git add .
git rebase --continue
git push origin main
```

**Step 3: Re-run Phantom.**

```bash
phantom run -p /path/to/your/project
```

### Prevention

- Use the `strategy: pr` publishing strategy to create a pull request instead of pushing directly. This avoids push conflicts entirely and lets you review changes before merging.
- If you use `strategy: direct`, avoid running Phantom concurrently with other processes that modify the same branch.

---

## 7. Blank screenshots

A blank (all white or all black) screenshot usually means Phantom captured the page before your application finished rendering.

### Symptoms

- The output PNG exists but is blank or shows only a background color.
- The Phantom run completes successfully (no errors), but the images are empty.

### Likely causes

1. **Application not ready when captured** -- The ready check passed, but the UI has not finished rendering.
2. **Wrong ready check configuration** -- The ready check is too lenient (e.g., `delay` instead of `http`, or checking the wrong URL).
3. **Missing `wait_after_actions`** -- Actions execute but the UI has not updated before the screenshot is taken.
4. **Viewport too small** -- Content is outside the visible area.
5. **JavaScript-rendered content not loaded** -- SPA frameworks may need additional wait time after the initial page load.

### Solution

**Step 1: Add a `wait_for` selector to your capture.**

Wait for a specific element that indicates the page is fully rendered:

```yaml
captures:
  - id: dashboard
    name: "Dashboard"
    route: "/"
    output: "docs/screenshots/dashboard.png"
    wait_for: ".dashboard-loaded"  # CSS selector for an element that appears when ready
```

**Step 2: Add explicit wait actions.**

If there is no single element to wait for, use `wait_for` and `wait` actions:

```yaml
captures:
  - id: dashboard
    name: "Dashboard"
    route: "/"
    output: "docs/screenshots/dashboard.png"
    actions:
      - type: wait_for
        selector: ".main-content"
        state: visible
        timeout: 10
      - type: wait_for_network
        state: idle
        timeout: 10
      - type: wait
        ms: 1000  # extra buffer for animations
```

**Step 3: Increase `wait_after_actions`.**

This global setting (in `capture_defaults` or per-capture) adds a delay between the last action and the screenshot:

```yaml
capture_defaults:
  wait_after_actions: 1500  # milliseconds, default is 500
```

**Step 4: Verify the viewport.**

Make sure the viewport is large enough for your content:

```yaml
capture_defaults:
  viewport:
    width: 1280
    height: 800
```

If your app has responsive breakpoints, make sure the width is above the breakpoint you want to capture.

**Step 5: Use `--verbose` to debug.**

Run with verbose logging to see exactly what is happening:

```bash
phantom run -p ./my-app -v
```

Check the raw screenshots in the workspace directory (`/tmp/phantom/workspace/<project>/raw/`) to see what was captured before darkroom processing.

### Notes for TUI captures

For the `tui` runner, blank screenshots usually mean the terminal screen buffer was empty. Make sure:

- Your application actually writes to stdout/stderr.
- The `screen_stable` ready check has a sufficient `stability_window` (default 500ms).
- The terminal dimensions in `tui.terminal` match what your application expects.

---

## 8. Ready check timeouts

A ready check timeout means Phantom started your application but it never reached a "ready" state within the configured timeout period.

### Symptoms

```
RunnerLaunchError: Application failed ready check after 30s. Type: http
stdout (last 20 lines):
...
stderr (last 20 lines):
...
```

For TUI apps:

```
RunnerLaunchError: TUI application failed ready check after 30s. Type: screen_stable
Output (last 20 lines):
...
Screen:
...
```

### Likely causes

1. **Application crashes on startup** -- The process exits before the ready check can succeed. Check the stdout/stderr in the error output.
2. **Wrong ready check type** -- Using `http` for an app that does not have an HTTP endpoint, or `screen_stable` for an app that continuously updates.
3. **Wrong URL or port** -- The `ready_check.url` does not match where your app actually listens.
4. **Timeout too short** -- The application takes longer to start than the default 30 seconds (e.g., large npm builds, database migrations).
5. **Missing environment variables** -- Your app requires env vars that are not set in the manifest.

### Solution

**Step 1: Verify your app starts manually.**

Before debugging Phantom, confirm your app starts correctly on its own:

```bash
cd /path/to/your/project
npm run dev  # or whatever your run command is
# In another terminal:
curl http://localhost:3000
```

**Step 2: Choose the right ready check type.**

| Type | Use when |
|------|----------|
| `http` | Your app serves HTTP and you know the URL |
| `tcp` | Your app listens on a port but the HTTP response is not predictable |
| `stdout_match` | Your app prints a specific message when ready (e.g., "Server listening on port 3000") |
| `screen_stable` | TUI apps: wait for the screen buffer to stop changing |
| `delay` | Last resort: wait a fixed number of seconds |

Example using `stdout_match`:

```yaml
setup:
  run:
    command: "npm run dev"
    ready_check:
      type: stdout_match
      pattern: "ready in"
      timeout: 60
```

**Step 3: Increase the timeout.**

```yaml
setup:
  run:
    ready_check:
      type: http
      url: "http://localhost:3000"
      timeout: 60  # seconds, default is 30
```

**Step 4: Adjust the polling interval.**

The `interval` field controls how frequently Phantom checks readiness (default: 1 second):

```yaml
setup:
  run:
    ready_check:
      type: http
      url: "http://localhost:3000"
      timeout: 60
      interval: 2  # check every 2 seconds
```

**Step 5: Set required environment variables.**

If your app needs specific env vars to start:

```yaml
setup:
  run:
    command: "npm run dev"
    env:
      NODE_ENV: "development"
      DATABASE_URL: "sqlite:///tmp/phantom-test.db"
      PHANTOM_MODE: "1"
    ready_check:
      type: http
      url: "http://localhost:3000"
```

**Step 6: Check for port conflicts.**

If another process is already using the port your app needs, the app may fail to start. Check with:

```bash
lsof -i :3000
```

### Debugging screen_stable timeouts (TUI)

For the `tui` runner, `screen_stable` waits for the screen content hash to remain unchanged for `stability_window` milliseconds. If your app has a blinking cursor or continuously updating content (e.g., a clock), the screen will never stabilize.

Adjust the parameters:

```yaml
setup:
  run:
    ready_check:
      type: screen_stable
      timeout: 30
      stability_window: 1000   # require 1 second of stability
      check_interval: 200      # sample every 200ms
```

Or switch to `stdout_match` or `delay` if your TUI app writes a startup message.

---

## 9. Manifest validation errors

Phantom validates your `.phantom.yml` manifest against a strict Pydantic schema before doing anything else. Validation errors are surfaced immediately with descriptive messages.

### Running validation standalone

```bash
phantom validate .phantom.yml
```

### Common errors and fixes

#### Wrong schema version

```
Unsupported schema version '2', expected '1'
```

**Fix:** The only supported version is `"1"`. Make sure it is a string, not an integer:

```yaml
# Correct
phantom: "1"

# Wrong -- YAML interprets unquoted 1 as an integer
phantom: 1
```

#### Duplicate capture IDs

```
ManifestValidationError: Duplicate capture IDs: dashboard
```

**Fix:** Every capture must have a unique `id`. Search your manifest for duplicate IDs:

```yaml
captures:
  - id: dashboard       # first occurrence
    name: "Dashboard"
    output: "docs/screenshots/dashboard.png"
  - id: dashboard       # duplicate -- rename this
    name: "Dashboard Dark"
    output: "docs/screenshots/dashboard-dark.png"
```

#### Invalid capture ID format

```
String should match pattern '^[a-z0-9][a-z0-9\-]*$'
```

**Fix:** Capture IDs must be lowercase, start with a letter or digit, and may only contain lowercase letters, digits, and hyphens:

```yaml
# Valid
- id: hero-screenshot
- id: dashboard-v2

# Invalid
- id: Hero_Screenshot   # no uppercase, no underscores
- id: -dashboard        # cannot start with a hyphen
```

#### Missing required fields

```
Field required [input_value=..., input_type=dict]
```

Common missing fields:

- `phantom` -- Schema version (must be `"1"`)
- `project` -- Project ID
- `name` -- Display name
- `setup` -- Setup configuration with `type` and `run`
- `captures` -- At least one capture definition
- Each capture requires `id`, `name`, and `output`

#### Invalid setup type

```
Setup type 'Web' must match ^[a-z][a-z0-9-]*$
```

**Fix:** The `setup.type` must be lowercase. Valid built-in types are `web`, `tui`, and `docker-compose`:

```yaml
setup:
  type: web  # not "Web" or "WEB"
```

#### Output path escapes project root

```
Capture 'hero' output path must be relative and not contain '..': ../screenshots/hero.png
```

**Fix:** Output paths must be relative to the project root and cannot use `..` to escape it:

```yaml
# Correct
output: "docs/screenshots/hero.png"

# Wrong
output: "/tmp/hero.png"           # absolute path
output: "../other-repo/hero.png"  # escapes project root
```

#### docker-compose missing compose_file

```
docker-compose setup requires 'compose_file'
```

**Fix:** When using the `docker-compose` runner type, you must specify the compose file:

```yaml
setup:
  type: docker-compose
  compose_file: docker-compose.yml
  run:
    command: "docker compose up -d"
    ready_check:
      type: http
      url: "http://localhost:8080"
```

#### Circular dependencies

```
Circular dependency detected involving capture 'capture-a'
```

**Fix:** Captures can declare `depends_on` to specify ordering, but the dependency chain must not form a cycle:

```yaml
captures:
  - id: capture-a
    depends_on: capture-b    # A depends on B
    ...
  - id: capture-b
    depends_on: capture-a    # B depends on A -- circular!
    ...
```

Remove one of the `depends_on` declarations to break the cycle.

#### Invalid ready check configuration

```
http ready_check requires 'url'
```

Each ready check type has required fields:

| Type | Required fields |
|------|----------------|
| `http` | `url` |
| `tcp` | `port` |
| `stdout_match` | `pattern` |
| `delay` | `seconds` |
| `screen_stable` | (none, uses defaults) |

---

## 10. Permission errors

### Workspace directory permissions

**Symptom:**

```
WorkspaceError: ...
PermissionError: [Errno 13] Permission denied: '/tmp/phantom/workspace/...'
```

**Cause:** The `/tmp/phantom/workspace/` directory (or a project subdirectory within it) was created by a different user or with restrictive permissions.

**Solution:**

```bash
# Check ownership
ls -la /tmp/phantom/workspace/

# Fix ownership (replace $USER with your username)
sudo chown -R $USER /tmp/phantom/workspace/

# Or remove and let Phantom recreate it
rm -rf /tmp/phantom/workspace/
```

### Lock file conflicts

**Symptom:**

```
LockError: Another Phantom instance is running for project 'my-project'.
If this is incorrect, remove /tmp/phantom/workspace/.locks/my-project.lock
```

**Cause:** Phantom uses flock-based per-project locks to prevent concurrent runs. This error means either another instance is genuinely running, or a previous instance crashed without releasing the lock.

**Solution:**

**Step 1: Check if another instance is actually running.**

```bash
ps aux | grep phantom
```

**Step 2: If no other instance is running, remove the stale lock file.**

```bash
rm /tmp/phantom/workspace/.locks/my-project.lock
```

**Step 3: Re-run Phantom.**

```bash
phantom run -p ./my-project
```

### State file permissions

**Symptom:**

```
state_record_failed  error="Permission denied: ~/.phantom/state.json"
```

**Cause:** The state file at `~/.phantom/state.json` is owned by a different user (e.g., created during a `sudo` run).

**Solution:**

```bash
sudo chown $USER ~/.phantom/state.json
# Or remove it -- Phantom will recreate it
rm ~/.phantom/state.json
```

### Output directory permissions

**Symptom:**

The run completes but output files are not written to your project directory.

**Cause:** The output directory (e.g., `docs/screenshots/`) does not exist or is not writable.

**Solution:**

Phantom creates output directories automatically, but the parent directory must be writable. Verify:

```bash
ls -la docs/
mkdir -p docs/screenshots
```

---

## 11. Performance tips

### Use `--capture` for single captures

If you are iterating on a single screenshot, avoid running the entire pipeline. Use `--capture` to target a specific capture by ID:

```bash
phantom run -p ./my-app --capture dashboard
```

This skips all other captures, which can save significant time for projects with many screenshots.

### Use `--group` for related captures

If your manifest defines groups, run only the captures you need:

```yaml
groups:
  onboarding: [signup, login, welcome]
  settings: [settings-general, settings-billing]
```

```bash
phantom run -p ./my-app --group onboarding
```

### Use `--if-changed` to skip unchanged projects

The `--if-changed` flag compares the current git HEAD SHA against the last SHA that Phantom captured for this project. If they match, the entire run is skipped:

```bash
phantom run -p ./my-app --if-changed
```

This is especially useful in CI pipelines where Phantom runs on every push but the UI may not have changed:

```yaml
# .github/workflows/screenshots.yml
- run: phantom run -p . --if-changed
```

### Use `--skip-publish` during development

When iterating on your manifest locally, skip git operations to speed up the feedback loop:

```bash
phantom run -p ./my-app --skip-publish
```

Combine with `--capture` for the fastest iteration:

```bash
phantom run -p ./my-app --capture hero --skip-publish
```

### Use `--dry-run` to preview

A dry run executes the full pipeline (build, launch, capture, process) but skips git commit and push. Use this to verify everything works before committing:

```bash
phantom run -p ./my-app --dry-run
```

### Enable verbose logging for diagnosis

When something is not working, verbose mode provides structured log output for every stage of the pipeline:

```bash
phantom run -p ./my-app -v
```

### Clean up stale workspaces

Over time, workspaces accumulate in `/tmp/phantom/workspace/`. Use `phantom gc` to clean up old ones:

```bash
# Remove workspaces older than 7 days (default)
phantom gc

# Remove workspaces older than 1 day
phantom gc --days 1

# Preview what would be removed without deleting
phantom gc --dry-run
```

### Diff threshold tuning

Phantom uses SSIM (structural similarity) to detect whether a screenshot has actually changed. The default threshold is 0.95. If Phantom is committing screenshots with negligible visual differences, raise the threshold:

```yaml
processing:
  diff:
    threshold: 0.98  # require more significant changes before committing
```

Conversely, if Phantom is skipping screenshots that you want committed, lower the threshold or use the `--force` flag:

```bash
phantom run -p ./my-app --force
```
