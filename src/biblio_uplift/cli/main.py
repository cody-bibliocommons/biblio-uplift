"""CLI entry point for biblio-uplift."""

from __future__ import annotations

import logging
import shlex
import sys
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.table import Table

from biblio_uplift import __version__
from biblio_uplift.config.loader import get_config_dir, list_configs, load_config
from biblio_uplift.config.schema import ProjectConfig
from biblio_uplift.core.pipeline import Pipeline, PipelineContext
from biblio_uplift.core.ssh import SSHRunner
from biblio_uplift.core.steps import get_cleanup_steps, get_upgrade_steps
from biblio_uplift.history.audit import read_history, record_run

console = Console()
logger = logging.getLogger(__name__)


def setup_logging(debug: bool = False) -> None:
    from logging.handlers import RotatingFileHandler

    from rich.logging import RichHandler

    from biblio_uplift.paths import get_project_root

    log_dir = get_project_root() / "logs"
    log_dir.mkdir(exist_ok=True)

    level = logging.DEBUG if debug else logging.INFO

    handlers: list[logging.Handler] = [
        RichHandler(rich_tracebacks=True, show_path=False, level=logging.INFO),
        RotatingFileHandler(
            log_dir / "upgrade.log",
            maxBytes=10_000_000,
            backupCount=5,
        ),
    ]

    if debug:
        debug_handler = RotatingFileHandler(
            log_dir / "debug.log",
            maxBytes=50_000_000,
            backupCount=3,
        )
        debug_handler.setLevel(logging.DEBUG)
        debug_handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
        handlers.append(debug_handler)

    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=handlers,
    )


def _load_project_config(project: str) -> ProjectConfig:
    config_path = get_config_dir() / f"{project}.yml"
    if not config_path.exists():
        console.print(f"[red]Config not found: {config_path}[/red]")
        sys.exit(1)
    return load_config(config_path)


def _build_ssh(cfg: ProjectConfig) -> SSHRunner:
    return SSHRunner(
        host=cfg.ssh_host,
        user=cfg.ssh_user,
        key_path=cfg.ssh_key,
        sudo=cfg.sudo,
        port=cfg.ssh_port,
    )


def build_upgrade_pipeline() -> Pipeline:
    return Pipeline(name="upgrade", steps=get_upgrade_steps())


def build_cleanup_pipeline() -> Pipeline:
    return Pipeline(name="cleanup", steps=get_cleanup_steps())


def _print_summary(pipeline: Pipeline, success: bool) -> None:
    table = Table(title=f"Pipeline: {pipeline.name}")
    table.add_column("Step")
    table.add_column("Status")
    table.add_column("Duration")
    table.add_column("Message")

    for s in pipeline.get_summary():
        style = {"success": "green", "failed": "red", "skipped": "dim"}.get(s["status"], "")
        table.add_row(
            s["name"],
            s["status"],
            f"{s['duration']:.1f}s",
            s["error"] or s["message"],
            style=style,
        )

    console.print(table)
    if success:
        console.print(f"[green]✓ {pipeline.name} completed in {pipeline.duration:.1f}s[/green]")
    else:
        console.print(f"[red]✗ {pipeline.name} failed after {pipeline.duration:.1f}s[/red]")


@click.group(invoke_without_command=True)
@click.option("--debug", is_flag=True, help="Enable verbose debug logging to logs/debug.log")
@click.option("--version", is_flag=True, help="Show version and exit")
@click.pass_context
def cli(ctx: click.Context, debug: bool, version: bool) -> None:
    """biblio-uplift: Server upgrade and maintenance tool."""
    if version:
        console.print(f"biblio-uplift {__version__}")
        raise SystemExit(0)
    setup_logging(debug=debug)
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug
    if ctx.invoked_subcommand is None:
        from biblio_uplift.tui.app import UpgradeApp

        app = UpgradeApp()
        app.run()


