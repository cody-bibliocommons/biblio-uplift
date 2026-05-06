from __future__ import annotations

import shlex
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
        r = ssh.run(
            "bash -c \"grep -rh 'NOPASSWD\\|ALL=(ALL)' /etc/sudoers /etc/sudoers.d/ 2>/dev/null | grep -v '^#'\""
        )
        if r.ok and r.stdout.strip():
            out("[bold]NOPASSWD entries (no password required):[/bold]")
            for line in r.stdout.strip().splitlines():
                out(f"  [yellow]{line.strip()}[/yellow]")
        else:
            out("  No NOPASSWD entries found.")

        out("")

        # List sudoers.d files
        r = ssh.run("bash -c 'ls -la /etc/sudoers.d/ 2>/dev/null'")
        if r.ok and r.stdout.strip():
            out("[bold]Sudoers drop-in files:[/bold]")
            for line in r.stdout.strip().splitlines():
                out(f"  {line}")

        out("")

        # Show who can sudo by checking group membership
        r = ssh.run("bash -c 'for g in sudo wheel; do getent group $g 2>/dev/null; done'")
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
        out("SSH Authorized Keys:")
        out("")
        r = ssh.run("bash -c 'ls -d /home/* /root 2>/dev/null'")
        if not r.ok:
            return ToolResult(success=False, error="Could not list home directories")

        found = False
        for home in r.stdout.strip().splitlines():
            home = home.strip()
            if not home:
                continue
            user = home.split("/")[-1]
            keys_file = f"{home}/.ssh/authorized_keys"
            keys_q = shlex.quote(keys_file)
            r2 = ssh.run(f"bash -c 'test -f {keys_q} && wc -l < {keys_q}'")
            if r2.ok and r2.stdout.strip():
                found = True
                count = r2.stdout.strip()
                out(f"[bold]{user}[/bold]: {count} key(s)")
                r3 = ssh.run(f"awk '{{print $NF}}' {keys_q}")
                if r3.ok:
                    for line in r3.stdout.strip().splitlines():
                        out(f"  {line}")
                out("")

        if not found:
            out("No authorized_keys found.")

        return ToolResult(success=True)


class GroupMembershipTool(Tool):
    name = "group-membership"
    category = "Users & Access"
    description = "Show docker and sudo group members"
    read_only = True

    def dry_run(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        return self.execute(ssh, config, out)

    def execute(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        result = ssh.run("bash -c 'for g in docker sudo wheel; do getent group $g 2>/dev/null; done'", timeout=15)
        out(result.stdout or "No matching groups found.")
        return ToolResult(success=True, output=result.stdout)


TOOLS = [SudoUsersTool(), AuthorizedKeysTool(), GroupMembershipTool()]
