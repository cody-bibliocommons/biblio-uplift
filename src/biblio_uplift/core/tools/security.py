from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from biblio_uplift.core.tools import Tool, ToolResult

if TYPE_CHECKING:
    from biblio_uplift.config.schema import ProjectConfig
    from biblio_uplift.core.ssh import SSHRunner


class PendingSecurityUpdates(Tool):
    name = "pending-security-updates"
    category = "security"
    description = "Check for pending apt security updates"

    def dry_run(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        return self.execute(ssh, config, out)

    def execute(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        result = ssh.run("apt-get update -qq 2>/dev/null && apt list --upgradable 2>/dev/null", timeout=60)
        out(result.stdout or "No upgradable packages.")
        return ToolResult(success=result.ok, output=result.stdout, error=result.stderr)


class OpenPortsAudit(Tool):
    name = "open-ports-audit"
    category = "security"
    description = "Show listening TCP ports"

    def dry_run(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        return self.execute(ssh, config, out)

    def execute(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        result = ssh.run("ss -tlnp", timeout=15)
        out(result.stdout)
        return ToolResult(success=result.ok, output=result.stdout, error=result.stderr)


class SshConfigReview(Tool):
    name = "ssh-config-review"
    category = "security"
    description = "Review sshd security settings"

    def dry_run(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        return self.execute(ssh, config, out)

    def execute(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        result = ssh.run("sshd -T 2>/dev/null || cat /etc/ssh/sshd_config", timeout=15)
        if not result.ok:
            out(result.stderr)
            return ToolResult(success=False, error=result.stderr)

        lines = result.stdout.lower()
        checks = {
            "PermitRootLogin": ("permitrootlogin no", "permitrootlogin"),
            "PasswordAuthentication": ("passwordauthentication no", "passwordauthentication"),
            "PubkeyAuthentication": ("pubkeyauthentication yes", "pubkeyauthentication"),
        }
        output_lines = []
        for label, (good_val, key) in checks.items():
            if good_val in lines:
                output_lines.append(f"  ✓ {label}: PASS")
            elif key in lines:
                output_lines.append(f"  ⚠ {label}: WARN")
            else:
                output_lines.append(f"  ? {label}: not found")

        output = "\n".join(output_lines)
        out(output)
        return ToolResult(success=True, output=output)


TOOLS = [PendingSecurityUpdates(), OpenPortsAudit(), SshConfigReview()]
