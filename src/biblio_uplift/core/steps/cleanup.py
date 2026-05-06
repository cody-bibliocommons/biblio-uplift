from __future__ import annotations

import logging
import shlex

from biblio_uplift.core.pipeline import PipelineContext, PipelineStep, StepResult, StepStatus

logger = logging.getLogger(__name__)


def _show_system_disk(ctx: PipelineContext, label: str) -> None:
    out = ctx.on_output or (lambda x: None)
    config = ctx.config
    out(f"{label}:")
    r = ctx.ssh.run(
        f"df -h {shlex.quote(str(config.project_dir))} --output=size,used,avail,pcent | tail -1",
        sudo=False,
    )
    if r.ok:
        parts = r.stdout.strip().split()
        if len(parts) >= 4:
            out(f"  {parts[2]} free of {parts[0]} ({parts[3]} used)")


class DockerCleanupStep(PipelineStep):
    name = "docker_cleanup"
    description = "Prune stale Docker resources"
    supports_dry_run = True

    def execute(self, ctx: PipelineContext) -> StepResult:
        if ctx.dry_run:
            return self._dry_run(ctx)

        out = ctx.on_output or (lambda x: None)
        cleanup = ctx.config.cleanup

        # Verify Docker daemon is reachable
        docker_check = ctx.ssh.run("docker info", timeout=10)
        if not docker_check.ok:
            return StepResult(
                status=StepStatus.FAILED,
                error="Docker daemon is not running or not reachable",
            )

        # System disk before
        _show_system_disk(ctx, "System disk before cleanup")
        out("")

        # Docker disk before
        out("Docker disk usage before cleanup:")
        before = ctx.ssh.run("docker system df", timeout=30)
        if before.ok:
            for line in before.stdout.strip().splitlines():
                out(f"  {line}")
        out("")

        prune_commands = []
        if cleanup.prune_containers:
            prune_commands.append(("docker container prune -f", "Containers pruned"))
        if cleanup.prune_images:
            # Failsafe: only prune images if containers are running
            from biblio_uplift.core.steps.docker import _bash_compose

            check_cmd = _bash_compose(ctx.config, "ps -q")
            running = ctx.ssh.run(check_cmd)
            if running.ok and running.stdout.strip():
                if cleanup.aggressive_prune:
                    prune_commands.append(("docker image prune -af", "All unused images pruned"))
                else:
                    prune_commands.append(("docker image prune -f", "Dangling images pruned"))
            else:
                if ctx.on_output:
                    ctx.on_output("[yellow]Skipping image prune: containers not running (failsafe)[/yellow]")
        if cleanup.prune_volumes:
            if cleanup.aggressive_prune:
                prune_commands.append(("docker volume prune -f", "All anonymous/orphaned volumes pruned"))
            else:
                prune_commands.append(("docker volume prune -f --filter 'label!=keep'", "Volumes pruned (label!=keep)"))
        if cleanup.prune_build_cache:
            prune_commands.append(("docker builder prune -af", "Build cache pruned"))

        for cmd, label in prune_commands:
            result = ctx.ssh.run(cmd, timeout=300)
            if not result.ok:
                return StepResult(status=StepStatus.FAILED, error=result.stderr, message=f"Failed: {cmd}")
            out(f"  {label}: {result.stdout.strip()}")

        # Docker disk after
        out("")
        out("Docker disk usage after cleanup:")
        after = ctx.ssh.run("docker system df", timeout=30)
        if after.ok:
            for line in after.stdout.strip().splitlines():
                out(f"  {line}")

        # System disk after
        out("")
        _show_system_disk(ctx, "System disk after cleanup")

        return StepResult(status=StepStatus.SUCCESS, message="Docker cleanup complete")

    def _dry_run(self, ctx: PipelineContext) -> StepResult:
        out = ctx.on_output or (lambda x: None)
        config = ctx.config
        out("[DRY RUN] Docker cleanup preview:")

        _show_system_disk(ctx, "System disk")
        out("")

        if config.cleanup.prune_containers:
            r = ctx.ssh.run('docker ps -a --filter status=exited --filter status=dead --format "{{.Names}}" | wc -l')
            if r.ok:
                out(f"  Stopped containers to remove: {r.stdout.strip()}")

        if config.cleanup.prune_images:
            from biblio_uplift.core.steps.docker import _bash_compose

            check_cmd = _bash_compose(config, "ps -q")
            running = ctx.ssh.run(check_cmd)
            if running.ok and running.stdout.strip():
                r = ctx.ssh.run('docker images --filter dangling=true --format "{{.Repository}}:{{.Tag}}" | wc -l')
                if r.ok:
                    out(f"  Dangling images to remove: {r.stdout.strip()}")
                r = ctx.ssh.run('docker system df --format "{{.Type}}\t{{.Reclaimable}}"')
                if r.ok:
                    out("  Reclaimable space:")
                    for line in r.stdout.strip().splitlines():
                        out(f"    {line}")
            else:
                out("  [yellow]Image prune would be skipped: containers not running[/yellow]")

        if config.cleanup.prune_volumes:
            r = ctx.ssh.run("docker volume ls --filter dangling=true --format '{{.Name}}' | wc -l")
            if r.ok:
                out(f"  Dangling volumes to remove: {r.stdout.strip()}")

        if config.cleanup.prune_build_cache:
            r = ctx.ssh.run("docker builder du --format '{{.Size}}' 2>/dev/null | tail -1")
            if r.ok and r.stdout.strip():
                out(f"  Build cache to clear: {r.stdout.strip()}")

        r = ctx.ssh.run("docker system df")
        if r.ok:
            out("")
            out("  Current Docker disk usage:")
            for line in r.stdout.strip().splitlines():
                out(f"    {line}")

        return StepResult(status=StepStatus.SUCCESS, message="Dry run preview complete")


