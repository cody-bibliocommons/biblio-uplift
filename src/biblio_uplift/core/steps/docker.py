from __future__ import annotations

import shlex

from biblio_uplift.config.schema import ProjectConfig
from biblio_uplift.core.pipeline import PipelineContext, PipelineStep, StepResult, StepStatus


def _compose_cmd(config: ProjectConfig) -> str:
    cmd = f"cd {shlex.quote(str(config.project_dir))} && {config.compose_command}"
    for f in config.compose_files:
        cmd += f" -f {shlex.quote(f)}"
    if config.compose_profile == "hostname":
        cmd += " --profile $(hostname -s)"
    elif config.compose_profile:
        cmd += f" --profile {shlex.quote(config.compose_profile)}"
    return cmd


class DockerDownStep(PipelineStep):
    name = "docker_down"
    description = "Stop containers with docker compose down"

    def execute(self, ctx: PipelineContext) -> StepResult:
        cmd = f"{_compose_cmd(ctx.config)} down"
        if ctx.on_output:
            ctx.on_output(f"$ {cmd}")
        result = ctx.ssh.run(cmd, timeout=120, on_output=ctx.on_output)
        if result.ok:
            return StepResult(status=StepStatus.SUCCESS, message="Containers stopped")
        return StepResult(status=StepStatus.FAILED, error=result.stderr)

    def rollback(self, ctx: PipelineContext) -> None:
        out = ctx.on_output or (lambda x: None)
        out("Rollback: bringing services back up...")
        cmd = _compose_cmd(ctx.config) + " up -d"
        ctx.ssh.run(cmd, timeout=120, on_output=out)


class DockerPullStep(PipelineStep):
    name = "docker_pull"
    description = "Pull latest container images"

    def execute(self, ctx: PipelineContext) -> StepResult:
        cmd = f"{_compose_cmd(ctx.config)} pull"
        if ctx.on_output:
            ctx.on_output(f"$ {cmd}")
        result = ctx.ssh.run(cmd, timeout=600, on_output=ctx.on_output)
        if result.ok:
            return StepResult(status=StepStatus.SUCCESS, message="Images pulled")
        return StepResult(status=StepStatus.FAILED, error=result.stderr)


class DockerUpStep(PipelineStep):
    name = "docker_up"
    description = "Start containers with docker compose up -d"

    def execute(self, ctx: PipelineContext) -> StepResult:
        cmd = f"{_compose_cmd(ctx.config)} up -d"
        if ctx.on_output:
            ctx.on_output(f"$ {cmd}")
        result = ctx.ssh.run(cmd, timeout=120, on_output=ctx.on_output)
        if result.ok:
            return StepResult(status=StepStatus.SUCCESS, message="Containers started")
        return StepResult(status=StepStatus.FAILED, error=result.stderr)
