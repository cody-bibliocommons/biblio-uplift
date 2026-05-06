from __future__ import annotations

import shlex
from collections.abc import Callable
from typing import TYPE_CHECKING

from biblio_uplift.core.tools import Tool, ToolResult

if TYPE_CHECKING:
    from biblio_uplift.config.schema import ProjectConfig
    from biblio_uplift.core.ssh import SSHRunner

TARGET_SIZE = "500M"


class JournaldConfigTool(Tool):
    name = "journald-config"
    category = "system"
    description = "Limit journald disk usage to 500M"
    read_only = False

    def dry_run(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        r1 = ssh.run(
            "bash -c \"grep SystemMaxUse /etc/systemd/journald.conf 2>/dev/null || echo 'not set'\"", timeout=10
        )
        r2 = ssh.run("journalctl --disk-usage", timeout=10)
        output = f"Current setting: {r1.stdout.strip()}\n{r2.stdout.strip()}\nWould set: SystemMaxUse={TARGET_SIZE}"
        out(output)
        return ToolResult(success=True, output=output)

    def execute(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        before = ssh.run("journalctl --disk-usage", timeout=10)
        out(f"Before: {before.stdout.strip()}")

        bak = ssh.run(
            "cp /etc/systemd/journald.conf /etc/systemd/journald.conf.bak.$(date +%s)",
            timeout=10,
        )
        if not bak.ok:
            return ToolResult(success=False, error=f"Backup failed: {bak.stderr}")

        inner = (
            f"sed -i 's/^#\\?SystemMaxUse=.*/SystemMaxUse={TARGET_SIZE}/' /etc/systemd/journald.conf"
            f" && grep -q '^SystemMaxUse=' /etc/systemd/journald.conf"
            f" || echo 'SystemMaxUse={TARGET_SIZE}' >> /etc/systemd/journald.conf"
        )
        sed = ssh.run(f"bash -c {shlex.quote(inner)}", timeout=10)
        if not sed.ok:
            return ToolResult(success=False, error=sed.stderr)

        ssh.run("systemctl restart systemd-journald", timeout=30)

        after = ssh.run("journalctl --disk-usage", timeout=10)
        out(f"After: {after.stdout.strip()}")
        out(f"Set SystemMaxUse={TARGET_SIZE}")
        return ToolResult(success=True, output=f"SystemMaxUse={TARGET_SIZE} applied")


class ForceLogrotateTool(Tool):
    name = "force-logrotate"
    category = "system"
    description = "Force log rotation"
    read_only = False

    def dry_run(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        check = ssh.run("which logrotate", timeout=10)
        if not check.ok:
            return ToolResult(success=False, error="logrotate is not installed on this system")
        result = ssh.run("bash -c 'logrotate -d /etc/logrotate.conf 2>&1 | head -30'", timeout=30)
        out(result.stdout)
        return ToolResult(success=result.ok, output=result.stdout, error=result.stderr)

    def execute(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        check = ssh.run("which logrotate", timeout=10)
        if not check.ok:
            return ToolResult(success=False, error="logrotate is not installed on this system")

        before = ssh.run("du -sh /var/log", timeout=10)
        out(f"Before: {before.stdout.strip()}")

        result = ssh.run("logrotate -f /etc/logrotate.conf", timeout=60)
        if not result.ok:
            return ToolResult(success=False, error=result.stderr)

        after = ssh.run("du -sh /var/log", timeout=10)
        out(f"After: {after.stdout.strip()}")
        return ToolResult(success=True, output=f"Before: {before.stdout.strip()}\nAfter: {after.stdout.strip()}")


class FixPermissionsTool(Tool):
    name = "fix-permissions"
    category = "system"
    description = "Fix file permissions on project directory (group-writable for docker group)"
    read_only = False

    def dry_run(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        project_dir = shlex.quote(str(config.project_dir))
        out("Would fix permissions on:")
        out(f"  {config.project_dir}")
        r = ssh.run(f"stat -c '%U:%G %a' {project_dir}")
        if r.ok:
            out(f"  Current: {r.stdout.strip()}")
        r = ssh.run(f"bash -c 'stat -c \"%U:%G %a\" {project_dir}/.git/objects 2>/dev/null'")
        if r.ok:
            out(f"  .git/objects: {r.stdout.strip()}")
        out("  Would set: group=docker, g+rwX recursively")
        for key_dir in ["/opt/bitbucket", "/opt/docker/bitbucket"]:
            r = ssh.run(f"bash -c 'test -d {key_dir} && stat -c \"%a\" {key_dir}/id_ed25519 2>/dev/null'")
            if r.ok and r.stdout.strip():
                out(f"  SSH key {key_dir}/id_ed25519: mode {r.stdout.strip()} → would set 600")
        return ToolResult(success=True)

    def execute(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        project_dir = shlex.quote(str(config.project_dir))
        out(f"Fixing permissions on {config.project_dir}...")

        r = ssh.run(f"chgrp -R docker {project_dir}")
        if r.ok:
            out("  Group set to docker")

        r = ssh.run(f"chmod -R g+rwX {project_dir}")
        if r.ok:
            out("  Group write enabled")

        for key_dir in ["/opt/bitbucket", "/opt/docker/bitbucket"]:
            ssh.run(f"bash -c 'test -d {key_dir} && chmod 600 {key_dir}/id_ed25519 2>/dev/null'")

        r = ssh.run(f"stat -c '%U:%G %a' {project_dir}")
        if r.ok:
            out(f"  Result: {r.stdout.strip()}")

        return ToolResult(success=True)


TOOLS = [JournaldConfigTool(), ForceLogrotateTool(), FixPermissionsTool()]