class LogCleanupStep(PipelineStep):
    name = "log_cleanup"
    description = "Clean up old log files"
    supports_dry_run = True

    def execute(self, ctx: PipelineContext) -> StepResult:
        config = ctx.config
        out = ctx.on_output or (lambda x: None)
        days = config.cleanup.log_retention_days

        if ctx.dry_run:
            return self._dry_run(ctx)

        out(f"Cleaning files older than {days} days...")

        # 1. Clean old rotated logs in /var/log
        out("Cleaning old rotated logs...")
        r = ctx.ssh.run(f"find /var/log -xdev -name '*.gz' -mtime +{days} -delete -print 2>/dev/null | wc -l")
        if r.ok:
            out(f"  Removed {r.stdout.strip()} rotated log files")

        r = ctx.ssh.run(f"find /var/log -xdev -name '*.old' -mtime +{days} -delete -print 2>/dev/null | wc -l")
        if r.ok:
            out(f"  Removed {r.stdout.strip()} old log files")

        r = ctx.ssh.run(f"find /var/log -xdev -name '*.1' -mtime +{days} -delete -print 2>/dev/null | wc -l")
        if r.ok:
            out(f"  Removed {r.stdout.strip()} numbered log files")

        # 2. Truncate specific configured log paths (only if they exist)
        for path in config.cleanup.log_paths:
            r = ctx.ssh.run(f"test -f {shlex.quote(path)} && truncate -s 0 {shlex.quote(path)}")
            if r.ok:
                out(f"  Truncated: {path}")

        # 3. Vacuum journald
        out(f"Vacuuming journal to {days} days...")
        r = ctx.ssh.run(f"journalctl --vacuum-time={days}d 2>&1")
        if r.ok:
            for line in r.stdout.strip().splitlines():
                if "freed" in line.lower() or "vacuuming" in line.lower() or "archived" in line.lower():
                    out(f"  {line.strip()}")

        # 4. Clean apt cache
        out("Cleaning apt cache...")
        r = ctx.ssh.run("apt-get clean 2>/dev/null")
        if r.ok:
            out("  Apt cache cleaned")

        # 5. Clean old tmp files
        out(f"Cleaning tmp files older than {days} days...")
        r = ctx.ssh.run(f"find /tmp -type f -mtime +{days} -delete -print 2>/dev/null | wc -l")
        if r.ok:
            count = r.stdout.strip()
            if count != "0":
                out(f"  Removed {count} tmp files")

        # Run custom cleanup commands
        if config.cleanup.cleanup_commands:
            out("Running custom cleanup commands...")
            for cmd in config.cleanup.cleanup_commands:
                logger.info("Cleanup command: %s", cmd)
                r = ctx.ssh.run(cmd, timeout=60)
                if r.ok:
                    # Show only non-empty output
                    if r.stdout.strip():
                        out(f"  {r.stdout.strip()}")
                else:
                    out(f"  Warning: {cmd} failed: {r.stderr}")

        return StepResult(status=StepStatus.SUCCESS, message="Log cleanup complete")

    def _dry_run(self, ctx: PipelineContext) -> StepResult:
        config = ctx.config
        out = ctx.on_output or (lambda x: None)
        days = config.cleanup.log_retention_days

        out(f"[DRY RUN] Log cleanup preview (files older than {days} days):")

        # Rotated logs
        r = ctx.ssh.run(f"find /var/log -xdev -name '*.gz' -mtime +{days} 2>/dev/null | wc -l")
        if r.ok:
            out(f"  Rotated .gz logs to remove: {r.stdout.strip()}")

        r = ctx.ssh.run(f"find /var/log -xdev \\( -name '*.old' -o -name '*.1' \\) -mtime +{days} 2>/dev/null | wc -l")
        if r.ok:
            out(f"  Old/numbered logs to remove: {r.stdout.strip()}")

        # Configured log paths
        for path in config.cleanup.log_paths:
            r = ctx.ssh.run(f"test -f {shlex.quote(path)} && du -sh {shlex.quote(path)} 2>/dev/null")
            if r.ok:
                out(f"  Would truncate: {r.stdout.strip()}")

        # Journal
        r = ctx.ssh.run("journalctl --disk-usage 2>/dev/null")
        if r.ok:
            out(f"  {r.stdout.strip()}")
            out(f"  Would vacuum to {days} days")

        # Apt cache
        r = ctx.ssh.run("du -sh /var/cache/apt/archives/ 2>/dev/null")
        if r.ok:
            out(f"  Apt cache: {r.stdout.strip()}")

        # Tmp files
        r = ctx.ssh.run(f"find /tmp -type f -mtime +{days} 2>/dev/null | wc -l")
        if r.ok:
            out(f"  Tmp files older than {days}d: {r.stdout.strip()}")

        if config.cleanup.cleanup_commands:
            out(f"  Custom cleanup commands: {len(config.cleanup.cleanup_commands)}")
            for cmd in config.cleanup.cleanup_commands:
                out(f"    $ {cmd}")

        return StepResult(status=StepStatus.SUCCESS, message="Dry run preview complete")