@cli.command()
@click.argument("project")
@click.option("--non-interactive", is_flag=True, help="Run without prompts")
@click.option("--skip-reboot", is_flag=True)
@click.option("--skip-os-update", is_flag=True)
@click.option("--skip-backup", is_flag=True)
@click.option("--skip-git", is_flag=True, help="Skip git pull")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.option("--no-hooks", is_flag=True, help="Skip pre/post upgrade hooks")
@click.option("--on-failure", default=None, help="Shell command to run on failure (overrides config)")
@click.option("--start-from", default=None, help="Skip steps before this one (e.g. docker_pull)")
def run(
    project: str,
    non_interactive: bool,
    skip_reboot: bool,
    skip_os_update: bool,
    skip_backup: bool,
    skip_git: bool,
    dry_run: bool,
    no_hooks: bool,
    on_failure: str | None,
    start_from: str | None,
) -> None:
    """Run the upgrade pipeline for a project."""
    cfg = _load_project_config(project)
    if on_failure:
        cfg = cfg.model_copy(update={"on_failure_cmd": on_failure})
    ssh = _build_ssh(cfg)
    pipeline = build_upgrade_pipeline()

    skip_steps: set[str] = set()
    if skip_reboot or cfg.skip_reboot:
        skip_steps.add("reboot")
    if skip_os_update or cfg.skip_os_update:
        skip_steps.add("os_update")
    if skip_backup:
        skip_steps.update({"backup_files", "backup_volumes", "backup_cleanup"})
    if no_hooks:
        skip_steps.update({"pre_hooks", "post_hooks"})
    if skip_git:
        skip_steps.add("git_pull")
    if start_from:
        step_names = [s.name for s in get_upgrade_steps()]
        if start_from not in step_names:
            console.print(f"[red]Unknown step: {start_from}. Available: {', '.join(step_names)}[/red]")
            raise SystemExit(1)
        for name in step_names:
            if name == start_from:
                break
            skip_steps.add(name)

    if not non_interactive:
        click.confirm(
            f"Run upgrade on {cfg.name} ({cfg.ssh_host})?",
            abort=True,
        )

    ctx = PipelineContext(
        config=cfg,
        ssh=ssh,
        dry_run=dry_run,
        skip_steps=skip_steps,
        on_output=lambda line: console.print(f"  {line}"),
    )

    success = pipeline.run(ctx)

    record_run(
        project=cfg.name,
        pipeline=pipeline.name,
        steps=pipeline.get_summary(),
        success=success,
        duration=pipeline.duration,
    )

    from biblio_uplift.core.state import clear_resume_state

    clear_resume_state()

    _print_summary(pipeline, success)
    sys.exit(0 if success else 1)


@cli.command()
@click.argument("project")
@click.option("--non-interactive", is_flag=True, help="Run without prompts")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
def cleanup(project: str, non_interactive: bool, dry_run: bool) -> None:
    """Run the cleanup pipeline for a project."""
    cfg = _load_project_config(project)
    ssh = _build_ssh(cfg)
    pipeline = build_cleanup_pipeline()

    if not non_interactive:
        click.confirm(
            f"Run cleanup on {cfg.name} ({cfg.ssh_host})?",
            abort=True,
        )

    ctx = PipelineContext(
        config=cfg,
        ssh=ssh,
        on_output=lambda line: console.print(f"  {line}"),
        dry_run=dry_run,
    )

    success = pipeline.run(ctx)

    record_run(
        project=cfg.name,
        pipeline=pipeline.name,
        steps=pipeline.get_summary(),
        success=success,
        duration=pipeline.duration,
    )

    _print_summary(pipeline, success)
    sys.exit(0 if success else 1)


