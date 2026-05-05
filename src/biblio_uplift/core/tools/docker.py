from __future__ import annotations

import shlex
from collections.abc import Callable
from typing import TYPE_CHECKING

from biblio_uplift.core.steps.docker import _compose_cmd
from biblio_uplift.core.tools import Tool, ToolResult

if TYPE_CHECKING:
    from biblio_uplift.config.schema import ProjectConfig
    from biblio_uplift.core.ssh import SSHRunner


class ContainerLogsTool(Tool):
    name = "container-logs"
    category = "docker"
    description = "Show recent logs for all running containers"

    def dry_run(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        return self.execute(ssh, config, out)

    def execute(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        names_result = ssh.run("docker ps --format '{{.Names}}'", timeout=15)
        if not names_result.ok:
            return ToolResult(success=False, error=names_result.stderr)

        containers = [n.strip() for n in names_result.stdout.strip().splitlines() if n.strip()]
        if not containers:
            out("No running containers.")
            return ToolResult(success=True, output="No running containers.")

        output_parts = []
        for name in containers:
            out(f"--- {name} ---")
            r = ssh.run(f"docker logs --tail 50 {shlex.quote(name)} 2>&1", timeout=30)
            out(r.stdout)
            output_parts.append(f"--- {name} ---\n{r.stdout}")

        output = "\n".join(output_parts)
        return ToolResult(success=True, output=output)


class ComposePullCheckTool(Tool):
    name = "compose-pull-check"
    category = "docker"
    description = "Check for available image updates"

    def dry_run(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        return self.execute(ssh, config, out)

    def execute(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        base = _compose_cmd(config)
        # Try --dry-run first
        inner = f"{base} pull --dry-run 2>&1"
        cmd = f"bash -c {shlex.quote(inner)}"
        result = ssh.run(cmd, timeout=120)
        if not result.ok or "unknown flag" in result.stdout.lower() + result.stderr.lower():
            # Fallback: real pull with grep
            inner = f"{base} pull 2>&1 | grep -iE 'pulling|up to date|downloaded'"
            cmd = f"bash -c {shlex.quote(inner)}"
            result = ssh.run(cmd, timeout=120)

        out(result.stdout or result.stderr or "No output.")
        return ToolResult(success=True, output=result.stdout, error=result.stderr)


class RestartContainerTool(Tool):
    name = "restart-containers"
    category = "docker"
    description = "Restart docker compose services"
    read_only = False

    def dry_run(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        result = ssh.run("docker ps --format 'table {{.Names}}\t{{.Status}}'", timeout=15)
        out(result.stdout)
        return ToolResult(success=result.ok, output=result.stdout, error=result.stderr)

    def execute(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        base = _compose_cmd(config)
        cmd = f"bash -c {shlex.quote(f'{base} restart')}"
        result = ssh.run(cmd, timeout=120)
        if not result.ok:
            out(result.stderr)
            return ToolResult(success=False, error=result.stderr)

        status = ssh.run("docker ps --format 'table {{.Names}}\t{{.Status}}'", timeout=15)
        out(status.stdout)
        return ToolResult(success=True, output=status.stdout)


TOOLS = [ContainerLogsTool(), ComposePullCheckTool(), RestartContainerTool()]
