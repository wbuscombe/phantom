"""Phantom CLI — entry point for all user-facing commands."""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from phantom import __version__

if TYPE_CHECKING:
    from phantom.conductor.orchestrator import JobReport

console = Console(stderr=True)
output = Console()


@click.group()
@click.version_option(__version__, prog_name="phantom")
def main() -> None:
    """Phantom — Automated documentation asset generation."""


@main.command()
@click.argument("manifest_path", type=click.Path(exists=True))
def validate(manifest_path: str) -> None:
    """Validate a .phantom.yml manifest file."""
    from phantom.exceptions import ManifestError
    from phantom.models import load_manifest

    try:
        manifest = load_manifest(manifest_path)
    except ManifestError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1) from None

    resolved = manifest.resolve_captures()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Capture")
    table.add_column("Viewport")
    table.add_column("Theme")
    table.add_column("Output")
    table.add_column("Status")

    for cap in resolved:
        skip_marker = "[dim]SKIP[/dim]" if cap.skip else "[green]OK[/green]"
        table.add_row(
            cap.id,
            f"{cap.viewport.width}x{cap.viewport.height}",
            cap.theme,
            cap.output,
            skip_marker,
        )

    panel_lines = [
        f"[bold]Schema version:[/bold] {manifest.phantom}",
        f"[bold]Project:[/bold] {manifest.project} ({manifest.name})",
        f"[bold]Setup:[/bold] {manifest.setup.type}",
        f"[bold]Fixtures:[/bold] {len(manifest.fixtures)} defined",
        f"[bold]Captures:[/bold] {len(manifest.captures)} defined",
        f"[bold]Processing:[/bold] {manifest.processing.format}, "
        f"{manifest.processing.border.style}",
        f"[bold]Publishing:[/bold] {manifest.publishing.strategy} to {manifest.publishing.branch}",
    ]

    output.print(Panel("\n".join(panel_lines), title="Manifest Summary", border_style="green"))
    output.print(table)
    output.print("[green]Manifest is valid.[/green]")