@cli.command()
@click.argument("project")
@click.option("--backup", "backup_ts", default=None, help="Backup timestamp to restore. Defaults to latest.")
@click.option("--non-interactive", is_flag=True)
def restore(project, backup_ts, non_interactive):
    """Restore a project from a backup archive."""
    config = _load_project_config(project)
    ssh = SSHRunner(
        host=config.ssh_host,
        user=config.ssh_user,
        key_path=config.ssh_key,
        sudo=config.sudo,
        port=config.ssh_port,
    )

    backup_dir = shlex.quote(str(config.backup_dir))

    # Find the backup to restore
    if backup_ts:
        file_pattern = f"{config.name}_files_{backup_ts}.tar.gz"
    else:
        # Find latest file backup
        result = ssh.run(f"ls -1t {backup_dir}/{shlex.quote(config.name)}_files_*.tar.gz 2>/dev/null | head -1")
        if not result.ok or not result.stdout.strip():
            console.print("[red]No backups found.[/red]")
            raise SystemExit(1)
        file_pattern = Path(result.stdout.strip()).name
        backup_ts = file_pattern.replace(f"{config.name}_files_", "").replace(".tar.gz", "")

    console.print(f"Restoring [bold]{config.name}[/bold] from backup {backup_ts}")

    # Verify backup exists
    file_backup = f"{config.backup_dir}/{file_pattern}"
    result = ssh.run(f"test -f {shlex.quote(file_backup)} && echo exists")
    if not result.ok or "exists" not in result.stdout:
        console.print(f"[red]Backup not found: {file_backup}[/red]")
        raise SystemExit(1)

    # List volume backups for this timestamp
    vol_result = ssh.run(f"ls -1 {backup_dir}/*_{backup_ts}.tar.gz 2>/dev/null")
    vol_files = (
        [
            line.strip()
            for line in vol_result.stdout.splitlines()
            if line.strip() and config.name + "_files_" not in line
        ]
        if vol_result.ok
        else []
    )

    console.print(f"  File backup: {file_backup}")
    for vf in vol_files:
        console.print(f"  Volume backup: {vf}")

    if not non_interactive:
        click.confirm("This will stop services and overwrite current files. Continue?", abort=True)

    def out(line):
        console.print(f"  {line}")

    # Step 1: Stop services
    out("Stopping services...")
    from biblio_uplift.core.steps.docker import _compose_cmd

    down_cmd = _compose_cmd(config) + " down"
    ssh.run(down_cmd, timeout=120, on_output=out)

    # Step 2: Restore files
    out(f"Restoring files from {file_backup}...")
    result = ssh.run(f"tar xzf {shlex.quote(file_backup)} -C /", timeout=300, on_output=out)
    if not result.ok:
        console.print(f"[red]File restore failed: {result.stderr}[/red]")
        raise SystemExit(1)

    # Step 3: Restore volumes
    for vf in vol_files:
        vf_name = Path(vf).name
        # Extract volume name: everything before _TIMESTAMP.tar.gz
        vol_name = vf_name.replace(f"_{backup_ts}.tar.gz", "")
        out(f"Restoring volume {vol_name}...")
        result = ssh.run(
            f"docker run --rm -v {shlex.quote(vol_name)}:/volume -v {shlex.quote(str(config.backup_dir))}:/backup "
            f"alpine sh -c 'rm -rf /volume/* && tar xzf {shlex.quote(f'/backup/{vf_name}')} -C /volume'",
            timeout=300,
            on_output=out,
        )
        if not result.ok:
            console.print(f"[red]Volume restore failed for {vol_name}: {result.stderr}[/red]")

    # Step 4: Bring services back up
    out("Starting services...")
    up_cmd = _compose_cmd(config) + " up -d"
    ssh.run(up_cmd, timeout=120, on_output=out)

    console.print("[green]Restore complete.[/green]")

    record_run(
        project=config.name,
        pipeline="restore",
        steps=[
            {
                "name": "restore",
                "status": "success",
                "duration": 0,
                "message": f"Restored from {backup_ts}",
                "error": "",
            }
        ],
        success=True,
        duration=0,
    )


