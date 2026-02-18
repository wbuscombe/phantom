# Phantom Onboarding: Set Up Automated Documentation for Your Project

> **What this does:** This prompt configures your project for [Phantom](https://github.com/wbuscombe/phantom), an automated documentation screenshot generator. After running this, your project will have everything needed for Phantom to automatically capture, process, and publish screenshots to your documentation on every release.
>
> **How to use:** Copy this entire prompt into Claude Code while in your project's root directory. Claude Code will analyze your project and generate all necessary files.

---

## Instructions for Claude Code

Analyze the current project directory and set up everything needed for Phantom automated documentation screenshots. Read the project's source code, understand what it does, and generate all of the deliverables listed below.

### 1. Analyze the Project

Examine the project to understand:

- **Tech stack:** Language, framework, build tools, package manager
- **Project type:** Web app, TUI app, desktop app, Docker compose service, CLI tool
- **User-facing features:** Routes, views, screens, commands — anything a user interacts with
- **Data model:** What data does the app display? What would realistic demo data look like?
- **External dependencies:** APIs, databases, services that need mocking in demo mode
- **Existing documentation:** README structure, existing screenshots, docs/ directory
- **Build and run process:** How to build from source, how to start the app

### 2. Create Demo Mode

Create the infrastructure for the app to run in a self-contained demo state:

- **Environment flag:** Support `PHANTOM_MODE=1` to activate demo mode
- **Mock external services:** When demo mode is active, all external API calls, authentication, network requests to third-party services are mocked or disabled
- **Demo data loading:** The app loads from bundled fixture data instead of real sources
- **No side effects:** No emails, webhooks, notifications, or writes to external systems
- **Identical UX:** The app must look and behave identically to production — just with synthetic data

Implementation approach depends on the project:
- Python: monkey-patch modules in a `demo.py` loaded at startup
- Node/React: environment-based mock service injection
- Rust: feature flag or config-based mock layer
- Docker: compose profile with mock service containers

Gate ALL demo mode changes so they have zero impact on production behavior.

### 3. Create Demo Seed Data

Create a seed data fixture and/or script:

- **Location:** `demo/data.json` (or language-appropriate format) for static fixtures, `scripts/seed-demo-data.{ext}` for dynamic seeding
- **Realistic content:** Names, titles, descriptions, dates should look like real data a real user would have. Not "Test Item 1" — use creative, varied, realistic content.
- **Sufficient volume:** Enough data that the app looks populated and active:
  - Lists should have 10-50+ items (not 3)
  - Multiple categories/types represented
  - Varied sizes (some lists long, some short)
  - Recent dates spread across the last few weeks/months
- **Idempotent:** Safe to run multiple times
- **Fast:** Completes in under 10 seconds
- **Self-contained:** No network access or external dependencies

### 4. Create `.phantom.yml` Manifest

Generate a Phantom manifest in the project root:

```yaml
phantom: "1"
project: "{project-name}"
name: "{Display Name}"
```

Include:

- **Setup section:** Correct build commands, run command, ready check, environment variables including `PHANTOM_MODE: "1"`, teardown
- **Fixtures section:** Reference the seed script if one was created
- **5-8 captures** covering the app's hero states:
  - Main/home view (populated with data)
  - 2-3 key feature workflows (the things that make this app valuable)
  - A detail or drill-down view
  - Mobile/responsive variant (for web apps)
  - Any visually distinctive secondary views
- Each capture needs: `id`, `name`, `description`, `alt_text`, `actions` (navigation sequence from app start), `output` path under `docs/screenshots/`, appropriate viewport or terminal dimensions
- **Processing section:** drop-shadow border, png format, optimize enabled, 2x retina
- **Publishing section:** direct to main branch, conventional commit message

For **TUI apps** specifically:
- Terminal dimensions: 140×36 (or sized to content)
- Silicon renderer: JetBrains Mono font, dark theme (Dracula or similar), window controls enabled, 20px padding, 8px corner radius
- Actions use `keystroke`, `type_text`, `wait`

For **web apps** specifically:
- Default viewport: 1440×900, device_scale: 2
- Dark theme via `prefers-color-scheme` emulation
- Actions use `navigate`, `click`, `wait_for`, `type`, `wait`
- Use real CSS selectors from the actual DOM

### 5. Create GitHub Actions Workflow

Create `.github/workflows/update-screenshots.yml`:

```yaml
name: Update Screenshots
on:
  release:
    types: [published]
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write

jobs:
  screenshots:
    runs-on: ubuntu-latest
    steps:
      # Install Python, Phantom, project dependencies
      # Install runner-specific deps (Playwright for web, silicon for TUI)
      # Run phantom run --project .
      # Commit and push or open PR with updated screenshots
```

The workflow should:
- Cache expensive dependencies (silicon compilation, node_modules, cargo target)
- Install fonts if needed (JetBrains Mono for TUI)
- Upload screenshots as artifacts for debugging
- Use `PHANTOM_PAT` secret if cloning private dependencies
- Commit directly to main or open a PR (configurable)

### 6. Prepare README for Screenshots

Add Phantom sentinel comments to the project's `README.md` at natural locations:

```markdown
<!-- phantom:{capture-id} -->
<img src="docs/screenshots/{capture-id}.png" width="{logical-width}" alt="{descriptive alt text}">
<!-- /phantom:{capture-id} -->
```

- Place sentinels where screenshots naturally belong in the existing README structure
- Do NOT restructure the README — work with what exists
- Add brief contextual text near each screenshot if the README doesn't already describe the feature
- Create `docs/screenshots/.gitkeep` to ensure the directory exists

### 7. Validate

- Run `phantom validate .phantom.yml` if Phantom is installed, or verify YAML structure matches the schema
- Verify demo mode starts: run the app with `PHANTOM_MODE=1` and confirm it displays demo data
- Verify the seed script runs without errors
- Verify the GitHub Actions workflow is syntactically valid YAML

### 8. Commit

Stage and commit all new and modified files:

```
git add -A
git commit -m "feat: add Phantom automated documentation pipeline

- Demo mode (PHANTOM_MODE=1) with realistic fixture data
- {N} screenshot captures defined in .phantom.yml
- GitHub Actions workflow for automated screenshot updates
- README sentinels for Phantom image placement"
```

Do NOT push — let the user review the changes first.

## Report

After completing all steps, provide:

- **Project analysis summary:** type, stack, features identified
- **Demo mode:** what was mocked, how it's activated
- **Captures defined:** list with brief descriptions
- **Files created/modified:** complete list
- **Manual steps remaining:**
  - Review and push the commit
  - Add `PHANTOM_PAT` repository secret if using private Phantom repo
  - Enable "Allow GitHub Actions to create PRs" in repo settings (if using PR strategy)
  - Run `gh workflow run update-screenshots.yml` to trigger first capture
  - Install `pngquant` and `oxipng` locally for optimized local captures (optional)