@main.command()
@click.option("--project", "-p", required=True, help="Project name or local path.")
@click.option("--manifest", "-m", type=click.Path(exists=True), help="Path to .phantom.yml.")
@click.option("--dry-run", is_flag=True, help="Run pipeline without committing.")
@click.option("--capture", "-c", "capture_id", help="Run a single capture by ID.")
@click.option("--group", "-g", help="Run captures in a named group.")
@click.option("--skip-publish", is_flag=True, help="Capture and process but skip git.")
@click.option("--force", is_flag=True, help="Commit even if below diff threshold.")
@click.option("--if-changed", is_flag=True, help="Skip if repo HEAD matches last captured SHA.")
@click.option(
    "--ai-analyst", is_flag=True, help="Generate manifest via AI instead of reading .phantom.yml."
)
@click.option(
    "--ai-document", is_flag=True, help="Use AI to update README with screenshots after capture."
)
@click.option(
    "--ai-auto", is_flag=True, help="Full autonomous pipeline: AI analyze + capture + document."
)
@click.option("--full", is_flag=True, help="Force full AI analysis (ignore incremental state).")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def run(
    project: str,
    manifest: str | None,
    dry_run: bool,
    capture_id: str | None,
    group: str | None,
    skip_publish: bool,
    force: bool,
    if_changed: bool,
    ai_analyst: bool,
    ai_document: bool,
    ai_auto: bool,
    full: bool,
    verbose: bool,
) -> None:
    """Run screenshot captures for a project."""
    from phantom.conductor.orchestrator import JobOptions, Orchestrator
    from phantom.exceptions import ManifestError
    from phantom.models import load_manifest
    from phantom.utils.logging import configure_logging

    configure_logging(verbose=verbose)

    # --ai-auto implies both --ai-analyst and --ai-document
    if ai_auto:
        ai_analyst = True
        ai_document = True

    console.print(f"[bold]Phantom v{__version__}[/bold] — run")
    console.print(f"  Project:      {project}")

    if dry_run:
        console.print("  Mode:         [yellow]dry-run[/yellow] (no commits)")
    if skip_publish:
        console.print("  Mode:         [yellow]skip-publish[/yellow] (no git)")
    if ai_auto:
        console.print("  Mode:         [cyan]ai-auto[/cyan] (analyze + capture + document)")
    elif ai_analyst:
        console.print("  Mode:         [cyan]ai-analyst[/cyan] (generating manifest)")
    if ai_document and not ai_auto:
        console.print("  Mode:         [cyan]ai-document[/cyan] (AI README update)")
    if capture_id:
        console.print(f"  Capture:      {capture_id}")
    if group:
        console.print(f"  Group:        {group}")
    if force:
        console.print("  Force:        [yellow]yes[/yellow] (ignore diff threshold)")
    if if_changed:
        console.print("  If-changed:   [yellow]yes[/yellow] (skip if unchanged)")

    # AI Analyst mode: generate manifest on the fly
    affected_capture_ids: list[str] | None = None
    if ai_analyst:
        import tempfile

        from phantom.analyst.analyzer import ProjectAnalyzer
        from phantom.analyst.state import AnalystStateManager

        project_path = Path(project).resolve()
        analyzer = ProjectAnalyzer()
        state_mgr = AnalystStateManager(project_path)

        # Use incremental if state exists and not forced full
        if not full and state_mgr.has_state():
            console.print("  Analyzing project (incremental)...")
            plan, diff_result = asyncio.get_event_loop().run_until_complete(
                analyzer.analyze_incremental(project_path, force_full=False)
            )
            console.print(
                f"  Diff: [cyan]{diff_result.recommendation}[/cyan] — {diff_result.reason}"
            )

            if diff_result.recommendation == "skip":
                console.print("  [green]No changes require re-capture.[/green]")
                return

            if diff_result.recommendation == "incremental" and diff_result.affected_capture_ids:
                affected_capture_ids = diff_result.affected_capture_ids
                console.print(f"  Incremental: {len(affected_capture_ids)} captures affected")
        else:
            console.print("  Analyzing project (full)...")
            plan = asyncio.get_event_loop().run_until_complete(analyzer.analyze(project_path))

        manifest_yaml = asyncio.get_event_loop().run_until_complete(
            analyzer.generate_manifest(plan, project_path)
        )

        console.print(f"  AI plan: {len(plan.captures)} captures, {len(plan.features)} features")
        if verbose:
            console.print("\n[dim]Generated manifest:[/dim]")
            console.print(manifest_yaml)

        # Write to temp file and load
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".phantom.yml", delete=False)  # noqa: SIM115
        tmp.write(manifest_yaml)
        tmp.close()
        manifest_path_resolved = Path(tmp.name)

        try:
            m = load_manifest(str(manifest_path_resolved))
        except ManifestError as e:
            console.print(f"[red]Error in generated manifest:[/red] {e}")
            console.print("[dim]Raw manifest written to: " + tmp.name + "[/dim]")
            raise SystemExit(1) from None
    else:
        # Resolve manifest path
        manifest_path_resolved = Path(manifest) if manifest else Path(project) / ".phantom.yml"
        if not manifest_path_resolved.exists():
            alt = Path(".phantom.yml")
            if alt.exists():
                manifest_path_resolved = alt
            else:
                console.print(f"[red]Error:[/red] Manifest not found at {manifest_path_resolved}")
                raise SystemExit(1)

        try:
            m = load_manifest(str(manifest_path_resolved))
        except ManifestError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise SystemExit(1) from None

    console.print(f"  Manifest:     {manifest_path_resolved}")
    console.print(f"  Captures:     {len(m.captures)}")
    console.print()

    # Resolve local project path
    project_path = Path(project).resolve()
    if not project_path.is_dir():
        # Try manifest's parent directory
        project_path = manifest_path_resolved.parent.resolve()

    options = JobOptions(
        dry_run=dry_run,
        skip_publish=skip_publish,
        force=force,
        capture_id=capture_id,
        capture_ids=affected_capture_ids,
        group=group,
        local_project=project_path,
        if_changed=if_changed,
        trigger_source="cli",
    )

    orchestrator = Orchestrator(manifest=m, options=options)

    start = time.monotonic()
    report = asyncio.get_event_loop().run_until_complete(orchestrator.run())
    elapsed = time.monotonic() - start

    # Print report
    _print_report(report, elapsed)

    # AI Documentation step (post-capture)
    if ai_document and not report.error:
        _run_ai_document(project_path, plan if ai_analyst else None, m, verbose)

    if report.error:
        raise SystemExit(1)


def _print_report(report: JobReport, elapsed: float) -> None:
    """Print a summary of the run."""
    from phantom.conductor.orchestrator import JobState

    status_color = "green" if report.state == JobState.COMPLETED else "red"
    status_text = report.state.value.upper()

    lines = [
        f"[bold]Status:[/bold]  [{status_color}]{status_text}[/{status_color}]",
    ]

    if report.skipped_unchanged:
        lines.append("[bold]Skip:[/bold]   [dim]unchanged since last capture[/dim]")
    else:
        lines.append(f"[bold]Total:[/bold]   {report.captures_total} captures")

        if report.captures_succeeded > 0:
            lines.append(f"[bold]OK:[/bold]      [green]{report.captures_succeeded}[/green]")
        if report.captures_failed > 0:
            lines.append(f"[bold]Failed:[/bold]  [red]{report.captures_failed}[/red]")
        if report.captures_changed > 0:
            lines.append(f"[bold]Changed:[/bold] [cyan]{report.captures_changed}[/cyan]")
        if report.captures_unchanged > 0:
            lines.append(f"[bold]Same:[/bold]    [dim]{report.captures_unchanged}[/dim]")

    if report.commit_sha:
        lines.append(f"[bold]Commit:[/bold]  {report.commit_sha[:8]}")
    if report.readme_updated:
        lines.append("[bold]README:[/bold]  updated")
    if report.stale_removed > 0:
        lines.append(f"[bold]Stale:[/bold]   {report.stale_removed} removed")

    lines.append(f"[bold]Trigger:[/bold] {report.trigger_source}")
    lines.append(f"[bold]Time:[/bold]    {elapsed:.1f}s")

    if report.error:
        lines.append(f"\n[red]Error:[/red] {report.error}")

    output.print(Panel("\n".join(lines), title="Phantom Run Report", border_style=status_color))


