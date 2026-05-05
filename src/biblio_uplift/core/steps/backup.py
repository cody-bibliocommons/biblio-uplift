from __future__ import annotations

import re
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

        excludes = ""
        for pattern in cfg.backup_exclude_patterns:
            excludes += f" --exclude={shlex.quote(pattern)}"

        tar_cmd = f"tar czf {shlex.quote(archive)}{excludes} -C / {' '.join(shlex.quote(p) for p in paths)}"
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
            # Verify volume exists before backing up
            check = ctx.ssh.run(f"docker volume inspect {shlex.quote(vol)}", timeout=30)
            if not check.ok:
                return StepResult(
                    status=StepStatus.FAILED,
                    error=f"Volume does not exist: {vol}",
                )
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
    skippable = True

    def execute(self, ctx: PipelineContext) -> StepResult:
        config = ctx.config
        out = ctx.on_output or (lambda x: None)
        backup_dir = str(config.backup_dir)
        retention = config.backup_retention

        out(f"Checking backups in {backup_dir} (retention: {retention})...")

        # List all tar.gz files
        inner = f"ls -1 {shlex.quote(backup_dir)}/*.tar.gz 2>/dev/null"
        result = ctx.ssh.run(f"bash -c {shlex.quote(inner)}")
        if not result.ok or not result.stdout.strip():
            out("No backups found.")
            return StepResult(status=StepStatus.SUCCESS, message="No backups to clean")

        files = [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]

        # Extract timestamps and group files by timestamp
        ts_pattern = re.compile(r'_(\d{8}_\d{6})\.tar\.gz$')
        groups: dict[str, list[str]] = {}
        for f in files:
            match = ts_pattern.search(f)
            if match:
                ts = match.group(1)
                groups.setdefault(ts, []).append(f)

        # Sort timestamps newest first
        sorted_ts = sorted(groups.keys(), reverse=True)
        out(f"Found {len(sorted_ts)} backup sets ({len(files)} files)")

        if len(sorted_ts) <= retention:
            out(f"Nothing to prune ({len(sorted_ts)} sets <= {retention})")
            return StepResult(status=StepStatus.SUCCESS, message="Within retention")

        # Remove old sets
        to_remove_ts = sorted_ts[retention:]
        remove_count = 0
        for ts in to_remove_ts:
            for f in groups[ts]:
                if not f.startswith(backup_dir + "/"):
                    continue  # safety check
                ctx.ssh.run(f"rm -f {shlex.quote(f)}")
                remove_count += 1

        out(f"Removed {len(to_remove_ts)} old backup sets ({remove_count} files)")
        return StepResult(status=StepStatus.SUCCESS, message=f"Removed {len(to_remove_ts)} sets")
