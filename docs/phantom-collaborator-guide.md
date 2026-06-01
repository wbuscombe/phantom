# Onboarding Your Desktop App to Phantom

Phantom is an automated screenshot documentation tool. It launches your app, takes screenshots at key states, and commits them to your repo — keeping your README visuals always up to date. It runs in CI (GitHub Actions) so screenshots refresh automatically when your code changes.

## Prerequisites

- **Python 3.10+**
- **Git repo on GitHub** (Phantom commits screenshots back to your repo)
- **Claude Code** (Anthropic's CLI tool — this runs the onboarding)
- **Anthropic API key** (for the AI Analyst that reads your code and generates a capture plan)

## What Phantom Does for Desktop Apps

Your app runs inside a headless X server (Xvfb) in CI. Phantom uses xdotool to send clicks/keystrokes and ImageMagick to capture screenshots. You don't need to modify your app's source code — Phantom drives it externally.

Supported frameworks: SDL2, Java Swing/JavaFX, Qt, GTK, Electron, or anything that opens a window.

## Step 1: Install Phantom

```bash
pip install 'phantom-docs>=0.3,<0.4'
```

Verify:
```bash
phantom --version
```

## Step 2: Add Demo Mode to Your App

Phantom needs your app to start in a predictable, self-contained state — no login prompts, no network dependencies, no randomness. This is called "demo mode."

Add an environment variable check to your app:

```
If PHANTOM_MODE=1:
  - Skip authentication / login screens
  - Use hardcoded or bundled demo data
  - Seed any RNG with a fixed value (e.g., srand(42))
  - Disable audio (or set SDL_AUDIODRIVER=dummy for SDL apps)
  - Don't connect to external services
```

The goal: `PHANTOM_MODE=1 ./your-app` should launch straight into a visually interesting, reproducible state every time.

## Step 3: Run the Onboarding Prompt

The onboarding prompt is a detailed guide that Claude Code follows to set up Phantom for your project. It lives in the Phantom repo:

```
https://github.com/wbuscombe/phantom/blob/main/docs/onboarding-prompt.md
```

Open Claude Code in your project directory and give it this prompt:

```
Follow the Phantom onboarding guide at ~/path/to/phantom/docs/onboarding-prompt.md 
to onboard this project. This is a desktop application (type: desktop).

The project is at: [your project path]
The Phantom CLI is available as: phantom
```

If you don't have the Phantom repo cloned locally, you can just tell Claude Code:

```
Install phantom-docs (pip install 'phantom-docs>=0.3,<0.4'), then onboard this 
desktop app project to Phantom. 

This is a [SDL2 / Java Swing / Qt / Electron / etc.] application.
The build command is: [make / gradle build / npm run build / etc.]
The run command is: [./my-app / java -jar my-app.jar / etc.]

Phantom is an automated screenshot tool. I need:
1. Demo mode (PHANTOM_MODE=1 env var) added to my app for reproducible state
2. A .phantom.yml manifest with type: desktop
3. A GitHub Actions workflow at .github/workflows/update-screenshots.yml
4. Screenshots placed in docs/screenshots/ and linked in the README

The desktop runner uses xvfb + xdotool + imagemagick in CI.
Use 'phantom validate' to verify the manifest.
Use 'phantom run --project . --skip-publish' to test captures locally.
```

## Step 4: Test Locally (Linux or WSL)

Desktop captures require X11 tools. On Ubuntu/Debian:

```bash
sudo apt install xvfb xdotool imagemagick
```

Framework-specific deps:
- **SDL2:** `sudo apt install libsdl2-dev libsdl2-image-dev libsdl2-ttf-dev`
- **Java Swing:** Just need a JDK (`sudo apt install default-jdk`)
- **Qt:** `sudo apt install qt6-base-dev` (or qt5 equivalent)

Then test:

```bash
PHANTOM_MODE=1 phantom run --project . --skip-publish
```

This launches your app in Xvfb, takes all the screenshots defined in `.phantom.yml`, and saves them to `docs/screenshots/`. Check that they look correct.

## Step 5: Set Up CI

The onboarding prompt creates a GitHub Actions workflow for you. You need to add one secret to your repo:

```bash
# From your project directory
echo "YOUR_ANTHROPIC_API_KEY" | gh secret set ANTHROPIC_API_KEY
```

Then push. The workflow triggers on pushes to main and takes fresh screenshots automatically.

## What You Get

After onboarding, your repo will have:

```
.phantom.yml                              # Capture manifest
.github/workflows/update-screenshots.yml  # CI workflow
docs/screenshots/                         # Auto-generated screenshots
README.md                                 # Updated with screenshot links
```

Every push to main regenerates screenshots if your UI changed. The bot commits them back with a message like:

```
docs(screenshots): update 3 of 5 captures [phantom]
```

## Quick Reference

| Command | What it does |
|---------|-------------|
| `phantom validate .phantom.yml` | Check your manifest for errors |
| `phantom run --project . --skip-publish` | Capture screenshots locally (no git commit) |
| `phantom run --project .` | Capture and commit |
| `phantom analyze --verbose` | AI reads your code and suggests captures |
| `phantom snapshots --dir .` | List snapshots you've recorded (manual — not created automatically) |
| `phantom rollback --dir . --latest` | Restore screenshots from your last snapshot. Forward-only (makes a new commit); **cannot** remove a frame already pushed to a remote |

## Troubleshooting

**Blank screenshots:** Your app isn't rendering in time. Increase `startup_wait_ms` in `.phantom.yml` or add longer `wait` actions before captures.

**Window not found:** xdotool can't find your app's window. Check `window_title` in your manifest matches what your app actually sets as its window title. Run `xdotool search --name "YourApp"` manually to debug.

**Audio errors in CI:** Set `SDL_AUDIODRIVER=dummy` in the env section of your manifest (SDL apps) or disable audio init in demo mode.

**Build fails in CI:** Make sure all build dependencies are listed in the workflow's apt-get install step.