def _run_ai_document(
    project_path: Path,
    plan: object | None,
    manifest: object,
    verbose: bool,
) -> None:
    """Run the AI documentation writer to update README with screenshots."""
    from phantom.analyst.costs import CostTracker
    from phantom.analyst.documenter import DocumentationWriter, DocumenterError

    console.print("\n[cyan]Running AI documentation writer...[/cyan]")

    # Gather screenshot paths from manifest captures
    screenshots: list[Path] = []
    for cap in manifest.captures:  # type: ignore[attr-defined]
        output_path = project_path / cap.output
        if output_path.exists():
            screenshots.append(output_path)

    if not screenshots:
        console.print("[yellow]No screenshots found to document.[/yellow]")
        return

    console.print(f"  Screenshots: {len(screenshots)} found")

    cost_tracker = CostTracker()
    writer = DocumentationWriter(cost_tracker=cost_tracker)

    try:
        doc_update = asyncio.get_event_loop().run_until_complete(
            writer.write_docs(
                screenshots=screenshots,
                plan=plan,  # type: ignore[arg-type]
                project_dir=project_path,
            )
        )

        if doc_update.screenshots_placed > 0:
            readme_path = project_path / doc_update.target_file
            readme_path.write_text(doc_update.updated_content, encoding="utf-8")
            console.print(f"  [green]Updated {doc_update.target_file}[/green]")
            console.print(f"  Placed:   {doc_update.screenshots_placed} screenshots")
            if doc_update.sections_modified:
                console.print(f"  Modified: {', '.join(doc_update.sections_modified)}")
            if doc_update.new_sections_added:
                console.print(f"  Added:    {', '.join(doc_update.new_sections_added)}")
        else:
            console.print("  [dim]No screenshots placed.[/dim]")

        summary = cost_tracker.summary()
        if verbose:
            console.print(
                f"  [dim]Doc cost: ${summary['estimated_cost_usd']:.4f} "
                f"({summary['total_input_tokens']} in / "
                f"{summary['total_output_tokens']} out)[/dim]"
            )

    except DocumenterError as e:
        console.print(f"[red]Documentation error:[/red] {e}")


