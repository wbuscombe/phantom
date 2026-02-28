# Phantom Onboarding v2: Automated Documentation for Your Project

> **What this does:** Sets up [Phantom](https://github.com/wbuscombe/phantom) to automatically capture, process, and publish screenshots to your documentation. After running this, every release triggers fresh screenshots in your README.
>
> **How to use:** Copy this entire prompt into Claude Code while in your project's root directory.
>
> **Requirements:** Python 3.10+, git, GitHub repo with Actions enabled.

---

## Instructions for Claude Code

You are onboarding this project to Phantom, an automated documentation screenshot tool. Follow the stages below IN ORDER. Each stage has a verification step — do not proceed to the next stage until verification passes. If verification fails, troubleshoot using the provided guidance before continuing.

## Stage 0: Environment Check

Before touching any project files, verify the environment:

```bash
# Check Python
python3 --version  # Needs 3.10+

# Check Phantom is available
phantom --version 2>/dev/null || {
  # Try the development install
  PHANTOM="$HOME/Dropbox/workspace/phantom/.venv/bin/phantom"
  $PHANTOM --version 2>/dev/null || {
    echo "Phantom not found. Install with: pip install 'phantom-docs>=0.3'"
    exit 1
  }
}

# Check git repo
git remote get-url origin  # Must be a GitHub repo

# Check GitHub CLI
gh auth status
```

Set `PHANTOM` variable to whichever phantom binary works. Use it for all subsequent commands.

## Stage 1: Project Detection

Detect the project type automatically. Read files in this exact order — stop as soon as you have enough information:

### Decision Tree

```
1. Does docker-compose.yml exist?
   → YES: type = docker-compose
   → Check which services have web UIs (look for port mappings, nginx, etc.)

2. Does package.json exist?
   → YES: Check dependencies:
   → next/react/vue/svelte/angular → type = web (SPA/SSR)
   → express/fastify/hono/koa → type = web (server-rendered)
   → electron → type = desktop (Electron)

3. Does pyproject.toml or setup.py exist?
   → YES: Check dependencies:
   → flask/django/fastapi/streamlit → type = web
   → textual/rich/blessed/curses → type = tui
   → pygame/tkinter → type = desktop

4. Does Cargo.toml exist?
   → Check for src-tauri → type = desktop (Tauri)
   → Check for crossterm/tui/ratatui → type = tui
   → Check for actix/axum/rocket → type = web

5. Does Makefile exist with SDL/OpenGL/GTK/Qt flags?
   → YES: type = desktop (native)

6. Does pom.xml or build.gradle exist?
   → Check for javax.swing/javafx → type = desktop (Java GUI)
   → Check for Spring Boot → type = web

7. Are there .html files with significant JS?
   → YES: type = web (static)

8. None of the above?
   → Check for main entry point that produces visual terminal output
   → If yes: type = tui (simple terminal)
   → If no: STOP — this project may not be suitable for Phantom
```

### What to Read

Based on detected type, read ONLY these files (preserve context window):

**Web apps:** `package.json` OR `pyproject.toml`, main route/page files (max 5), layout component, `README.md`
**TUI apps:** `pyproject.toml` OR `Cargo.toml`, main entry point, screen/view modules (max 5), `README.md`
**Desktop apps:** `Makefile` or build config, main source file, `README.md`
**Docker compose:** `docker-compose.yml`, frontend source files (max 5), `README.md`

### Verification

```bash
echo "Detected type: [web|tui|desktop|docker-compose]"
echo "Framework: [flask|react|sdl2|swing|etc]"
echo "Build command: [npm run build|make|cargo build|etc]"
echo "Run command: [npm start|python app.py|./build/myapp|etc]"
echo "Port: [5000|3000|8080|none]"
```

All five fields must be filled before proceeding. If unsure about any, examine more source files.

## Stage 2: Demo Mode

Create `PHANTOM_MODE=1` support. The approach depends entirely on the project type and framework.

### Framework-Specific Playbooks

#### Flask / Django / FastAPI (Python web)

```python
# At the top of the main app file, or in a dedicated demo.py:
import os
PHANTOM_MODE = os.getenv("PHANTOM_MODE") == "1"

# 1. Authentication bypass
if PHANTOM_MODE:
    # Option A: Disable login_required decorators
    # Option B: Auto-create and login a demo user
    # Option C: Skip auth middleware entirely
    # CHOOSE based on how auth is implemented

# 2. Database isolation
if PHANTOM_MODE:
    import tempfile
    db_path = os.path.join(tempfile.mkdtemp(), "phantom_demo.db")
    app.config["DATABASE"] = db_path
    # OR: app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"

# 3. Seed data — load AFTER db is created, BEFORE first request
if PHANTOM_MODE:
    with app.app_context():
        load_demo_data()  # Create tables, insert fixtures

# 4. External service mocking
if PHANTOM_MODE:
    # Mock any external API calls (weather, auth providers, etc.)
    # Use unittest.mock.patch or conditional imports

# 5. Health check bypass (if health endpoint checks external services)
if PHANTOM_MODE:
    @app.route("/health")
    def health():
        return "ok"
```

**Common Flask/Django pitfalls:**
- SQLite with `PARSE_DECLTYPES` requires `strftime('%Y-%m-%d %H:%M:%S')` format, NOT ISO 8601 with `T`
- Database path must be writable in CI (not `/data/` or other Docker-only paths)
- `@login_required` on the health endpoint will return 302/401 in demo mode
- Socket.IO keepalive prevents Playwright `networkidle` — use `domcontentloaded` + explicit wait

#### React / Next.js / Vue (JavaScript SPA)

```javascript
// In environment config or a demo provider:
const PHANTOM_MODE = process.env.PHANTOM_MODE === "1";

// 1. Mock API layer
if (PHANTOM_MODE) {
  // Use MSW (Mock Service Worker) or conditional fetch wrapper
  // Return fixture data for all API calls
}

// 2. Auth bypass
if (PHANTOM_MODE) {
  // Set auth context to a demo user
  // Skip redirect to login page
}

// 3. Static data
// Create public/demo-data.json or src/fixtures/demo.json
```

#### SDL2 / OpenGL / Native C/C++

```c
// In main() or near the top:
int phantom_mode = getenv("PHANTOM_MODE") && strcmp(getenv("PHANTOM_MODE"), "1") == 0;

// 1. Deterministic seeding (critical for consistent screenshots)
if (phantom_mode) {
    srand(42);  // Fixed seed — same board/state every time
} else {
    srand(time(NULL));
}

// 2. Audio mocking (SDL2)
// Don't init audio subsystem in phantom mode, or set SDL_AUDIODRIVER=dummy in env

// 3. No self-capture code needed — Desktop Runner handles screenshots externally
// Just make sure the app reaches the desired state and stays there
```

#### Java Swing / JavaFX

```java
// In main():
boolean phantomMode = "1".equals(System.getenv("PHANTOM_MODE"));

// 1. Deterministic state
if (phantomMode) {
    // Use fixed seed for Random
    // Load specific data file
    // Set window to specific size
}

// 2. Keep window open (don't auto-close)
// Desktop Runner needs time to capture
if (phantomMode) {
    frame.setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
    // Don't call System.exit() or dispose() prematurely
}
```

#### Python TUI (Textual / Rich / Curses)

```python
# Create demo.py that monkey-patches external dependencies:
PHANTOM_MODE = os.getenv("PHANTOM_MODE") == "1"

if PHANTOM_MODE:
    # 1. Patch authentication (return hardcoded credentials)
    # 2. Patch API calls (return fixture data from demo/data.json)
    # 3. Patch database (load from fixture instead of real DB)
    # 4. Patch config (hardcode safe defaults)
    
    # Import and patch BEFORE the app imports these modules
    import demo  # demo.py does all the patching
```

### Demo Seed Data

Create fixture data that makes the app look compelling:

**Quality checklist:**
- [ ] 10-50+ items in any list view (not 3 — that looks empty)
- [ ] Varied content: different names, categories, lengths, types
- [ ] Realistic dates spread across recent weeks (not all the same day)
- [ ] Natural size distribution (some playlists have 3 items, some have 150)
- [ ] Multiple user roles/states represented if applicable
- [ ] No placeholder text ("Test Item 1") — use creative, realistic content
- [ ] Edge cases covered: long names that truncate gracefully, unicode characters
- [ ] The data tells a story: "this person actively uses this app"

Location: `demo/data.json` for static fixtures, `demo/seed.py` for dynamic seeding.

### Verification (CRITICAL — do not skip)

```bash
# Start the app in demo mode and verify it works
PHANTOM_MODE=1 <run_command> &
APP_PID=$!
sleep 5

# For web apps: check the server responds
curl -s http://localhost:<port>/ | head -20
# Should return HTML, not a redirect to login or an error

# For TUI apps: check the process started
kill -0 $APP_PID 2>/dev/null && echo "Running" || echo "CRASHED"

# For desktop apps: check under xvfb
# (Skip this locally if not on Linux — CI will test it)

# Clean up
kill $APP_PID 2>/dev/null
```

**If the app crashes or shows an error page:** STOP. Fix the demo mode before proceeding. Common issues:
- Missing database tables → seed script needs to create schema first
- Import errors → demo patches must run before app imports
- Port already in use → use a non-standard port in demo mode
- Missing environment variables → provide defaults in demo mode

## Stage 3: Create Manifest

Generate `.phantom.yml` based on the detected project type.

### Capture Selection

Choose 4-8 captures that tell the story of the app:

1. **Hero shot** (required) — the main view, fully populated with data. This is the first thing users see in the README.
2. **Key workflow** (required) — the primary action the app enables. For a todo app: adding a task. For a game: mid-gameplay.
3. **Secondary features** (1-3) — other notable views that differentiate this app.
4. **Detail view** (optional) — drill-down, modal, or expanded state.
5. **Mobile/responsive** (optional, web only) — if the app is responsive, show it.

**Do NOT capture:** settings pages, login screens, error states, loading spinners, about pages, empty states.

### Action Timing Rules

These rules prevent the #1 source of capture failures:

**Web apps:**
- After every navigation: `wait: 3000` (minimum)
- For dynamic content (AJAX, WebSocket): use `wait_for` with a CSS selector for the loaded content
- NEVER use `networkidle` for apps with WebSocket/Socket.IO/SSE — use `domcontentloaded` + wait
- For charts/graphs: `wait: 5000` (rendering libraries need time)
- Before capture: always add a final `wait: 1000` buffer

**TUI apps:**
- After navigation keystrokes: `wait: 500`
- After typing text (search, input): `wait: 1000`
- Use `delay: 3000` as ready check, not `screen_stable` (unreliable for sparse views)
- For screens that load data: `wait: 2000`

**Desktop apps:**
- After launch: `wait: 3000` (window initialization)
- After click actions: `wait: 500`
- After state changes (new game, load file): `wait: 1000`

### Manifest Templates

#### Web App Template

```yaml
phantom: "1"
project: "{project-name}"
name: "{Display Name}"

type: web

setup:
  install: "{pip install -r requirements.txt | npm install}"
  build: "{npm run build | echo 'no build step'}"
  run: "{python app.py | npm start}"
  port: {port}
  env:
    PHANTOM_MODE: "1"
    # Add any other required env vars
  ready_check:
    url: "http://localhost:{port}/"
    strategy: "domcontentloaded"   # NOT networkidle for websocket apps
    timeout_ms: 15000

web:
  viewport:
    width: 1440
    height: 900
  device_scale: 2
  
captures:
  - id: dashboard
    name: "Dashboard"
    alt_text: "Main dashboard showing..."
    actions:
      - navigate: "/"
      - wait_for: ".dashboard-content"   # Wait for real content, not skeleton
      - wait: 2000                        # Buffer for charts/animations
    output: docs/screenshots/dashboard.png

processing:
  format: png
  border:
    style: drop-shadow

publishing:
  strategy: direct
  commit_message: "docs: update screenshots [phantom]"
```

#### TUI App Template

```yaml
phantom: "1"
project: "{project-name}"
name: "{Display Name}"

type: tui

setup:
  install: "python3 -m venv .venv && .venv/bin/pip install -e ."
  run: ".venv/bin/{entry-point}"
  env:
    PHANTOM_MODE: "1"
  ready_check:
    strategy: delay
    delay_ms: 3000

tui:
  terminal:
    width: 140
    height: 36
  renderer: silicon
  renderer_config:
    theme: Dracula
    font: JetBrains Mono
    window_controls: true
    padding: 20
    round_corner: 8

captures:
  - id: main-menu
    name: "Main Menu"
    alt_text: "Main menu showing..."
    actions: []   # First screen after launch
    output: docs/screenshots/main-menu.png

processing:
  format: png
  border:
    style: drop-shadow
```

#### Desktop App Template

```yaml
phantom: "1"
project: "{project-name}"
name: "{Display Name}"

type: desktop

setup:
  build: "{make | javac *.java | cargo build}"
  run: "{./build/myapp | java -cp . Main}"
  env:
    PHANTOM_MODE: "1"
    SDL_AUDIODRIVER: "dummy"
    DISPLAY: ":99"

desktop:
  display: ":99"
  resolution: "1280x720x24"
  window_title: "{Window Title}"
  startup_wait_ms: 3000

captures:
  - id: main-view
    name: "Main View"
    alt_text: "Application showing..."
    actions:
      - wait: 2000
    output: docs/screenshots/main-view.png

processing:
  format: png
  border:
    style: drop-shadow
```

### Verification

```bash
$PHANTOM validate .phantom.yml
```

Must pass with no errors. Warnings are acceptable.

## Stage 4: Test Single Capture

Before creating all captures, test ONE to verify the pipeline works end-to-end:

```bash
$PHANTOM run --project . --capture $(head -1 .phantom.yml | ... first capture id) --skip-publish 2>&1 | tail -20
```

If this isn't supported, run the full pipeline but expect only the first capture to matter:

```bash
$PHANTOM run --project . --skip-publish 2>&1
```

### Verify the output

```bash
# Check a screenshot was created
ls -la docs/screenshots/
# Check it's not blank (must have reasonable size and dimensions)
for f in docs/screenshots/*.png; do
  python3 -c "
from PIL import Image; import os; f='$f'
img=Image.open(f)
print(f'{f}: {img.size[0]}x{img.size[1]} {os.path.getsize(f)//1024}KB')
# Check for blank: sample pixel variance
import random; random.seed(42)
pixels = [img.getpixel((random.randint(0,img.size[0]-1), random.randint(0,img.size[1]-1))) for _ in range(100)]
unique = len(set(pixels))
print(f'  Pixel diversity: {unique}/100 unique (>5 = likely non-blank)')
" 2>/dev/null || file "$f"
done
```

**If the screenshot is blank or too small:**
- Check if the app actually started (look for error logs)
- Check if the ready check passed
- Increase wait times
- For web apps: verify the URL is correct and returns content
- For TUI apps: verify the terminal dimensions are large enough
- For desktop apps: verify xvfb is running and the window appeared

**If the screenshot shows the wrong state:**
- The action sequence isn't reaching the intended view
- Add more wait time between actions
- Verify selector names / key sequences are correct
- Run the app manually and trace the navigation path

Fix any issues before proceeding to the full capture set.

## Stage 5: Run All Captures

Once the first capture works, run the full pipeline:

```bash
$PHANTOM run --project . --skip-publish
```

Verify ALL screenshots:

```bash
echo "=== Screenshot Report ==="
for f in docs/screenshots/*.png; do
  python3 -c "
from PIL import Image; import os; f='$f'
img=Image.open(f)
size_kb=os.path.getsize(f)//1024
print(f'{os.path.basename(f):30s} {img.size[0]:5d}x{img.size[1]:<5d} {size_kb:4d}KB')
" 2>/dev/null || echo "$(basename $f): FAILED TO READ"
done
```

All screenshots should:
- Be non-blank (>10KB, >5 unique pixel samples)
- Have consistent dimensions (same width for same type)
- Have reasonable file sizes (50-500KB for web/TUI, up to 1.5MB for desktop)

## Stage 6: CI Workflow

Create `.github/workflows/update-screenshots.yml`:

### Framework-Specific CI Requirements

**Python web apps (Flask/Django/FastAPI):**
```yaml
- uses: actions/setup-python@v5
  with:
    python-version: '3.12'
- run: pip install -r requirements.txt
```

**Node.js apps (React/Next/Vue):**
```yaml
- uses: actions/setup-node@v4
  with:
    node-version: '20'
- run: npm ci
```

**SDL2/Native C/C++:**
```yaml
- run: |
    sudo apt-get update
    sudo apt-get install -y xvfb xdotool imagemagick \
      libsdl2-dev libsdl2-image-dev libsdl2-ttf-dev libsdl2-mixer-dev
```

**Java Swing/JavaFX:**
```yaml
- uses: actions/setup-java@v4
  with:
    distribution: 'temurin'
    java-version: '11'
- run: sudo apt-get install -y xvfb xdotool imagemagick
```

### Workflow Template

```yaml
name: Update Screenshots
on:
  release:
    types: [published]
  push:
    branches: [main, master]
    paths:
      - 'src/**'
      - 'templates/**'
      - 'static/**'
      - 'public/**'
      - '*.html'
      - '*.css'
      - '*.js'
      - '*.ts'
      - '*.py'
      - '*.c'
      - '*.cpp'
      - '*.java'
      - '*.rs'
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: phantom-screenshots
  cancel-in-progress: false

jobs:
  screenshots:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      # === FRAMEWORK-SPECIFIC SETUP (choose one) ===
      # [Insert appropriate setup from above]
      
      # === PHANTOM SETUP ===
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      
      - name: Install Phantom
        run: pip install 'phantom-docs>=0.3,<0.4'
      
      - name: Install runner dependencies
        run: |
          # For web: install Playwright
          # playwright install chromium --with-deps
          
          # For TUI: install silicon + fonts (with cache)
          # cargo install silicon --locked
          
          # For desktop: install X11 tools
          # sudo apt-get install -y xvfb xdotool imagemagick
      
      # === OPTIONAL: Playwright browser cache ===
      # - name: Cache Playwright browsers
      #   uses: actions/cache@v4
      #   with:
      #     path: ~/.cache/ms-playwright
      #     key: playwright-${{ runner.os }}
      
      # === OPTIONAL: Silicon cache ===
      # - name: Cache silicon
      #   uses: actions/cache@v4
      #   with:
      #     path: |
      #       ~/.cargo/registry
      #       ~/.cargo/git
      #       ~/.cargo/bin/silicon
      #     key: silicon-${{ runner.os }}
      
      # === OPTIONAL: Phantom state cache (incremental analysis) ===
      - name: Restore Phantom state
        uses: actions/cache@v4
        with:
          path: .phantom-state.json
          key: phantom-state-${{ github.ref }}
          restore-keys: phantom-state-
      
      # === RUN ===
      - name: Capture screenshots
        env:
          PHANTOM_MODE: "1"
          # ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}  # For AI features
        run: phantom run --project . --skip-publish
      
      # === PUBLISH ===
      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: phantom-screenshots
          path: docs/screenshots/
      
      - name: Commit and push
        run: |
          git config user.name "phantom[bot]"
          git config user.email "phantom[bot]@users.noreply.github.com"
          git add docs/screenshots/ README.md
          git diff --cached --quiet || {
            git commit -m "docs: update screenshots [phantom]"
            git pull --rebase origin $(git branch --show-current)
            git push
          }
      
      # === SAVE STATE ===
      - name: Save Phantom state
        uses: actions/cache/save@v4
        if: always()
        with:
          path: .phantom-state.json
          key: phantom-state-${{ github.ref }}-${{ github.sha }}
```

Customize the template for this specific project — don't leave commented-out sections. Remove what's not needed.

### Verification

```bash
# Validate the workflow YAML
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/update-screenshots.yml'))" && echo "Valid YAML"
```

## Stage 7: README Integration

### Detect Existing Screenshots

```bash
# Find any existing screenshot references in README
grep -n "img src\|!\[.*\](.*\.png\|.*\.jpg\|.*\.gif)" README.md 2>/dev/null
# Find existing screenshot files
find . -name "*.png" -o -name "*.PNG" -o -name "*.jpg" | grep -i "screen\|cap\|demo\|preview" 2>/dev/null
```

If existing screenshots found:
1. Note their locations in the README
2. Replace references with Phantom-managed versions
3. Remove old screenshot files (or move to a backup)
4. DO NOT break any existing README content

### Place Screenshots

Add `<img>` tags at natural locations in the README. Use retina-aware sizing:

```markdown
<img src="docs/screenshots/{id}.png" width="{logical_width}" alt="{descriptive alt text}">
```

Where `logical_width` = actual pixel width / device_scale (usually /2 for retina).

**Placement rules:**
- Put the hero shot near the top, after the project description but before installation
- Put feature screenshots in or near the section describing that feature
- Put mobile screenshots next to desktop screenshots, not in a separate section
- Don't add a generic "Screenshots" section if screenshots fit naturally elsewhere
- Write 1-2 sentences of context near each screenshot

Create `docs/screenshots/.gitkeep` to ensure the directory exists.

## Stage 8: Final Verification

Run the complete pipeline one more time to ensure everything works together:

```bash
# Clean previous captures
rm -f docs/screenshots/*.png

# Full run
$PHANTOM run --project . --skip-publish

# Verify all captures
echo "=== Final Verification ==="
expected=$(grep "id:" .phantom.yml | wc -l | tr -d ' ')
actual=$(ls docs/screenshots/*.png 2>/dev/null | wc -l | tr -d ' ')
echo "Expected: $expected captures"
echo "Actual: $actual screenshots"

if [ "$expected" = "$actual" ]; then
  echo "✅ All captures successful"
else
  echo "❌ MISMATCH — check for failed captures"
fi

# Verify sizes
for f in docs/screenshots/*.png; do
  size=$(stat -f%z "$f" 2>/dev/null || stat -c%s "$f" 2>/dev/null)
  if [ "$size" -lt 10000 ]; then
    echo "⚠️  $(basename $f) is only ${size} bytes — possibly blank"
  fi
done

# Verify manifest
$PHANTOM validate .phantom.yml
```

If any captures failed, fix them NOW before committing.

## Stage 9: Commit (do NOT push)

```bash
git add -A
git status

# Review what's being committed
git diff --cached --stat

git commit -m "feat: add Phantom automated documentation pipeline

- Demo mode (PHANTOM_MODE=1) with realistic fixture data
- $(ls docs/screenshots/*.png 2>/dev/null | wc -l | tr -d ' ') screenshot captures defined in .phantom.yml
- GitHub Actions workflow for automated screenshot updates
- README updated with documentation screenshots"
```

**Do NOT push.** Let the user review the changes first.

## Stage 10: Report

Provide a clean summary:

```
Phantom Onboarding Complete
═══════════════════════════
Project: {name}
Type: {web|tui|desktop|docker-compose}
Framework: {flask|react|sdl2|swing|etc}

Demo Mode:
- Activation: PHANTOM_MODE=1
- Auth: {bypassed|mocked|n/a}
- Data: {demo/data.json|seeded RNG|in-memory DB}
- External services: {mocked|none}

Captures: {N} screenshots
- {id}: {brief description}
- {id}: {brief description}
- ...

Files Created:
- .phantom.yml
- .github/workflows/update-screenshots.yml
- demo/data.json (if created)
- demo/seed.py (if created)
- docs/screenshots/*.png

Files Modified:
- {list of modified source files}
- README.md

Manual Steps Remaining:
1. Review changes: git diff HEAD~1
2. Push: git push origin {branch}
3. Trigger CI: gh workflow run update-screenshots.yml
4. (Optional) Set ANTHROPIC_API_KEY secret for AI features
5. (Optional) Enable "Allow GitHub Actions to create PRs" in repo settings
```
