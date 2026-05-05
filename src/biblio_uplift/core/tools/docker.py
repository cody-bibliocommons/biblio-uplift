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


class FreeIpaLogsTool(Tool):
    name = "freeipa-logs"
    category = "Docker"
    description = "Manage FreeIPA container logs (httpd, krb5kdc, dirsrv, sssd, pki, journal)"
    read_only = False

    def dry_run(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        out("[DRY RUN] FreeIPA log management preview:")
        out("")
        # Find freeipa container
        r = ssh.run("docker ps --format '{{.Names}}' | grep -i freeipa")
        if not r.ok or not r.stdout.strip():
            out("[yellow]No FreeIPA container found on this server.[/yellow]")
            return ToolResult(success=True)
        container = r.stdout.strip().splitlines()[0]
        out(f"Container: {container}")
        out("")

        # Show current log sizes
        out("Current log sizes:")
        r = ssh.run(f"docker exec {container} du -sh /var/log/httpd/ /var/log/krb5kdc.log /var/log/dirsrv/ 2>/dev/null")
        if r.ok:
            for line in r.stdout.strip().splitlines():
                out(f"  {line}")

        r = ssh.run(f"docker exec {container} du -sh /var/log/sssd/ 2>/dev/null")
        if r.ok and r.stdout.strip():
            out(f"  SSSD: {r.stdout.strip().split()[0]}")

        r = ssh.run(f"docker exec {container} du -sh /var/log/pki/ 2>/dev/null")
        if r.ok and r.stdout.strip():
            out(f"  PKI: {r.stdout.strip().split()[0]}")
        r = ssh.run(f"docker exec {container} du -sh /var/log/journal/ 2>/dev/null")
        if r.ok and r.stdout.strip():
            out(f"  Journal: {r.stdout.strip().split()[0]}")

        out("")
        out("Would perform:")
        out("  - Compress httpd logs older than 1 day")
        out("  - Remove compressed httpd logs older than 7 days")
        out("  - Truncate active httpd logs (error_log, access_log, ssl_request_log)")
        out("  - Remove dirsrv access logs older than 3 days")
        out("  - Compress krb5kdc.log and start fresh")
        out("  - Truncate SSSD logs > 1MB")
        out("  - Truncate DNF logs")
        out("  - Remove audit logs older than 7 days")
        out("  - Vacuum journal to 7 days")
        out("  - Remove PKI signed audit logs older than 7 days")
        out("  - Truncate PKI CA logs larger than 10MB")
        out("  - Remove journal files older than 7 days")
        return ToolResult(success=True)

    def execute(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        # Find freeipa container
        r = ssh.run("docker ps --format '{{.Names}}' | grep -i freeipa")
        if not r.ok or not r.stdout.strip():
            out("[yellow]No FreeIPA container found on this server.[/yellow]")
            return ToolResult(success=True, output="No FreeIPA container")
        container = r.stdout.strip().splitlines()[0]
        out(f"Managing logs for: {container}")
        out("")

        # Show before sizes
        out("Before:")
        r = ssh.run(f"docker exec {container} du -sh /var/log/httpd/ /var/log/krb5kdc.log /var/log/dirsrv/ 2>/dev/null")
        if r.ok:
            for line in r.stdout.strip().splitlines():
                out(f"  {line}")
        out("")

        # 1. Compress old httpd logs (older than 1 day)
        out("Compressing httpd logs older than 1 day...")
        ssh.run(f"docker exec {container} find /var/log/httpd -name '*.log.*' -mtime +1 -not -name '*.gz' -exec gzip {{}} \\;")

        # 2. Remove compressed httpd logs older than 7 days
        out("Removing compressed httpd logs older than 7 days...")
        r = ssh.run(f"docker exec {container} find /var/log/httpd -name '*.gz' -mtime +7 -delete -print 2>/dev/null | wc -l")
        if r.ok and r.stdout.strip() != '0':
            out(f"  Removed {r.stdout.strip()} old compressed logs")

        # 3. Truncate active httpd logs
        out("Truncating active httpd logs...")
        for log in ["error_log", "access_log", "ssl_request_log"]:
            ssh.run(f"docker exec {container} truncate -s 0 /var/log/httpd/{log}")
        out("  Truncated: error_log, access_log, ssl_request_log")

        # 4. Remove old dirsrv access logs (older than 3 days)
        out("Cleaning dirsrv logs older than 3 days...")
        r = ssh.run(f"docker exec {container} find /var/log/dirsrv -name 'access.*' -mtime +3 -delete -print 2>/dev/null | wc -l")
        if r.ok and r.stdout.strip() != '0':
            out(f"  Removed {r.stdout.strip()} old dirsrv access logs")
        r = ssh.run(f"docker exec {container} find /var/log/dirsrv -name 'errors.*' -mtime +3 -delete -print 2>/dev/null | wc -l")
        if r.ok and r.stdout.strip() != '0':
            out(f"  Removed {r.stdout.strip()} old dirsrv error logs")

        # 5. Compress and truncate krb5kdc.log
        out("Compressing krb5kdc.log...")
        ssh.run(f"docker exec {container} bash -c 'cp /var/log/krb5kdc.log /var/log/krb5kdc.log.1 && truncate -s 0 /var/log/krb5kdc.log && gzip -f /var/log/krb5kdc.log.1'")
        out("  Compressed and truncated krb5kdc.log")

        # Remove old krb5kdc compressed logs
        ssh.run(f"docker exec {container} find /var/log -name 'krb5kdc.log.*.gz' -mtime +7 -delete 2>/dev/null")

        # 6. Clean SSSD logs
        out("Cleaning SSSD logs...")
        ssh.run(f"docker exec {container} find /var/log/sssd -name '*.log' -size +1M -exec truncate -s 0 {{}} \\;")
        out("  Truncated SSSD logs > 1MB")

        # 7. Clean DNF logs
        out("Cleaning DNF logs...")
        ssh.run(f"docker exec {container} truncate -s 0 /var/log/dnf.log /var/log/dnf.rpm.log /var/log/dnf.librepo.log /var/log/hawkey.log 2>/dev/null")
        out("  Truncated DNF logs")

        # 8. Clean audit logs
        out("Cleaning audit logs...")
        r = ssh.run(f"docker exec {container} find /var/log/audit -name 'audit.log.*' -mtime +7 -delete -print 2>/dev/null | wc -l")
        if r.ok and r.stdout.strip() != '0':
            out(f"  Removed {r.stdout.strip()} old audit logs")

        # 9. Vacuum journal inside container
        out("Vacuuming container journal...")
        ssh.run(f"docker exec {container} journalctl --vacuum-time=7d 2>/dev/null")
        out("  Journal vacuumed to 7 days")

        # 10. Clean PKI/Tomcat signed audit logs
        out("Cleaning PKI signed audit logs...")
        r = ssh.run(f"docker exec {container} find /var/log/pki/pki-tomcat/ca/signedAudit -type f -mtime +7 -delete -print 2>/dev/null | wc -l")
        if r.ok and r.stdout.strip() != '0':
            out(f"  Removed {r.stdout.strip()} old PKI audit logs")
        else:
            out("  No old PKI audit logs to remove")

        # 11. Clean PKI/Tomcat CA logs
        out("Cleaning PKI CA logs...")
        ssh.run(f"docker exec {container} find /var/log/pki/pki-tomcat/ca -name '*.log.*' -mtime +7 -delete 2>/dev/null")
        ssh.run(f"docker exec {container} find /var/log/pki/pki-tomcat -name '*.log' -size +10M -exec truncate -s 0 {{}} \\; 2>/dev/null")
        out("  Cleaned PKI CA logs (removed >7d, truncated >10MB)")

        # 12. Clean container /var/log/journal
        out("Cleaning container journal files...")
        r = ssh.run(f"docker exec {container} find /var/log/journal -type f -mtime +7 -delete -print 2>/dev/null | wc -l")
        if r.ok and r.stdout.strip() != '0':
            out(f"  Removed {r.stdout.strip()} old journal files")
        else:
            out("  No old journal files to remove")

        out("")
        # Show after sizes
        out("After:")
        r = ssh.run(f"docker exec {container} du -sh /var/log/httpd/ /var/log/krb5kdc.log /var/log/dirsrv/ 2>/dev/null")
        if r.ok:
            for line in r.stdout.strip().splitlines():
                out(f"  {line}")

        return ToolResult(success=True, output="FreeIPA logs cleaned")


TOOLS = [ContainerLogsTool(), ComposePullCheckTool(), RestartContainerTool(), FreeIpaLogsTool()]