@main.command()
@click.option("--dir", "directory", default=".", help="Project directory to analyze.")
@click.option("--model", default="claude-sonnet-4-20250514", help="Claude model to use.")
@click.option("--max-cost", type=float, default=0.50, help="Maximum cost in USD.")
@click.option("--write", is_flag=True, help="Write the generated manifest to .phantom.yml.")
@click.option("--full", is_flag=True, help="Force full analysis (ignore incremental state).")
@click.option("--dry-run", is_flag=True, help="Show diff recommendation only, no API call.")
@click.option("--verbose", "-v", is_flag=True, help="Show full plan details.")
def analyze(
    directory: str,
    model: str,
    max_cost: float,
    write: bool,
    full: bool,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Analyze a project and generate a .phantom.yml manifest via AI."""
    from phantom.analyst.analyzer import AnalystDependencyError, AnalystError, ProjectAnalyzer
    from phantom.analyst.costs import CostTracker
    from phantom.analyst.state import AnalystStateManager
    from phantom.utils.logging import configure_logging

    configure_logging(verbose=verbose)

    project_dir = Path(directory).resolve()
    output.print(f"[bold]Phantom v{__version__}[/bold] — analyze")
    output.print(f"  Project: {project_dir}")
    output.print(f"  Model:   {model}")
    output.print(f"  Budget:  ${max_cost:.2f}")

    state_mgr = AnalystStateManager(project_dir)

    if not full and state_mgr.has_state() and not dry_run:
        output.print("  Mode:    [cyan]incremental[/cyan] (use --full to force full analysis)")
    elif full:
        output.print("  Mode:    [yellow]full[/yellow] (forced)")
    elif dry_run:
        output.print("  Mode:    [yellow]dry-run[/yellow] (diff check only)")

    output.print()

    cost_tracker = CostTracker(max_cost_usd=max_cost)
    analyzer = ProjectAnalyzer(model=model, cost_tracker=cost_tracker)

    try:
        # Detect project type
        project_type = asyncio.get_event_loop().run_until_complete(
            analyzer.detect_project_type(project_dir)
        )
        output.print(f"  Detected type: [cyan]{project_type}[/cyan]")

        # Dry-run mode: just show diff recommendation
        if dry_run:
            from phantom.analyst.diff import DiffAnalyzer

            state = state_mgr.load()
            diff_analyzer = DiffAnalyzer(project_dir)
            head_sha = diff_analyzer.get_head_sha()

            output.print(f"  HEAD:          {head_sha[:8] if head_sha else 'unknown'}")
            output.print(
                f"  Last analyzed: {state.last_analysis_commit[:8] if state.last_analysis_commit else 'never'}"
            )

            if state.last_analysis_commit:
                changed = diff_analyzer.get_changed_files(state.last_analysis_commit)
                classified = diff_analyzer.classify_changes(changed, project_type)
                output.print(f"  Changed files: {len(changed)}")
                output.print(f"    Visual:      {len(classified['visual'])}")
                output.print(f"    Non-visual:  {len(classified['non_visual'])}")
                if verbose:
                    for f in classified["visual"]:
                        output.print(f"      [cyan]{f}[/cyan]")
                    for f in classified["non_visual"]:
                        output.print(f"      [dim]{f}[/dim]")
            else:
                output.print("  [dim]No prior state — would run full analysis[/dim]")
            return

        # Incremental mode if state exists and not forced
        if not full and state_mgr.has_state():
            plan, diff_result = asyncio.get_event_loop().run_until_complete(
                analyzer.analyze_incremental(project_dir, force_full=False)
            )

            output.print(f"  Recommendation: [cyan]{diff_result.recommendation}[/cyan]")
            output.print(f"  Reason:         {diff_result.reason}")
            if diff_result.changed_files:
                output.print(f"  Changed files:  {len(diff_result.changed_files)}")
            if diff_result.affected_capture_ids:
                output.print(f"  Affected:       {', '.join(diff_result.affected_capture_ids)}")

            if diff_result.recommendation == "skip":
                output.print("\n[green]No changes require re-analysis.[/green]")
                summary = cost_tracker.summary()
                output.print(
                    f"[dim]Cost: $0.0000 (saved ~${max_cost * 0.3:.4f} vs full analysis)[/dim]"
                )
                return
        else:
            # Full analysis
            plan = asyncio.get_event_loop().run_until_complete(analyzer.analyze(project_dir))

            # Save state for future incremental runs
            manifest_yaml = asyncio.get_event_loop().run_until_complete(
                analyzer.generate_manifest(plan, project_dir)
            )
            from phantom.analyst.diff import DiffAnalyzer

            head_sha = DiffAnalyzer(project_dir).get_head_sha()
            state_mgr.update_after_analysis(
                commit_sha=head_sha,
                manifest_yaml=manifest_yaml,
                cost_usd=cost_tracker.estimated_cost_usd,
                input_tokens=cost_tracker.total_input_tokens,
                output_tokens=cost_tracker.total_output_tokens,
                recommendation="full",
            )

        if verbose:
            output.print()
            output.print("[bold]Features:[/bold]")
            for feat in plan.features:
                output.print(
                    f"  [{feat.importance}] {feat.name} ({feat.ui_type}) — {feat.description}"
                )

            output.print()
            output.print("[bold]Captures:[/bold]")
            for cap in plan.captures:
                output.print(f"  [{cap.importance}] {cap.id} — {cap.description}")
                if cap.navigation_actions:
                    for act in cap.navigation_actions:
                        output.print(f"      {act}")

            output.print()
            output.print("[bold]Doc Sections:[/bold]")
            for sec in plan.documentation_sections:
                output.print(f"  {sec.section_header} → {sec.target_file} ({sec.placement})")

        # Generate manifest
        manifest_yaml = asyncio.get_event_loop().run_until_complete(
            analyzer.generate_manifest(plan, project_dir)
        )

        if write:
            manifest_path = project_dir / ".phantom.yml"
            manifest_path.write_text(manifest_yaml)
            output.print(f"\n[green]Wrote manifest to {manifest_path}[/green]")
        else:
            output.print()
            output.print(Panel(manifest_yaml, title=".phantom.yml", border_style="cyan"))

        # Cost summary
        summary = cost_tracker.summary()
        output.print()
        output.print(
            f"[dim]Cost: ${summary['estimated_cost_usd']:.4f} "
            f"({summary['total_input_tokens']} in / {summary['total_output_tokens']} out, "
            f"{summary['call_count']} call(s))[/dim]"
        )

    except AnalystDependencyError:
        console.print(
            "[red]Error:[/red] The 'anthropic' package is required. "
            "Install with: pip install 'phantom-docs[ai]'"
        )
        raise SystemExit(1) from None
    except AnalystError as e:
        console.print(f"[red]Error:[/red] {e}")
        if hasattr(e, "raw_response") and e.raw_response:
            console.print(f"[dim]Raw response: {e.raw_response[:500]}[/dim]")
        raise SystemExit(1) from None


@main.command()
@click.option("--dir", "directory", default=".", help="Project directory to check.")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed file lists.")
def diff(directory: str, verbose: bool) -> None:
    """Show what changed since the last AI analysis (no API calls)."""
    from phantom.analyst.diff import DiffAnalyzer
    from phantom.analyst.state import AnalystStateManager

    project_dir = Path(directory).resolve()
    output.print(f"[bold]Phantom v{__version__}[/bold] — diff")
    output.print(f"  Project: {project_dir}")
    output.print()

    state_mgr = AnalystStateManager(project_dir)

    if not state_mgr.has_state():
        output.print("[dim]No analyst state found. Run 'phantom analyze' first.[/dim]")
        return

    state = state_mgr.load()
    diff_analyzer = DiffAnalyzer(project_dir)
    head_sha = diff_analyzer.get_head_sha()

    output.print(f"  HEAD:          {head_sha[:8] if head_sha else 'unknown'}")
    output.print(
        f"  Last analyzed: {state.last_analysis_commit[:8] if state.last_analysis_commit else 'never'}"
    )
    output.print(f"  Total analyses: {state.total_analyses}")
    output.print(
        f"  Breakdown:     {state.full_analyses} full, "
        f"{state.incremental_analyses} incremental, "
        f"{state.skipped_analyses} skipped"
    )
    output.print()

    if not state.last_analysis_commit:
        output.print("[dim]No prior commit recorded — would run full analysis.[/dim]")
        return

    # Detect project type for classification
    detected_type = _detect_project_type(project_dir) or "web"

    changed = diff_analyzer.get_changed_files(state.last_analysis_commit)
    if not changed:
        output.print("[green]No changes since last analysis.[/green]")
        output.print("  Recommendation: [green]skip[/green]")
        return

    classified = diff_analyzer.classify_changes(changed, detected_type)

    output.print(f"  Changed files: {len(changed)}")
    output.print(f"    Visual:      [cyan]{len(classified['visual'])}[/cyan]")
    output.print(f"    Non-visual:  [dim]{len(classified['non_visual'])}[/dim]")

    if verbose:
        if classified["visual"]:
            output.print("\n  [bold]Visual changes:[/bold]")
            for f in classified["visual"]:
                output.print(f"    [cyan]{f}[/cyan]")
        if classified["non_visual"]:
            output.print("\n  [bold]Non-visual changes:[/bold]")
            for f in classified["non_visual"]:
                output.print(f"    [dim]{f}[/dim]")

    # Determine recommendation
    if not classified["visual"]:
        output.print("\n  Recommendation: [green]skip[/green] (only non-visual changes)")
    else:
        output.print("\n  Recommendation: [yellow]re-analyze[/yellow] (visual changes detected)")
        if not verbose:
            output.print("  Run with --verbose to see changed files.")


def _detect_project_type(directory: Path) -> str | None:
    """Auto-detect project type from marker files in *directory*."""
    # Docker-compose takes precedence (may also contain package.json)
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        if (directory / name).exists():
            return "docker-compose"

    # Web projects (Node/Bun/Yarn)
    for name in ("package.json", "bun.lockb", "yarn.lock"):
        if (directory / name).exists():
            return "web"

    # TUI / native projects
    for name in ("Cargo.toml", "go.mod"):
        if (directory / name).exists():
            return "tui"

    return None


# Per-type sensible defaults for init scaffolding
_TYPE_DEFAULTS: dict[str, dict[str, str | int]] = {
    "web": {
        "build_command": "npm ci",
        "run_command": "npm run dev",
        "port": 3000,
        "ready_check_type": "http",
    },
    "tui": {
        "build_command": "cargo build --release",
        "run_command": "./target/release/myapp",
        "port": 0,
        "ready_check_type": "screen_stable",
    },
    "desktop": {
        "build_command": "npm ci && npm run build",
        "run_command": "npm run start",
        "port": 0,
        "ready_check_type": "delay",
    },
    "docker-compose": {
        "build_command": "docker compose build",
        "run_command": "docker compose up -d",
        "port": 8080,
        "ready_check_type": "http",
    },
}


@main.command()
@click.option("--dir", "directory", default=".", help="Project directory to scan.")
def init(directory: str) -> None:
    """Scaffold a new .phantom.yml manifest interactively."""
    target_dir = Path(directory).resolve()
    output.print("[bold]Phantom — Initialize Manifest[/bold]")
    output.print()

    # Auto-detect project type
    detected = _detect_project_type(target_dir)
    if detected:
        output.print(f"  Detected project type: [cyan]{detected}[/cyan]")

    project_type = click.prompt(
        "Project type",
        type=click.Choice(["web", "tui", "desktop", "docker-compose"]),
        default=detected or "web",
    )

    # Auto-derive project ID from directory name
    default_id = target_dir.name.lower().replace(" ", "-").replace("_", "-")
    project_id = click.prompt("Project ID (kebab-case)", type=str, default=default_id)
    project_name = click.prompt(
        "Display name", type=str, default=project_id.replace("-", " ").title()
    )

    defaults = _TYPE_DEFAULTS.get(project_type, _TYPE_DEFAULTS["web"])
    dev_command = click.prompt("Dev server command", type=str, default=defaults["run_command"])
    ready_type = str(defaults["ready_check_type"])
    default_port = int(defaults["port"])

    if ready_type == "http":
        dev_port = click.prompt("Dev server port", type=int, default=default_port)
    else:
        dev_port = default_port

    num_captures = click.prompt("Number of initial captures", type=int, default=3)

    # Build YAML content with comments
    build_cmd = str(defaults["build_command"])
    lines = [
        "# Phantom manifest — see https://github.com/wbuscombe/phantom",
        'phantom: "1"',
        f'project: "{project_id}"',
        f'name: "{project_name}"',
        "",
        "# How to build and run your project",
        "setup:",
        f"  type: {project_type}",
        "  build:",
        f"    - {build_cmd}",
        "  run:",
        f'    command: "{dev_command}"',
        "    env:",
        '      PHANTOM_MODE: "1"  # Signal to your app that Phantom is running',
        "    ready_check:",
        f"      type: {ready_type}",
    ]

    if ready_type == "http":
        lines.append(f'      url: "http://localhost:{dev_port}"')
        lines.append("      timeout: 30")
    elif ready_type == "screen_stable":
        lines.append("      timeout: 30")
        lines.append("      stability_window: 500")
    elif ready_type == "delay":
        lines.append("      seconds: 5")

    if project_type == "docker-compose":
        lines.append("  compose_file: docker-compose.yml")

    lines.extend(
        [
            "",
            "# Default settings applied to all captures",
            "capture_defaults:",
            "  viewport: { width: 1280, height: 800 }",
            "  theme: dark",
            "  device_scale: 2",
            "",
            "# Screenshots to capture",
            "captures:",
        ]
    )

    for i in range(1, num_captures + 1):
        lines.extend(
            [
                f"  - id: capture-{i}",
                f'    name: "Capture {i}"  # TODO: descriptive name',
            ]
        )
        if project_type in ("web", "docker-compose"):
            lines.append('    route: "/"  # TODO: set route')
        lines.extend(
            [
                f'    output: "docs/screenshots/capture-{i}.png"',
                "",
            ]
        )

    lines.extend(
        [
            "# Image processing pipeline",
            "processing:",
            "  format: png",
            "  optimize: true",
            "  border:",
            "    style: drop-shadow",
            "",
            "# Git publishing settings",
            "publishing:",
            "  branch: main",
            "  strategy: direct",
            "  readme_update: true",
        ]
    )

    manifest_path = target_dir / ".phantom.yml"
    if manifest_path.exists() and not click.confirm(f"{manifest_path} already exists. Overwrite?"):
        output.print("[yellow]Aborted.[/yellow]")
        return

    manifest_path.write_text("\n".join(lines) + "\n")
    output.print(f"\n[green]Created {manifest_path}[/green]")
    output.print("Edit the file to fill in routes, selectors, and output paths.")
    output.print("Run [bold]phantom validate .phantom.yml[/bold] to check your manifest.")


@main.command()
@click.option("--project", "-p", help="Filter by project name.")
def status(project: str | None) -> None:
    """Show Phantom status and recent run history."""
    from datetime import datetime

    from phantom.conductor.state import StateManager

    output.print(f"[bold]Phantom v{__version__}[/bold]")
    output.print()

    state_mgr = StateManager()

    # Show per-project summary if filtering
    if project:
        proj = state_mgr.get_project(project)
        summary_lines = [
            f"[bold]Project:[/bold]    {proj.project}",
            f"[bold]Total runs:[/bold] {proj.total_runs}",
            f"[bold]Last run:[/bold]   {datetime.fromtimestamp(proj.last_run).strftime('%Y-%m-%d %H:%M') if proj.last_run else 'never'}",
            f"[bold]Last SHA:[/bold]   {proj.last_sha[:8] if proj.last_sha else '-'}",
            f"[bold]Last status:[/bold] {proj.last_status or '-'}",
        ]
        if proj.last_diff_pct is not None:
            summary_lines.append(f"[bold]Last diff:[/bold]  {proj.last_diff_pct:.1f}%")
        output.print(Panel("\n".join(summary_lines), title="Project Summary", border_style="blue"))
        output.print()

    recent = state_mgr.get_recent_runs(project=project, limit=10)

    if not recent:
        output.print("[dim]No run history available.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Time")
    table.add_column("Project")
    table.add_column("Status")
    table.add_column("Captures")
    table.add_column("Changed")
    table.add_column("Commit")
    table.add_column("Trigger")
    table.add_column("Duration")

    for r in recent:
        dt = datetime.fromtimestamp(r.timestamp)
        time_str = dt.strftime("%Y-%m-%d %H:%M")

        status_color = "green" if r.status == "completed" else "red"
        status_str = f"[{status_color}]{r.status}[/{status_color}]"

        sha_str = r.commit_sha[:8] if r.commit_sha else "-"
        duration_str = f"{r.duration_ms / 1000:.1f}s"
        trigger_str = r.trigger_source or "-"

        table.add_row(
            time_str,
            r.project,
            status_str,
            str(r.captures_total),
            str(r.captures_changed),
            sha_str,
            trigger_str,
            duration_str,
        )

    output.print(table)


@main.command()
@click.option("--port", default=9443, help="Webhook listener port.")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def serve(port: int, verbose: bool) -> None:
    """Start the webhook listener and scheduler as a long-running process."""
    from phantom.conductor.queue import Job, JobQueue
    from phantom.conductor.scheduler import Scheduler
    from phantom.conductor.triggers import WebhookListener
    from phantom.utils.logging import configure_logging

    configure_logging(verbose=verbose)

    console.print(f"[bold]Phantom v{__version__}[/bold] — serve")
    console.print(f"  Port: {port}")

    webhook_secret = os.environ.get("PHANTOM_WEBHOOK_SECRET", "")
    if not webhook_secret:
        console.print("[red]Error:[/red] PHANTOM_WEBHOOK_SECRET environment variable is required")
        raise SystemExit(1)

    # Parse manifest map from PHANTOM_MANIFEST_MAP env var
    # Format: repo1=/path/to/manifest1.yml,repo2=/path/to/manifest2.yml
    manifest_map: dict[str, str] = {}
    raw_map = os.environ.get("PHANTOM_MANIFEST_MAP", "")
    if raw_map:
        for entry in raw_map.split(","):
            entry = entry.strip()
            if "=" in entry:
                repo, path = entry.split("=", 1)
                manifest_map[repo.strip()] = path.strip()

    console.print(f"  Manifests: {len(manifest_map)} configured")

    async def _serve() -> None:
        queue = JobQueue()

        async def handle_job(job: Job) -> None:
            """Process a queued job through the orchestrator."""
            from phantom.conductor.orchestrator import JobOptions, Orchestrator
            from phantom.models import load_manifest

            manifest = load_manifest(job.manifest_path)
            options = JobOptions(
                skip_publish=job.skip_publish,
                force=job.force,
                capture_id=job.capture_id,
                if_changed=job.if_changed,
                trigger_source=job.trigger_source,
                local_project=Path(job.manifest_path).parent,
            )
            orch = Orchestrator(manifest=manifest, options=options)
            await orch.run()

        # Start queue worker
        await queue.start(handle_job)

        # Start webhook listener
        listener = WebhookListener(
            queue=queue,
            webhook_secret=webhook_secret,
            port=port,
            manifest_map=manifest_map,
        )
        await listener.start()

        # Start scheduler with manifest triggers
        scheduler = Scheduler(queue=queue)
        for _repo_name, manifest_path in manifest_map.items():
            try:
                from phantom.models import load_manifest

                m = load_manifest(manifest_path)
                for trigger in m.triggers:
                    if trigger.type == "schedule" and trigger.cron:
                        from phantom.conductor.scheduler import ScheduleEntry

                        scheduler.add_entry(
                            ScheduleEntry(
                                project=m.project,
                                manifest_path=manifest_path,
                                cron_expression=trigger.cron,
                            )
                        )
            except Exception as e:
                console.print(
                    f"[yellow]Warning:[/yellow] Failed to load triggers from {manifest_path}: {e}"
                )

        await scheduler.start()

        console.print(f"[green]Phantom serving on port {port}[/green]")
        console.print("Press Ctrl+C to stop.")

        # Wait forever until interrupted
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
        finally:
            await scheduler.stop()
            await listener.stop()
            await queue.shutdown()

    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down...[/yellow]")


@main.command()
@click.option("--verbose", "-v", is_flag=True, help="Show passing checks too.")
def doctor(verbose: bool) -> None:
    """Check system dependencies for all runner types."""
    from phantom.conductor.requirements import check_all_dependencies
    from phantom.runners import available_runners

    output.print(f"[bold]Phantom v{__version__}[/bold] — doctor")
    output.print()

    results = asyncio.get_event_loop().run_until_complete(check_all_dependencies())

    table = Table(show_header=True, header_style="bold")
    table.add_column("Tool")
    table.add_column("Status")
    table.add_column("Version")
    table.add_column("Runner")
    table.add_column("Install hint")

    ok_count = 0
    missing_count = 0

    for r in results:
        if r.found:
            ok_count += 1
            if not verbose:
                continue
            status = "[green]OK[/green]"
        else:
            missing_count += 1
            status = "[red]MISSING[/red]"

        table.add_row(
            r.tool,
            status,
            r.version or "-",
            r.required_by,
            r.install_hint if not r.found else "",
        )

    output.print(table)

    runners = available_runners()
    output.print(f"\n  Registered runners: {', '.join(runners)}")
    output.print(f"  [green]{ok_count} OK[/green], [red]{missing_count} missing[/red]")

    if missing_count == 0:
        output.print("\n[green]All dependencies satisfied![/green]")
    else:
        output.print(
            f"\n[yellow]{missing_count} tool(s) missing.[/yellow] "
            "Install them to use the corresponding runners."
        )


@main.command()
@click.option("--days", default=7, help="Remove workspaces older than N days.")
@click.option(
    "--workspace-root", default="/tmp/phantom/workspace", help="Workspace root directory."
)
@click.option("--dry-run", is_flag=True, help="Show what would be removed without deleting.")
def gc(days: int, workspace_root: str, dry_run: bool) -> None:
    """Clean up stale Phantom workspaces older than the retention period."""
    root = Path(workspace_root)

    if not root.exists():
        output.print("[dim]No workspace directory found.[/dim]")
        return

    output.print(f"[bold]Phantom v{__version__}[/bold] — gc")
    output.print(f"  Workspace: {root}")
    output.print(f"  Retention: {days} days")
    output.print()

    import time as t

    cutoff = t.time() - (days * 86400)
    removed = 0
    total_size = 0

    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        # Skip the .locks directory
        if entry.name == ".locks":
            continue

        mtime = entry.stat().st_mtime
        if mtime < cutoff:
            # Calculate directory size
            dir_size = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
            total_size += dir_size
            size_mb = dir_size / (1024 * 1024)

            if dry_run:
                output.print(f"  [dim]Would remove:[/dim] {entry.name} ({size_mb:.1f} MB)")
            else:
                shutil.rmtree(entry, ignore_errors=True)
                output.print(f"  [red]Removed:[/red] {entry.name} ({size_mb:.1f} MB)")
            removed += 1

    total_mb = total_size / (1024 * 1024)
    if removed == 0:
        output.print("[dim]No stale workspaces found.[/dim]")
    elif dry_run:
        output.print(f"\n[yellow]Would remove {removed} workspace(s) ({total_mb:.1f} MB)[/yellow]")
    else:
        output.print(f"\n[green]Removed {removed} workspace(s) ({total_mb:.1f} MB)[/green]")


@main.command()
@click.option("--project", "-p", help="Filter by project name.")
@click.option(
    "--dir", "directory", multiple=True, help="Project directory to check for analyst state."
)
def costs(project: str | None, directory: tuple[str, ...]) -> None:
    """Show AI Analyst cost summary from run history and analyst state."""
    from phantom.conductor.state import DEFAULT_STATE_FILE, StateManager

    output.print(f"[bold]Phantom v{__version__}[/bold] — costs")
    output.print()

    # Show analyst state data if project dirs are specified
    if directory:
        from phantom.analyst.state import AnalystStateManager

        output.print("[bold]Analyst State (per-project):[/bold]")
        output.print()

        analyst_table = Table(show_header=True, header_style="bold")
        analyst_table.add_column("Project")
        analyst_table.add_column("Analyses")
        analyst_table.add_column("Full")
        analyst_table.add_column("Incremental")
        analyst_table.add_column("Skipped")
        analyst_table.add_column("Cost")
        analyst_table.add_column("Avg Cost/Run")
        analyst_table.add_column("Tokens (in/out)")

        total_cost = 0.0
        total_analyses = 0

        for d in directory:
            proj_dir = Path(d).resolve()
            mgr = AnalystStateManager(proj_dir)
            if not mgr.has_state():
                analyst_table.add_row(proj_dir.name, "-", "-", "-", "-", "-", "-", "-")
                continue

            state = mgr.load()
            total_cost += state.cumulative_cost_usd
            total_analyses += state.total_analyses
            avg_cost = (
                f"${state.cumulative_cost_usd / state.total_analyses:.4f}"
                if state.total_analyses > 0
                else "-"
            )
            analyst_table.add_row(
                proj_dir.name,
                str(state.total_analyses),
                str(state.full_analyses),
                str(state.incremental_analyses),
                str(state.skipped_analyses),
                f"${state.cumulative_cost_usd:.4f}",
                avg_cost,
                f"{state.cumulative_input_tokens}/{state.cumulative_output_tokens}",
            )

        output.print(analyst_table)
        output.print()
        output.print(
            f"[dim]Total analyst cost: ${total_cost:.4f} across {total_analyses} analyses[/dim]"
        )
        output.print()

    # Show conductor state data
    if not DEFAULT_STATE_FILE.exists():
        if not directory:
            output.print("[dim]No state file found. Run some captures first.[/dim]")
        return

    conductor_mgr = StateManager()
    conductor_state = conductor_mgr.load()

    if not conductor_state.projects:
        output.print("[dim]No projects tracked yet.[/dim]")
        return

    # Aggregate stats across all (or filtered) projects
    total_runs = 0
    projects_list = []

    for name, proj in conductor_state.projects.items():
        if project and name != project:
            continue
        total_runs += proj.total_runs
        projects_list.append(proj)

    if not projects_list:
        output.print(f"[dim]No data for project '{project}'.[/dim]")
        return

    output.print("[bold]Run History:[/bold]")

    lines = [
        f"[bold]Projects tracked:[/bold] {len(projects_list)}",
        f"[bold]Total runs:[/bold]       {total_runs}",
    ]

    # Per-project breakdown
    table = Table(show_header=True, header_style="bold")
    table.add_column("Project")
    table.add_column("Runs")
    table.add_column("Last Status")
    table.add_column("Last Run")

    from datetime import datetime

    for proj in projects_list:
        last_run_str = (
            datetime.fromtimestamp(proj.last_run).strftime("%Y-%m-%d %H:%M")
            if proj.last_run
            else "never"
        )
        status_str = proj.last_status or "-"
        table.add_row(proj.project, str(proj.total_runs), status_str, last_run_str)

    output.print(Panel("\n".join(lines), title="Cost Summary", border_style="cyan"))
    output.print(table)
    output.print()
    output.print(
        "[dim]Note: Use --dir to include per-project analyst cost breakdown. "
        "Detailed per-call token costs are shown in 'phantom analyze --verbose' "
        "output.[/dim]"
    )