@cli.command()
def resume():
    """Resume an upgrade after reboot (if the controlling session was lost)."""
    from biblio_uplift.core.state import clear_resume_state, load_resume_state

    state_data = load_resume_state()
    if not state_data:
        console.print("No resume state found. Nothing to resume.")
        raise SystemExit(0)

    project_name = state_data["project"]
    completed_steps = set(state_data.get("completed_steps", []))
    skip_steps = set(state_data.get("skip_steps", []))
    saved_state = state_data.get("state", {})

    console.print(f"Resuming upgrade for [bold]{project_name}[/bold]")
    console.print(f"Completed steps: {', '.join(completed_steps)}")

    config = _load_project_config(project_name)
    ssh = _build_ssh(config)

    # Build pipeline, skip already-completed steps + reboot itself
    all_skip = completed_steps | skip_steps | {"reboot"}
    pipeline = build_upgrade_pipeline()

    ctx = PipelineContext(
        config=config,
        ssh=ssh,
        on_output=lambda line: console.print(f"  {line}"),
        skip_steps=all_skip,
    )
    ctx.state.update(saved_state)

    success = pipeline.run(ctx)

    record_run(
        project=config.name,
        pipeline="upgrade-resume",
        steps=pipeline.get_summary(),
        success=success,
        duration=pipeline.duration,
    )

    _print_summary(pipeline, success)
    clear_resume_state()
    sys.exit(0 if success else 1)


@cli.group("config")
def config_group() -> None:
    """Manage project configurations."""


@config_group.command("list")
def config_list() -> None:
    """List all project configurations."""
    configs = list_configs(get_config_dir())
    if not configs:
        console.print("[yellow]No configs found.[/yellow]")
        return

    table = Table(title="Project Configurations")
    table.add_column("Name")
    table.add_column("Host")
    table.add_column("Project Dir")

    for cfg in configs:
        table.add_row(cfg.name, cfg.ssh_host, str(cfg.project_dir))

    console.print(table)


@config_group.command("show")
@click.argument("project")
def config_show(project: str) -> None:
    """Show configuration details for a project."""
    cfg = _load_project_config(project)
    console.print(yaml.dump(cfg.model_dump(mode="json"), default_flow_style=False, sort_keys=False))


@config_group.command("create")
@click.argument("name")
@click.option("--host", required=True, help="SSH hostname")
@click.option("--project-dir", required=True, help="Remote project directory")
@click.option("--ssh-user", default="ansible")
@click.option("--ssh-key", default="~/.ssh/integration.pem")
def config_create(name: str, host: str, project_dir: str, ssh_user: str, ssh_key: str) -> None:
    """Create a new project configuration."""
    from biblio_uplift.config.loader import save_config

    config = ProjectConfig(
        name=name,
        ssh_host=host,
        project_dir=Path(project_dir),
        ssh_user=ssh_user,
        ssh_key=Path(ssh_key),
    )
    path = get_config_dir() / f"{name}.yml"
    if path.exists():
        console.print(f"[red]Config {name} already exists at {path}[/red]")
        raise SystemExit(1)
    save_config(config, path)
    console.print(f"Created config: {path}")


