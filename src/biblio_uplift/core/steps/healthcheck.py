from __future__ import annotations

import shlex
import time

from biblio_uplift.core.pipeline import PipelineContext, PipelineStep, StepResult, StepStatus


class HealthCheckStep(PipelineStep):
    name = "healthcheck"
    description = "Verify services are healthy"
    skippable = True

    def execute(self, ctx: PipelineContext) -> StepResult:
        config = ctx.config
        out = ctx.on_output or (lambda x: None)
        errors: list[str] = []

        # 1. Check container health via docker ps
        out("Checking container health...")
        deadline = time.monotonic() + config.healthcheck_timeout
        first_check = True
        while time.monotonic() < deadline:
            result = ctx.ssh.run(
                'docker ps --format "{{.Names}}\t{{.Status}}"',
                on_output=None,
            )
            if result.ok:
                lines = [line for line in result.stdout.strip().splitlines() if line]
                if not lines:
                    out("  No containers running.")
                    break
                all_healthy = True
                starting_count = 0
                unhealthy_count = 0
                for line in lines:
                    parts = line.split("\t", 1)
                    name = parts[0]
                    status = parts[1] if len(parts) > 1 else ""
                    if "(healthy)" in status:
                        if first_check:
                            out(f"  ✓ {name}: healthy")
                    elif "(health: starting)" in status or "starting" in status.lower():
                        all_healthy = False
                        starting_count += 1
                    elif "(unhealthy)" in status:
                        all_healthy = False
                        unhealthy_count += 1
                    else:
                        if first_check:
                            out(f"  ? {name}: {status}")
                if all_healthy:
                    if not first_check:
                        # Log final healthy state
                        for line in lines:
                            parts = line.split("\t", 1)
                            out(f"  ✓ {parts[0]}: healthy")
                    break
                if not first_check:
                    out(f"  Waiting... ({starting_count} starting, {unhealthy_count} unhealthy)")
                first_check = False
            time.sleep(10)
        else:
            # Timeout reached
            result = ctx.ssh.run(
                'docker ps --format "{{.Names}}\t{{.Status}}"',
                on_output=None,
            )
            if result.ok:
                for line in result.stdout.strip().splitlines():
                    if not line:
                        continue
                    parts = line.split("\t", 1)
                    status = parts[1] if len(parts) > 1 else ""
                    if "(unhealthy)" in status:
                        errors.append(f"{parts[0]} is unhealthy")
                    elif "(health: starting)" in status or "starting" in status.lower():
                        errors.append(f"{parts[0]} still starting after {config.healthcheck_timeout}s")
            else:
                errors.append(f"Could not check container health: {result.stderr}")

        # 2. Check HTTP endpoints
        for url in config.healthcheck_urls:
            out(f"Checking {url}...")
            result = ctx.ssh.run(
                f'curl -sSf -o /dev/null -w "%{{http_code}}" --max-time 10 -k {shlex.quote(url)}',
                timeout=15,
            )
            if result.ok:
                out(f"  ✓ {url}: HTTP {result.stdout.strip()}")
            else:
                errors.append(f"{url}: {result.stderr}")
                out(f"  ✗ {url}: {result.stderr}")

        if errors:
            return StepResult(
                status=StepStatus.FAILED,
                error="; ".join(errors),
            )

        return StepResult(
            status=StepStatus.SUCCESS,
            message="All health checks passed",
        )
