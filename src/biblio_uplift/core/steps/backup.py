from __future__ import annotations

import shlex
from datetime import datetime, timezone

from biblio_uplift.core.pipeline import PipelineContext, PipelineStep, StepResult, StepStatus


class BackupFilesStep(PipelineStep):
    name = "backup_files"
    description = "Back up project files and extra paths"

    def execute(self, ctx: PipelineContext) -> StepResult:
        cfg = ctx.config
        backup_dir = str(cfg.backup_dir)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        ctx.state["backup_timestamp"] = timestamp

        archive = f"{backup_dir}/{cfg.name}_files_{timestamp}.tar.gz"

        ctx.on_output and ctx.on_output(f"Creating backup directory {backup_dir}")
        result = ctx.ssh.run(f"mkdir -p {shlex.quote(backup_dir)}", on_output=ctx.on_output)
        if not result.ok:
            return StepResult(status=StepStatus.FAILED, error=f"Failed to create backup dir: {result.stderr}")

        chmod_result = ctx.ssh.run(f"chmod 700 {shlex.quote(backup_dir)}")
        if not chmod_result.ok:
            return StepResult(
                status=StepStatus.FAILED,
                error=f"Failed to set backup directory permissions: {chmod_result.stderr}",
            )

        paths = [str(cfg.project_dir).lstrip("/")]
        for p in cfg.extra_backup_paths:
            paths.append(p.lstrip("/"))

        tar_cmd = f"tar czf {shlex.quote(archive)} -C / {' '.join(shlex.quote(p) for p in paths)}"
        ctx.on_output and ctx.on_output(f"Archiving files: {tar_cmd}")
        result = ctx.ssh.run(tar_cmd, timeout=600, on_output=ctx.on_output)
        if not result.ok:
            return StepResult(status=StepStatus.FAILED, error=f"tar failed: {result.stderr}")

        ctx.state["file_backup_path"] = archive
        return StepResult(status=StepStatus.SUCCESS, message=f"File backup saved to {archive}")


class BackupVolumesStep(PipelineStep):
    name = "backup_volumes"
    description = "Back up Docker volumes"

    def execute(self, ctx: PipelineContext) -> StepResult:
        cfg = ctx.config
        if not cfg.volumes:
            return StepResult(status=StepStatus.SUCCESS, message="No volumes to back up")

        backup_dir = str(cfg.backup_dir)
        timestamp = ctx.state.get("backup_timestamp", datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"))

        ctx.on_output and ctx.on_output("Pulling alpine:latest")
        result = ctx.ssh.run("docker pull alpine:latest", on_output=ctx.on_output)
        if not result.ok:
            return StepResult(status=StepStatus.FAILED, error=f"Failed to pull alpine: {result.stderr}")

        backup_paths: list[str] = []
        for vol in cfg.volumes:
            safe_vol = vol.replace("/", "_").replace(" ", "_")
            archive = f"{safe_vol}_{timestamp}.tar.gz"
            cmd = (
                f"docker run --rm -v {shlex.quote(vol)}:/volume"
                f" -v {shlex.quote(backup_dir)}:/backup"
                f" alpine tar czf {shlex.quote(f'/backup/{archive}')} -C /volume ."
            )
            ctx.on_output and ctx.on_output(f"Backing up volume {vol}")
            result = ctx.ssh.run(cmd, timeout=600, on_output=ctx.on_output)
            if not result.ok:
                return StepResult(status=StepStatus.FAILED, error=f"Volume backup failed for {vol}: {result.stderr}")
            backup_paths.append(f"{backup_dir}/{archive}")

        ctx.state["volume_backup_paths"] = backup_paths
        return StepResult(status=StepStatus.SUCCESS, message=f"Backed up {len(backup_paths)} volume(s)")


class BackupCleanupStep(PipelineStep):
    name = "backup_cleanup"
    description = "Remove old backups beyond retention count"

    def execute(self, ctx: PipelineContext) -> StepResult:
        cfg = ctx.config
        backup_dir = str(cfg.backup_dir)
        retention = cfg.backup_retention

        patterns = [f"{cfg.name}_files_*.tar.gz"]
        for vol in cfg.volumes:
            safe_vol = vol.replace("/", "_").replace(" ", "_")
            patterns.append(f"{safe_vol}_*.tar.gz")

        removed = 0
        for pattern in patterns:
            # List matching files sorted by name
            result = ctx.ssh.run(
                f"find {shlex.quote(backup_dir)} -maxdepth 1 -name {shlex.quote(pattern)} -type f | sort"
            )
            if not result.ok or not result.stdout.strip():
                continue

            files = [f for f in result.stdout.strip().splitlines() if f]
            if len(files) <= retention:
                continue

            to_remove = files[: len(files) - retention]
            for f in to_remove:
                # Safety: only remove files within backup_dir
                if not f.startswith(backup_dir + "/"):
                    continue
                ctx.on_output and ctx.on_output(f"Removing old backup: {f}")
                ctx.ssh.run(f"rm -f {shlex.quote(f)}", on_output=ctx.on_output)
                removed += 1

        return StepResult(status=StepStatus.SUCCESS, message=f"Cleanup complete, removed {removed} old backup(s)")
