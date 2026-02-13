# Deployment Guide

This guide covers every way to run Phantom, from local development to production self-hosted servers. Each section includes copy-pasteable examples.

---

## Table of Contents

1. [Local Development](#1-local-development)
2. [CI Integration (GitHub Actions)](#2-ci-integration-github-actions)
3. [Self-hosted Server](#3-self-hosted-server)
4. [Docker](#4-docker)
5. [Environment Variables](#5-environment-variables)
6. [Webhook Setup](#6-webhook-setup)
7. [Scheduling](#7-scheduling)

---

## 1. Local Development

The fastest way to use Phantom is running it against a local project directory.

### Install

```bash
pipx install phantom-docs
# or
pip install phantom-docs
```

Install the Playwright browser (required for web runner captures):

```bash
playwright install chromium
```

Verify your setup:

```bash
phantom doctor
```

### Initialize a Manifest

If your project does not have a `.phantom.yml` yet, scaffold one interactively:

```bash
cd /path/to/your/project
phantom init
```

This auto-detects the project type (web, tui, docker-compose) and generates a manifest with sensible defaults.

### Run Captures

```bash
phantom run -p .
```

This runs the full pipeline: validate the manifest, build the project, launch the dev server, execute actions, capture screenshots, process images through the darkroom, and (unless `--dry-run` is set) commit the results.

### Useful Flags

```bash
# Preview without committing
phantom run -p . --dry-run

# Capture and process images, but skip all git operations
phantom run -p . --skip-publish

# Run a single capture by ID
phantom run -p . --capture dashboard

# Run a named group of captures
phantom run -p . --group hero

# Commit even if screenshots are below the diff threshold
phantom run -p . --force

# Skip entirely if the repo HEAD has not changed since the last run
phantom run -p . --if-changed

# Debug logging
phantom run -p . --verbose
```

### Validate Without Running

```bash
phantom validate .phantom.yml
```

This parses the manifest, resolves captures against defaults, and prints a summary table without launching anything.

---

## 2. CI Integration (GitHub Actions)

Run Phantom automatically on every push to `main` so documentation screenshots stay current.

### Full Workflow

Create `.github/workflows/phantom.yml`:

```yaml
name: Update Screenshots

on:
  push:
    branches: [main]

# Prevent concurrent Phantom runs on the same branch
concurrency:
  group: phantom-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: write

jobs:
  screenshots:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          # Fetch depth 2 so Phantom can diff against the previous commit
          fetch-depth: 2

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install Phantom
        run: pip install phantom-docs

      - name: Install Playwright browsers
        run: playwright install chromium --with-deps

      - name: Install optimization tools
        run: |
          sudo apt-get update
          sudo apt-get install -y pngquant

      - name: Run Phantom
        run: phantom run -p . --verbose

      - name: Commit updated screenshots
        run: |
          git config user.name "Phantom Bot"
          git config user.email "phantom@noreply"
          git add docs/screenshots/ README.md
          git diff --cached --quiet || git commit -m "docs(screenshots): update via Phantom [skip ci]"
          git push
```

### Workflow Variations

**Run only when specific files change** (avoids unnecessary screenshot updates):

```yaml
on:
  push:
    branches: [main]
    paths:
      - "src/**"
      - "public/**"
      - ".phantom.yml"
```

**Run on release only:**

```yaml
on:
  release:
    types: [published]
```

**Run a specific capture group:**

```yaml
      - name: Run Phantom (hero screenshots only)
        run: phantom run -p . --group hero --verbose
```

**Dry-run on pull requests** (validate that captures succeed without committing):

```yaml
on:
  pull_request:
    branches: [main]

jobs:
  phantom-check:
    runs-on: ubuntu-latest
    steps:
      # ... setup steps same as above ...
      - name: Phantom dry run
        run: phantom run -p . --dry-run --verbose
```

---

## 3. Self-hosted Server

For teams that want Phantom to react to GitHub webhooks and run on a schedule, use `phantom serve`. This starts a long-running process with a webhook listener and a cron scheduler.

### Prerequisites

- A server or VM with Python 3.12+, Chromium (via Playwright), and any build tools your projects need (Node.js, etc.).
- A public URL or reverse proxy so GitHub can reach the webhook endpoint.

### Environment Setup

Create an environment file at `/etc/phantom/phantom.env`:

```bash
# Required: HMAC secret for verifying GitHub webhook signatures
PHANTOM_WEBHOOK_SECRET=your-webhook-secret-here

# Required: Maps repository names to local manifest paths
# Format: repo_name=/path/to/manifest.yml,another-repo=/path/to/other.yml
PHANTOM_MANIFEST_MAP=my-app=/srv/phantom/manifests/my-app.yml,docs-site=/srv/phantom/manifests/docs-site.yml
```

### systemd Unit File

Create `/etc/systemd/system/phantom.service`:

```ini
[Unit]
Description=Phantom Documentation Screenshot Service
After=network.target
Wants=network.target

[Service]
Type=simple
User=phantom
Group=phantom

EnvironmentFile=/etc/phantom/phantom.env

ExecStart=/usr/local/bin/phantom serve --port 9443
Restart=on-failure
RestartSec=10
TimeoutStopSec=30

# Working directory for workspace files
WorkingDirectory=/srv/phantom

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/srv/phantom /tmp/phantom

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=phantom

[Install]
WantedBy=multi-user.target
```

### Server Setup Commands

```bash
# Create the phantom user
sudo useradd --system --shell /usr/sbin/nologin --home-dir /srv/phantom phantom

# Create directories
sudo mkdir -p /srv/phantom/manifests
sudo mkdir -p /etc/phantom
sudo mkdir -p /tmp/phantom/workspace

# Install Phantom
sudo pip install phantom-docs
sudo -u phantom playwright install chromium --with-deps

# Copy your manifest files
sudo cp /path/to/my-app/.phantom.yml /srv/phantom/manifests/my-app.yml

# Create environment file (edit with your values)
sudo tee /etc/phantom/phantom.env > /dev/null <<'EOF'
PHANTOM_WEBHOOK_SECRET=your-secret-here
PHANTOM_MANIFEST_MAP=my-app=/srv/phantom/manifests/my-app.yml
EOF

sudo chmod 640 /etc/phantom/phantom.env
sudo chown root:phantom /etc/phantom/phantom.env

# Enable and start the service
sudo systemctl daemon-reload
sudo systemctl enable phantom
sudo systemctl start phantom

# Check status
sudo systemctl status phantom
sudo journalctl -u phantom -f
```

### Reverse Proxy (nginx)

If you terminate TLS at a reverse proxy, forward requests to the Phantom port:

```nginx
server {
    listen 443 ssl;
    server_name phantom.example.com;

    ssl_certificate     /etc/letsencrypt/live/phantom.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/phantom.example.com/privkey.pem;

    location /webhook/github {
        proxy_pass http://127.0.0.1:9443;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /health {
        proxy_pass http://127.0.0.1:9443;
    }
}
```

### Health Check

The serve command exposes a health endpoint:

```bash
curl http://localhost:9443/health
# {"status": "ok", "queue_size": 0}
```

---

## 4. Docker

Run Phantom in a container with Playwright and Chromium pre-installed.

### Dockerfile

```dockerfile
FROM python:3.12-slim

# Install system dependencies for Playwright/Chromium and image optimization
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libcups2 \
    libxkbcommon0 \
    libatspi2.0-0 \
    fonts-liberation \
    pngquant \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Phantom
RUN pip install --no-cache-dir phantom-docs

# Install Playwright Chromium browser
RUN playwright install chromium --with-deps

# Create phantom user and workspace directories
RUN useradd --system --shell /usr/sbin/nologin --home-dir /srv/phantom phantom \
    && mkdir -p /srv/phantom/manifests /tmp/phantom/workspace \
    && chown -R phantom:phantom /srv/phantom /tmp/phantom

USER phantom
WORKDIR /srv/phantom

# Default: run the webhook server on port 9443
EXPOSE 9443
CMD ["phantom", "serve", "--port", "9443"]
```

### Build and Run

```bash
# Build the image
docker build -t phantom:latest .

# Run a one-off capture against a local project
docker run --rm \
    -v /path/to/your/project:/project:rw \
    phantom:latest \
    phantom run -p /project --dry-run

# Run the webhook server
docker run -d \
    --name phantom \
    --restart unless-stopped \
    -p 9443:9443 \
    -e PHANTOM_WEBHOOK_SECRET=your-secret-here \
    -e "PHANTOM_MANIFEST_MAP=my-app=/srv/phantom/manifests/my-app.yml" \
    -v /path/to/manifests:/srv/phantom/manifests:ro \
    phantom:latest
```

### Docker Compose

For a more complete setup including an nginx reverse proxy:

```yaml
# docker-compose.yml
services:
  phantom:
    build: .
    restart: unless-stopped
    ports:
      - "9443:9443"
    environment:
      PHANTOM_WEBHOOK_SECRET: "${PHANTOM_WEBHOOK_SECRET}"
      PHANTOM_MANIFEST_MAP: "my-app=/srv/phantom/manifests/my-app.yml"
    volumes:
      - ./manifests:/srv/phantom/manifests:ro
      - phantom-workspace:/tmp/phantom/workspace
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9443/health"]
      interval: 30s
      timeout: 5s
      retries: 3

volumes:
  phantom-workspace:
```

```bash
# Start
PHANTOM_WEBHOOK_SECRET=your-secret docker compose up -d

# View logs
docker compose logs -f phantom
```

---

## 5. Environment Variables

Phantom reads these environment variables at runtime. Both are required when running `phantom serve`.

| Variable | Required For | Format | Description |
|----------|-------------|--------|-------------|
| `PHANTOM_WEBHOOK_SECRET` | `phantom serve` | Plain string | HMAC secret used to verify the `X-Hub-Signature-256` header on incoming GitHub webhook requests. Must match the secret configured in your GitHub webhook settings. |
| `PHANTOM_MANIFEST_MAP` | `phantom serve` | `repo1=/path1,repo2=/path2` | Comma-separated list of `repo_name=manifest_path` pairs. The repo name is the repository name (not the full `owner/repo`), and the path is the absolute path to the `.phantom.yml` manifest file on disk. |

### Examples

**Single repository:**

```bash
export PHANTOM_WEBHOOK_SECRET="whsec_abc123def456"
export PHANTOM_MANIFEST_MAP="my-app=/srv/phantom/manifests/my-app.yml"
```

**Multiple repositories:**

```bash
export PHANTOM_WEBHOOK_SECRET="whsec_abc123def456"
export PHANTOM_MANIFEST_MAP="my-app=/srv/phantom/manifests/my-app.yml,docs-site=/srv/phantom/manifests/docs-site.yml,admin-panel=/srv/phantom/manifests/admin.yml"
```

### Generating a Webhook Secret

```bash
# Generate a secure random secret
openssl rand -hex 32
```

Use the same value in both the `PHANTOM_WEBHOOK_SECRET` environment variable and the GitHub webhook configuration.

---

## 6. Webhook Setup

Configure GitHub to send events to your Phantom server so screenshots update automatically on pushes and releases.

### Step-by-Step

1. Go to your GitHub repository **Settings > Webhooks > Add webhook**.

2. Configure the webhook:

   | Field | Value |
   |-------|-------|
   | **Payload URL** | `https://phantom.example.com/webhook/github` (your server's public URL) |
   | **Content type** | `application/json` |
   | **Secret** | The same value you set in `PHANTOM_WEBHOOK_SECRET` |
   | **SSL verification** | Enable (recommended) |

3. Under **Which events would you like to trigger this webhook?**, select **Let me select individual events** and check:

   - **Pushes** -- triggers screenshot updates when code is pushed to main
   - **Releases** -- triggers screenshot updates when a new release is published

   Uncheck everything else (including the default "Just the push event" if you want releases too).

4. Make sure **Active** is checked, then click **Add webhook**.

### Verifying the Webhook

After saving, GitHub sends a `ping` event. Check your server logs:

```bash
# systemd
sudo journalctl -u phantom -f

# Docker
docker logs -f phantom
```

You should see the ping received. To test a real event, push a commit to main and confirm the screenshot pipeline runs.

### Webhook Endpoint Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/webhook/github` | POST | Receives GitHub webhook events. Validates `X-Hub-Signature-256`, parses the event, and submits a job to the queue. |
| `/health` | GET | Returns `{"status": "ok", "queue_size": N}`. Use for load balancer health checks. |

### Supported GitHub Events

| Event | Trigger Condition | Behavior |
|-------|------------------|----------|
| `push` | Push to an allowed branch (default: `main`, `master`) | Runs captures with `--if-changed` (skips if HEAD matches last captured SHA) |
| `release` (action: `published`) | A new release is published | Runs all captures unconditionally |
| `workflow_dispatch` | Manual trigger via GitHub Actions | Runs all captures unconditionally |

Pushes to branches other than `main`/`master` are ignored by default.

---

## 7. Scheduling

Phantom supports cron-based scheduling through the `triggers` section of the manifest. Scheduled jobs run automatically when `phantom serve` is active.

### Manifest Configuration

Add a `triggers` section to your `.phantom.yml`:

```yaml
phantom: "1"
project: "my-app"
name: "My App"

# ... setup, captures, processing, publishing ...

triggers:
  # Re-capture screenshots every day at 3:00 AM UTC
  - type: schedule
    cron: "0 3 * * *"

  # Also re-capture on new releases
  - type: release
```

### Cron Expression Reference

The `cron` field uses standard 5-field cron syntax:

```
 ┌───────────── minute (0-59)
 │ ┌───────────── hour (0-23)
 │ │ ┌───────────── day of month (1-31)
 │ │ │ ┌───────────── month (1-12)
 │ │ │ │ ┌───────────── day of week (0-6, 0=Sunday)
 │ │ │ │ │
 * * * * *
```

**Common schedules:**

| Cron Expression | Meaning |
|----------------|---------|
| `0 3 * * *` | Every day at 3:00 AM |
| `0 */6 * * *` | Every 6 hours |
| `0 9 * * 1` | Every Monday at 9:00 AM |
| `0 0 1 * *` | First day of every month at midnight |
| `30 2 * * 0` | Every Sunday at 2:30 AM |

### How It Works

When `phantom serve` starts, it reads every manifest referenced in `PHANTOM_MANIFEST_MAP` and looks for `triggers` with `type: schedule`. Each matching trigger is registered in an internal scheduler that checks for due jobs every 60 seconds.

Scheduled jobs default to `--if-changed` behavior: if the project's repository HEAD has not changed since the last capture, the run is skipped. This prevents unnecessary work when nothing has changed.

### Trigger Types

| Type | Description | Required Fields |
|------|-------------|-----------------|
| `schedule` | Cron-based recurring captures | `cron` (5-field cron expression) |
| `release` | Triggered by a GitHub release webhook | None |
| `push` | Triggered by a GitHub push webhook | Optional: `branches`, `paths` |

### Full Example: Multi-trigger Manifest

```yaml
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
      timeout: 30

captures:
  - id: dashboard
    name: "Dashboard"
    route: "/"
    output: "docs/screenshots/dashboard.png"
    actions:
      - { type: wait_for, selector: ".dashboard-loaded" }

  - id: settings
    name: "Settings"
    route: "/settings"
    output: "docs/screenshots/settings.png"

groups:
  hero:
    - dashboard

processing:
  format: png
  optimize: true
  border:
    style: drop-shadow

publishing:
  branch: main
  strategy: direct
  commit_message: "docs(screenshots): update via Phantom"
  readme_update: true

triggers:
  # Nightly rebuild to catch any visual regressions
  - type: schedule
    cron: "0 3 * * *"

  # Immediate update on new releases
  - type: release

  # Update on pushes to main
  - type: push
```
