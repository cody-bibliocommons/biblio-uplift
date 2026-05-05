from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from biblio_uplift.core.tools import Tool, ToolResult

if TYPE_CHECKING:
    from biblio_uplift.config.schema import ProjectConfig
    from biblio_uplift.core.ssh import SSHRunner


class SudoUsersTool(Tool):
    name = "sudo-users"
    category = "Users & Access"
    description = "List users with sudo access and NOPASSWD status"
    read_only = True

    def dry_run(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        return self.execute(ssh, config, out)

    def execute(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        out("Sudo configuration:")
        out("")

        # Check /etc/sudoers for NOPASSWD entries
        r = ssh.run("grep -rh 'NOPASSWD\\|ALL=(ALL)' /etc/sudoers /etc/sudoers.d/ 2>/dev/null | grep -v '^#'")
        if r.ok and r.stdout.strip():
            out("[bold]NOPASSWD entries (no password required):[/bold]")
            for line in r.stdout.strip().splitlines():
                out(f"  [yellow]{line.strip()}[/yellow]")
        else:
            out("  No NOPASSWD entries found.")

        out("")

        # List sudoers.d files
        r = ssh.run("ls -la /etc/sudoers.d/ 2>/dev/null")
        if r.ok and r.stdout.strip():
            out("[bold]Sudoers drop-in files:[/bold]")
            for line in r.stdout.strip().splitlines():
                out(f"  {line}")

        out("")

        # Show who can sudo by checking group membership
        r = ssh.run("getent group sudo wheel 2>/dev/null")
        if r.ok and r.stdout.strip():
            out("[bold]Sudo/wheel group members:[/bold]")
            for line in r.stdout.strip().splitlines():
                parts = line.split(":")
                if len(parts) >= 4:
                    group = parts[0]
                    members = parts[3]
                    out(f"  {group}: {members if members else '(empty)'}")

        return ToolResult(success=True)


class AuthorizedKeysTool(Tool):
    name = "authorized-keys"
    category = "Users & Access"
    description = "Review SSH authorized keys for all users"
    read_only = True

    def dry_run(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        return self.execute(ssh, config, out)

    def execute(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        cmd = (
            'for user_home in /home/* /root; do '
            'keys="$user_home/.ssh/authorized_keys"; '
            'if [ -f "$keys" ]; then '
            'echo "=== $(basename $user_home) ==="; '
            'wc -l < "$keys"; '
            "cat \"$keys\" | awk '{print $NF}'; "
            "fi; done"
        )
        result = ssh.run(cmd, timeout=15)
        out(result.stdout or "No authorized_keys found.")
        return ToolResult(success=result.ok, output=result.stdout, error=result.stderr)


class GroupMembershipTool(Tool):
    name = "group-membership"
    category = "Users & Access"
    description = "Show docker and sudo group members"
    read_only = True

    def dry_run(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        return self.execute(ssh, config, out)

    def execute(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        result = ssh.run("getent group docker sudo wheel 2>/dev/null", timeout=15)
        out(result.stdout or "No matching groups found.")
        return ToolResult(success=result.ok, output=result.stdout, error=result.stderr)


TOOLS = [SudoUsersTool(), AuthorizedKeysTool(), GroupMembershipTool()]
