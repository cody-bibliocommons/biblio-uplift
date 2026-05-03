from __future__ import annotations

import re
import shlex

from biblio_uplift.core.pipeline import PipelineContext, PipelineStep, StepResult, StepStatus


class PreflightStep(PipelineStep):
    name = "preflight"
    description = "Check SSH connectivity and disk space"
    skippable = False

    def execute(self, ctx: PipelineContext) -> StepResult:
        log = ctx.on_output or (lambda _: None)
        config = ctx.config

        # Check maintenance window
        if config.maintenance_window:
            try:
                start_str, end_str = config.maintenance_window.split("-")
                from datetime import datetime, time

                now = datetime.now().time()
                start = time.fromisoformat(start_str.strip())
                end = time.fromisoformat(end_str.strip())
                if start <= end:
                    in_window = start <= now <= end
                else:  # crosses midnight, e.g. 22:00-06:00
                    in_window = now >= start or now <= end
                if not in_window:
                    msg = (
                        f"Outside maintenance window ({config.maintenance_window}). "
                        f"Current time: {now.strftime('%H:%M')}"
                    )
                    log(msg)
                    return StepResult(
                        status=StepStatus.FAILED,
                        error=f"Outside maintenance window {config.maintenance_window}",
                    )
                log(f"Within maintenance window ({config.maintenance_window})")
            except ValueError as e:
                log(f"Warning: Invalid maintenance_window format: {e}")

        # 1. Test SSH connection
        log("Testing SSH connectivity...")
        result = ctx.ssh.test_connection()
        if not result.ok:
            return StepResult(
                status=StepStatus.FAILED,
                error=f"SSH connection failed: {result.stderr}",
            )
        log("SSH connection OK")

        # 2. Check disk space on backup_dir partition
        backup_dir = str(ctx.config.backup_dir)
        log(f"Checking disk space on {backup_dir}...")
        df_result = ctx.ssh.run(f"df -BM {shlex.quote(backup_dir)}", on_output=None)
        disk_avail_mb = 0
        available_mb = 0
        if df_result.ok:
            # Parse second line: Filesystem 1M-blocks Used Available Use% Mounted
            lines = df_result.stdout.strip().splitlines()
            if len(lines) >= 2:
                match = re.search(r"(\d+)M", lines[1].split()[3])
                if match:
                    disk_avail_mb = int(match.group(1))
            available_mb = disk_avail_mb
            ctx.state["disk_avail_mb"] = disk_avail_mb
            if disk_avail_mb < 2048:
                log(f"WARNING: Only {disk_avail_mb}MB free on {backup_dir} (< 2GB)")
            else:
                log(f"Disk space OK: {disk_avail_mb}MB available")
        else:
            log(f"WARNING: Could not check disk space: {df_result.stderr}")

        # Estimate backup size
        config = ctx.config
        out = log
        out("Estimating backup size...")
        total_estimate_mb = 0

        # Project dir size
        result = ctx.ssh.run(f"du -sm {shlex.quote(str(config.project_dir))} | cut -f1")
        if result.ok:
            try:
                dir_mb = int(result.stdout.strip())
                total_estimate_mb += dir_mb
                out(f"  Project dir: ~{dir_mb}MB")
            except ValueError:
                pass

        # Volume sizes
        for vol in config.volumes:
            result = ctx.ssh.run(f"docker run --rm -v {shlex.quote(vol)}:/volume alpine du -sm /volume | cut -f1")
            if result.ok:
                try:
                    vol_mb = int(result.stdout.strip())
                    total_estimate_mb += vol_mb
                    out(f"  Volume {vol}: ~{vol_mb}MB")
                except ValueError:
                    pass

        if total_estimate_mb > 0:
            out(f"  Estimated backup size: ~{total_estimate_mb}MB")
            ctx.state["estimated_backup_mb"] = total_estimate_mb
            if available_mb > 0 and total_estimate_mb * 1.5 > available_mb:
                return StepResult(
                    status=StepStatus.FAILED,
                    error=f"Insufficient disk space: need ~{int(total_estimate_mb * 1.5)}MB, have {available_mb}MB",
                )

        # 3. Verify docker is accessible
        log("Checking Docker...")
        docker_result = ctx.ssh.run("docker info --format '{{.ServerVersion}}'")
        if not docker_result.ok:
            return StepResult(
                status=StepStatus.FAILED,
                error=f"Docker check failed: {docker_result.stderr}",
            )
        docker_version = docker_result.stdout.strip()
        ctx.state["docker_version"] = docker_version
        log(f"Docker OK: {docker_version}")

        return StepResult(
            status=StepStatus.SUCCESS,
            message="All preflight checks passed",
            details={
                "docker_version": docker_version,
                "disk_avail_mb": disk_avail_mb,
            },
        )