@config_group.command("validate")
@click.argument("project")
def config_validate(project):
    """Validate a project config by testing SSH, Docker, and paths."""
    config = _load_project_config(project)
    console.print(f"Validating {config.name} ({config.ssh_host})...")

    try:
        ssh = SSHRunner(
            host=config.ssh_host,
            user=config.ssh_user,
            key_path=config.ssh_key,
            sudo=config.sudo,
            port=config.ssh_port,
        )
    except FileNotFoundError as e:
        console.print(f"[red]SSH key error: {e}[/red]")
        raise SystemExit(1) from None

    # Test SSH
    result = ssh.test_connection()
    if result.ok:
        console.print("  [green]✓[/green] SSH connection")
    else:
        console.print(f"  [red]✗[/red] SSH connection: {result.stderr}")
        raise SystemExit(1)

    # Test Docker
    result = ssh.run("docker info --format '{{.ServerVersion}}'")
    if result.ok:
        console.print(f"  [green]✓[/green] Docker {result.stdout.strip()}")
    else:
        console.print(f"  [red]✗[/red] Docker: {result.stderr}")

    # Test project dir
    result = ssh.run(f"test -d {shlex.quote(str(config.project_dir))} && echo exists")
    if result.ok and "exists" in result.stdout:
        console.print(f"  [green]✓[/green] Project dir: {config.project_dir}")
    else:
        console.print(f"  [red]✗[/red] Project dir not found: {config.project_dir}")

    # Test compose files
    for cf in config.compose_files:
        path = f"{config.project_dir}/{cf}"
        result = ssh.run(f"test -f {shlex.quote(path)} && echo exists")
        if result.ok and "exists" in result.stdout:
            console.print(f"  [green]✓[/green] Compose file: {cf}")
        else:
            console.print(f"  [red]✗[/red] Compose file not found: {cf}")

    # Test backup dir (or parent)
    parent = str(Path(config.backup_dir).parent)
    result = ssh.run(f"test -d {shlex.quote(parent)} && echo exists")
    if result.ok:
        console.print(f"  [green]✓[/green] Backup dir parent: {parent}")
    else:
        console.print(f"  [yellow]![/yellow] Backup dir parent doesn't exist: {parent} (will be created)")

    console.print("[green]Validation complete.[/green]")


@cli.command("run-all")
@click.option("--non-interactive", is_flag=True)
@click.option("--skip-reboot", is_flag=True)
@click.option("--skip-os-update", is_flag=True)
@click.option("--dry-run", is_flag=True)
@click.option("--projects", default=None, help="Comma-separated project names. Defaults to all.")
def run_all(non_interactive, skip_reboot, skip_os_update, dry_run, projects):
    """Run upgrades on multiple projects sequentially."""
    all_configs = list_configs(get_config_dir())
    if projects:
        names = [n.strip() for n in projects.split(",")]
        configs = [c for c in all_configs if c.name in names]
        missing = set(names) - {c.name for c in configs}
        if missing:
            console.print(f"[red]Unknown projects: {', '.join(missing)}[/red]")
            raise SystemExit(1)
    else:
        configs = all_configs

    if not configs:
        console.print("No projects found.")
        raise SystemExit(0)

    console.print(f"Running upgrades for: {', '.join(c.name for c in configs)}")
    if not non_interactive:
        click.confirm("Continue?", abort=True)

    results = {}
    for config in configs:
        console.print(f"\n{'=' * 60}")
        console.print(f"[bold]Upgrading {config.name} ({config.ssh_host})[/bold]")
        console.print(f"{'=' * 60}")

        try:
            ssh = SSHRunner(
                host=config.ssh_host,
                user=config.ssh_user,
                key_path=config.ssh_key,
                sudo=config.sudo,
                port=config.ssh_port,
            )
        except FileNotFoundError as e:
            console.print(f"[red]SSH key error: {e}[/red]")
            results[config.name] = False
            continue

        skip_steps = set()
        if skip_reboot or config.skip_reboot:
            skip_steps.add("reboot")
        if skip_os_update or config.skip_os_update:
            skip_steps.add("os_update")

        pipeline = build_upgrade_pipeline()
        ctx = PipelineContext(
            config=config,
            ssh=ssh,
            on_output=lambda line: console.print(f"  {line}"),
            skip_steps=skip_steps,
            dry_run=dry_run,
        )

        success = pipeline.run(ctx)
        results[config.name] = success

        record_run(
            project=config.name,
            pipeline="upgrade",
            steps=pipeline.get_summary(),
            success=success,
            duration=pipeline.duration,
        )

    # Summary
    console.print(f"\n{'=' * 60}")
    console.print("[bold]Summary[/bold]")
    for name, ok in results.items():
        icon = "[green]✓[/green]" if ok else "[red]✗[/red]"
        console.print(f"  {icon} {name}")

    all_ok = all(results.values())
    sys.exit(0 if all_ok else 1)


