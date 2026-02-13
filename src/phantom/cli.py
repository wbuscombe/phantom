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
    verbose: bool,
) -> None:
    """Run screenshot captures for a project."""
    from phantom.conductor.orchestrator import JobOptions, Orchestrator
    from phantom.exceptions import ManifestError
    from phantom.models import load_manifest
    from phantom.utils.logging import configure_logging

    configure_logging(verbose=verbose)

    console.print(f"[bold]Phantom v{__version__}[/bold] — run")
    console.print(f"  Project:      {project}")

    if dry_run:
        console.print("  Mode:         [yellow]dry-run[/yellow] (no commits)")
    if skip_publish:
        console.print("  Mode:         [yellow]skip-publish[/yellow] (no git)")
    if capture_id:
        console.print(f"  Capture:      {capture_id}")
    if group:
        console.print(f"  Group:        {group}")
    if force:
        console.print("  Force:        [yellow]yes[/yellow] (ignore diff threshold)")
    if if_changed:
        console.print("  If-changed:   [yellow]yes[/yellow] (skip if unchanged)")

    # Resolve manifest path
    manifest_path = Path(manifest) if manifest else Path(project) / ".phantom.yml"
    if not manifest_path.exists():
        alt = Path(".phantom.yml")
        if alt.exists():
            manifest_path = alt
        else:
            console.print(f"[red]Error:[/red] Manifest not found at {manifest_path}")
            raise SystemExit(1)

    try:
        m = load_manifest(str(manifest_path))
    except ManifestError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1) from None

    console.print(f"  Manifest:     {manifest_path}")
    console.print(f"  Captures:     {len(m.captures)}")
    console.print()

    # Resolve local project path
    project_path = Path(project).resolve()
    if not project_path.is_dir():
        # Try manifest's parent directory
        project_path = manifest_path.parent.resolve()

    options = JobOptions(
        dry_run=dry_run,
        skip_publish=skip_publish,
        force=force,
        capture_id=capture_id,
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
