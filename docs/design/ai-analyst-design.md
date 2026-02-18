# AI Analyst Design Document

## Vision

The AI Analyst is the brain that sits between "code was pushed" and "Phantom captures screenshots." It reads the codebase, understands the application, decides what documentation is needed, generates the capture plan, and after captures are complete, writes and places the documentation. The `.phantom.yml` manifest becomes an internal intermediate artifact, not a human-authored file.

## Architecture

The Analyst runs in two phases:

**Phase A — Analysis & Planning (pre-capture):** Reads project files to understand what the app does. Identifies documentable views, workflows, and states. Generates a complete `.phantom.yml` manifest programmatically. This is Phase 5A.

**Phase B — Documentation & Publishing (post-capture):** Reviews captured screenshots. Writes descriptive captions and alt text. Decides where in the README each screenshot belongs. Generates the documentation text around screenshots. This is Phase 5B (future task).

## Cost Control

Hard limits per run (configurable):
- Max $0.50 per run
- Max 50K input tokens per run
- Max 10K output tokens per run
- Max 3 API calls per run
- Kill switch: `PHANTOM_ANALYST_ENABLED=false`

Cost projections using Claude Sonnet:
- ~20K tokens input per analysis = ~$0.06
- ~3K tokens output per analysis = ~$0.05
- Total per run: ~$0.10-0.15
- At weekly runs across 5 projects: ~$2-4/month

## File Selection Strategy

The Analyst does NOT read the entire codebase. It reads a curated set of files (under 30K tokens) that are most informative for understanding the app's user-facing features and navigation structure.

## Structured Output

The Analyst requests JSON responses matching the AnalysisPlan Pydantic schema. This ensures the output is parseable and validatable without post-processing.
