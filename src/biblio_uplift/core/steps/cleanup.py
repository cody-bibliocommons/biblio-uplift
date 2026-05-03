from __future__ import annotations

import shlex

from biblio_uplift.core.pipeline import PipelineContext, PipelineStep, StepResult, StepStatus


class DockerCleanupStep(PipelineStep):
    name = "docker_cleanup"
    description = "Prune stale Docker resources"

    def execute(self, ctx: PipelineContext) -> StepResult:
        cleanup = ctx.config.cleanup

        # Snapshot disk usage before
        if ctx.on_output:
            ctx.on_output("Docker disk usage before cleanup:")
        ctx.ssh.run("docker system df", timeout=30, on_output=ctx.on_output)

        prune_commands = []
        if cleanup.prune_containers:
            prune_commands.append("docker container prune -f")
        if cleanup.prune_images:
            prune_commands.append("docker image prune -f")
        if cleanup.prune_volumes:
            prune_commands.append("docker volume prune -f --filter 'label!=keep'")
        if cleanup.prune_build_cache:
            prune_commands.append("docker builder prune -af")

        for cmd in prune_commands:
            if ctx.on_output:
                ctx.on_output(f"$ {cmd}")
            result = ctx.ssh.run(cmd, timeout=300, on_output=ctx.on_output)
            if not result.ok:
                return StepResult(status=StepStatus.FAILED, error=result.stderr, message=f"Failed: {cmd}")

        # Snapshot disk usage after
        if ctx.on_output:
            ctx.on_output("Docker disk usage after cleanup:")
        ctx.ssh.run("docker system df", timeout=30, on_output=ctx.on_output)

        return StepResult(status=StepStatus.SUCCESS, message="Docker cleanup complete")


class LogCleanupStep(PipelineStep):
    name = "log_cleanup"
    description = "Clean up old log files"

    def execute(self, ctx: PipelineContext) -> StepResult:
        cleanup = ctx.config.cleanup
        cleaned = []

        for path in cleanup.log_paths:
            cmd = f"truncate -s 0 {shlex.quote(path)}"
            if ctx.on_output:
                ctx.on_output(f"$ {cmd}")
            result = ctx.ssh.run(cmd, timeout=30, on_output=ctx.on_output)
            if result.ok:
                cleaned.append(path)
            else:
                if ctx.on_output:
                    ctx.on_output(f"Warning: failed to truncate {path}: {result.stderr}")

        # Clean journal logs
        days = cleanup.log_retention_days
        cmd = f"journalctl --vacuum-time={shlex.quote(str(days))}d"
        if ctx.on_output:
            ctx.on_output(f"$ {cmd}")
        result = ctx.ssh.run(cmd, timeout=60, on_output=ctx.on_output)
        if not result.ok:
            return StepResult(status=StepStatus.FAILED, error=result.stderr, message="Journal cleanup failed")

        msg = f"Truncated {len(cleaned)} log files, vacuumed journal to {days}d"
        return StepResult(status=StepStatus.SUCCESS, message=msg)