@cli.command()
@click.option("--project", default=None, help="Filter by project name")
@click.option("--last", default=20, type=int, help="Number of recent entries")
def history(project: str | None, last: int) -> None:
    """Show upgrade run history."""
    entries = read_history(project=project, last=last)
    if not entries:
        console.print("[yellow]No history found.[/yellow]")
        return

    table = Table(title="Run History")
    table.add_column("Timestamp")
    table.add_column("Project")
    table.add_column("Pipeline")
    table.add_column("Success")
    table.add_column("Duration")

    for e in entries:
        success_str = "[green]✓[/green]" if e["success"] else "[red]✗[/red]"
        table.add_row(
            e["timestamp"],
            e["project"],
            e["pipeline"],
            success_str,
            f"{e['duration_seconds']}s",
        )

    console.print(table)


@cli.command()
@click.argument("project")
def status(project):
    """Show current status of a project's remote server."""
    config = _load_project_config(project)
    ssh = SSHRunner(
        host=config.ssh_host,
        user=config.ssh_user,
        key_path=config.ssh_key,
        sudo=config.sudo,
        port=config.ssh_port,
    )

    console.print(f"[bold]{config.name}[/bold] ({config.ssh_host})")
    console.print()

    # Uptime
    r = ssh.run("uptime -p")
    if r.ok:
        console.print(f"  Uptime: {r.stdout.strip()}")

    # Reboot required?
    r = ssh.run("cat /var/run/reboot-required 2>/dev/null || echo 'No reboot required'")
    if r.ok:
        msg = r.stdout.strip()
        if "restart required" in msg.lower():
            console.print(f"  Reboot: [yellow]{msg}[/yellow]")
        else:
            console.print(f"  Reboot: {msg}")

    # Disk
    r = ssh.run(f"df -h {shlex.quote(str(config.project_dir))} | tail -1")
    if r.ok:
        console.print(f"  Disk: {r.stdout.strip()}")

    # Git
    r = ssh.run(f"cd {shlex.quote(str(config.project_dir))} && git log --oneline -1")
    if r.ok:
        console.print(f"  Git: {r.stdout.strip()}")

    # Containers
    console.print()
    from biblio_uplift.core.steps.docker import _compose_cmd

    r = ssh.run(f"{_compose_cmd(config)} ps --format 'table {{{{.Name}}}}\t{{{{.Status}}}}\t{{{{.Image}}}}'")
    if r.ok and r.stdout.strip():
        console.print("  Containers:")
        for line in r.stdout.strip().splitlines():
            console.print(f"    {line}")
    else:
        console.print("  Containers: [yellow]none running[/yellow]")

    # Backup info
    r = ssh.run(f"ls -1t {shlex.quote(str(config.backup_dir))}/*.tar.gz 2>/dev/null | head -5")
    if r.ok and r.stdout.strip():
        console.print()
        console.print("  Recent backups:")
        for line in r.stdout.strip().splitlines():
            console.print(f"    {Path(line.strip()).name}")
    else:
        console.print("  Backups: [yellow]none found[/yellow]")


@cli.group()
def backup():
    """Manage project backups."""
    pass


@backup.command("list")
@click.argument("project")
def backup_list(project):
    """List available backups for a project."""
    config = _load_project_config(project)
    ssh = SSHRunner(
        host=config.ssh_host,
        user=config.ssh_user,
        key_path=config.ssh_key,
        sudo=config.sudo,
        port=config.ssh_port,
    )

    result = ssh.run(f"ls -lhS {shlex.quote(str(config.backup_dir))}/*.tar.gz 2>/dev/null")
    if not result.ok or not result.stdout.strip():
        console.print("No backups found.")
        return

    table = Table(title=f"Backups: {config.name}")
    table.add_column("File")
    table.add_column("Size")
    table.add_column("Date")

    for line in result.stdout.strip().splitlines():
        parts = line.split()
        if len(parts) >= 9:
            size = parts[4]
            date = " ".join(parts[5:8])
            name = Path(parts[-1]).name
            table.add_row(name, size, date)

    console.print(table)
