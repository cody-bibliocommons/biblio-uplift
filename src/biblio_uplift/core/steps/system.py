from __future__ import annotations

from biblio_uplift.core.pipeline import PipelineContext, PipelineStep, StepResult, StepStatus
from biblio_uplift.core.state import save_resume_state

PACKAGE_MANAGER_COMMANDS: dict[str, list[tuple[str, int]]] = {
    "apt": [
        ("apt-get update", 120),
        ("DEBIAN_FRONTEND=noninteractive apt-get upgrade -y", 600),
        ("apt-get autoremove --purge -y", 120),
    ],
    "dnf": [
        ("dnf upgrade -y", 600),
        ("dnf autoremove -y", 120),
    ],
    "yum": [
        ("yum update -y", 600),
        ("package-cleanup --oldkernels -y", 120),
    ],
    "apk": [
        ("apk update", 120),
        ("apk upgrade", 600),
    ],
}


class OsUpdateStep(PipelineStep):
    name = "os_update"
    description = "Update OS packages"
    skippable = True

    def execute(self, ctx: PipelineContext) -> StepResult:
        commands = PACKAGE_MANAGER_COMMANDS[ctx.config.package_manager]
        for cmd, timeout in commands:
            result = ctx.ssh.run(cmd, timeout=timeout, on_output=ctx.on_output)
            if not result.ok:
                return StepResult(
                    status=StepStatus.FAILED,
                    error=result.stderr,
                    message=f"Command failed: {cmd}",
                )
        return StepResult(status=StepStatus.SUCCESS, message="OS packages updated")

    def rollback(self, ctx: PipelineContext) -> None:
        out = ctx.on_output or (lambda x: None)
        out("Warning: OS updates cannot be automatically rolled back.")


class RebootStep(PipelineStep):
    name = "reboot"
    description = "Reboot server and wait for it to come back"
    skippable = True

    def execute(self, ctx: PipelineContext) -> StepResult:
        # Save state before reboot so the pipeline can be resumed
        out = ctx.on_output or (lambda x: None)
        completed = ctx.state.get("_completed_steps", [])
        save_resume_state(
            project=ctx.config.name,
            completed_steps=completed,
            skip_steps=ctx.skip_steps,
            state={k: v for k, v in ctx.state.items() if not k.startswith("_")},
        )
        out("Saved resume state for post-reboot recovery.")

        # reboot will disconnect/return non-zero, that's expected
        ctx.ssh.run("reboot", timeout=10, on_output=ctx.on_output)

        if ctx.on_output:
            ctx.on_output("Waiting for server to come back...")

        came_back = ctx.ssh.wait_for_reboot(timeout=ctx.config.reboot_timeout)
        out = ctx.on_output or (lambda x: None)

        if came_back:
            # Verify we reconnected to the right host
            actual_host = "unknown"
            verify = ctx.ssh.run("hostname -f")
            if verify.ok:
                actual_host = verify.stdout.strip()
                out(f"Reconnected to: {actual_host}")
            # Verify docker is responsive
            docker_check = ctx.ssh.run("docker info --format '{{.ServerVersion}}'")
            if docker_check.ok:
                out(f"Docker version: {docker_check.stdout.strip()}")
            else:
                out(f"Warning: Docker not responsive after reboot: {docker_check.stderr}")
            return StepResult(status=StepStatus.SUCCESS, message=f"Rebooted, reconnected to {actual_host}")

        return StepResult(
            status=StepStatus.FAILED,
            error="Server did not come back within 300s",
            message="Reboot timeout",
        )
