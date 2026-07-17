# Contributing to Phantom

Thanks for your interest in contributing! This guide covers the development workflow.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/wbuscombe/phantom.git
cd phantom

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Install Playwright browsers (for web runner tests)
playwright install chromium
```

## Running Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run only unit tests
pytest tests/unit/

# Run only integration tests
pytest tests/integration/ -m integration

# Run a specific test file
pytest tests/unit/test_models.py

# Run with coverage
pytest --cov=phantom --cov-report=term-missing
```

## Linting and Formatting

```bash
# Check for lint errors
ruff check src/ tests/

# Auto-fix lint errors
ruff check --fix src/ tests/

# Check formatting
ruff format --check src/ tests/

# Auto-format
ruff format src/ tests/

# Type checking
mypy src/phantom/ --ignore-missing-imports
```

### Pre-commit hooks (optional)

The repo ships a [`.pre-commit-config.yaml`](.pre-commit-config.yaml) that mirrors the CI
ruff gate. Enable it once and it runs on every commit:

```bash
pip install pre-commit
pre-commit install
```

## Code Style

- Python 3.12+ features are encouraged (`match`, `type` aliases, `|` unions)
- Use `from __future__ import annotations` in all modules
- Follow the existing patterns: Pydantic for data models, structlog for logging, async for I/O
- Keep functions focused and small
- Write docstrings for public APIs

## Commit Conventions

We use conventional commits:

- `feat:` — New feature
- `fix:` — Bug fix
- `docs:` — Documentation changes
- `test:` — Adding or updating tests
- `refactor:` — Code change that neither fixes a bug nor adds a feature
- `chore:` — Build process, CI, or tooling changes

Examples:
```
feat: add desktop runner for Electron apps
fix: handle missing ready_check gracefully
docs: add troubleshooting guide for silicon installation
```

## Pull Request Process

1. Fork the repository and create a branch from `main`
2. Make your changes with tests
3. Ensure all checks pass: `ruff check`, `ruff format --check`, `mypy`, `pytest`
4. Write a clear PR description explaining the change
5. Request a review

## Writing Runner Plugins

Phantom's runner system is extensible. See [docs/writing-runners.md](docs/writing-runners.md) for a complete guide on creating custom runners, including:

- Implementing the `BaseRunner` interface
- Registering via entry points
- Testing your runner
- Publishing as a standalone package

## Project Structure

```
src/phantom/
├── cli.py                 # Click CLI commands
├── models.py              # Pydantic manifest models
├── exceptions.py          # Exception hierarchy
├── conductor/             # Orchestration layer
│   ├── orchestrator.py    # Main pipeline coordinator
│   ├── workspace.py       # Workspace management
│   ├── requirements.py    # System dependency checking
│   ├── fixtures.py        # Test fixture execution
│   ├── state.py           # Run history persistence
│   ├── queue.py           # Job queue
│   ├── scheduler.py       # Cron scheduler
│   └── triggers.py        # Webhook listener
├── runners/               # Runner implementations
│   ├── base.py            # BaseRunner ABC
│   ├── web.py             # Playwright web runner
│   ├── terminal.py        # TUI runner
│   ├── docker.py          # Docker Compose runner
│   └── actions.py         # Shared action execution
├── darkroom/              # Image processing
│   └── pipeline.py        # Processing pipeline
├── publisher/             # Git publishing
│   ├── git.py             # Git operations
│   └── readme.py          # README sentinel updates
└── utils/                 # Shared utilities
    ├── process.py         # Async subprocess helpers
    └── logging.py         # Structured logging setup
```

## Questions?

Open an issue on [GitHub](https://github.com/wbuscombe/phantom/issues) or start a discussion.
