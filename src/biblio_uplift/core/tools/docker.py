from __future__ import annotations

import shlex
from collections.abc import Callable
from typing import TYPE_CHECKING

from biblio_uplift.core.steps.docker import _bash_compose, _compose_cmd
from biblio_uplift.core.tools import Tool, ToolResult

if TYPE_CHECKING:
    from biblio_uplift.config.schema import ProjectConfig
    from biblio_uplift.core.ssh import SSHRunner


class ContainerLogsTool(Tool):
    name = "container-logs"
    category = "Docker"
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
    category = "Docker"
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
            # Fallback: show current images and their digests
            inner = f"{base} images --format '{{{{.Repository}}}}:{{{{.Tag}}}}  {{{{.ID}}}}'"
            cmd = f"bash -c {shlex.quote(inner)}"
            result = ssh.run(cmd, timeout=60)

        out(result.stdout or result.stderr or "No output.")
        return ToolResult(success=True, output=result.stdout, error=result.stderr)


class RestartContainerTool(Tool):
    name = "restart-containers"
    category = "Docker"
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
        r = ssh.run("bash -c \"docker ps --format '{{.Names}}' | grep -i freeipa\"")
        if not r.ok or not r.stdout.strip():
            out("[yellow]No FreeIPA container found on this server.[/yellow]")
            return ToolResult(success=True)
        container = shlex.quote(r.stdout.strip().splitlines()[0])
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
        r = ssh.run("bash -c \"docker ps --format '{{.Names}}' | grep -i freeipa\"")
        if not r.ok or not r.stdout.strip():
            out("[yellow]No FreeIPA container found on this server.[/yellow]")
            return ToolResult(success=True, output="No FreeIPA container")
        container = shlex.quote(r.stdout.strip().splitlines()[0])
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
        cmd = (
            f"docker exec {container} find /var/log/httpd -name '*.log.*'"
            f" -mtime +1 -not -name '*.gz' -exec gzip {{}} \\;"
        )
        ssh.run(cmd)

        # 2. Remove compressed httpd logs older than 7 days
        out("Removing compressed httpd logs older than 7 days...")
        cmd = f"docker exec {container} find /var/log/httpd -name '*.gz' -mtime +7 -delete -print 2>/dev/null | wc -l"
        r = ssh.run(cmd)
        if r.ok and r.stdout.strip() != "0":
            out(f"  Removed {r.stdout.strip()} old compressed logs")

        # 3. Truncate active httpd logs
        out("Truncating active httpd logs...")
        for log in ["error_log", "access_log", "ssl_request_log"]:
            ssh.run(f"docker exec {container} truncate -s 0 /var/log/httpd/{log}")
        out("  Truncated: error_log, access_log, ssl_request_log")

        # 4. Remove old dirsrv access logs (older than 3 days)
        out("Cleaning dirsrv logs older than 3 days...")
        cmd = (
            f"docker exec {container} find /var/log/dirsrv -name 'access.*'"
            f" -mtime +3 -delete -print 2>/dev/null | wc -l"
        )
        r = ssh.run(cmd)
        if r.ok and r.stdout.strip() != "0":
            out(f"  Removed {r.stdout.strip()} old dirsrv access logs")
        cmd = (
            f"docker exec {container} find /var/log/dirsrv -name 'errors.*'"
            f" -mtime +3 -delete -print 2>/dev/null | wc -l"
        )
        r = ssh.run(cmd)
        if r.ok and r.stdout.strip() != "0":
            out(f"  Removed {r.stdout.strip()} old dirsrv error logs")

        # 5. Compress and truncate krb5kdc.log
        out("Compressing krb5kdc.log...")
        cmd = (
            f"docker exec {container} bash -c 'cp /var/log/krb5kdc.log"
            f" /var/log/krb5kdc.log.1 && truncate -s 0 /var/log/krb5kdc.log"
            f" && gzip -f /var/log/krb5kdc.log.1'"
        )
        ssh.run(cmd)
        out("  Compressed and truncated krb5kdc.log")

        # Remove old krb5kdc compressed logs
        ssh.run(f"docker exec {container} find /var/log -name 'krb5kdc.log.*.gz' -mtime +7 -delete 2>/dev/null")

        # 6. Clean SSSD logs
        out("Cleaning SSSD logs...")
        ssh.run(f"docker exec {container} find /var/log/sssd -name '*.log' -size +1M -exec truncate -s 0 {{}} \\;")
        out("  Truncated SSSD logs > 1MB")

        # 7. Clean DNF logs
        out("Cleaning DNF logs...")
        cmd = (
            f"docker exec {container} truncate -s 0 /var/log/dnf.log"
            f" /var/log/dnf.rpm.log /var/log/dnf.librepo.log"
            f" /var/log/hawkey.log 2>/dev/null"
        )
        ssh.run(cmd)
        out("  Truncated DNF logs")

        # 8. Clean audit logs
        out("Cleaning audit logs...")
        cmd = (
            f"docker exec {container} find /var/log/audit"
            f" -name 'audit.log.*' -mtime +7 -delete -print 2>/dev/null | wc -l"
        )
        r = ssh.run(cmd)
        if r.ok and r.stdout.strip() != "0":
            out(f"  Removed {r.stdout.strip()} old audit logs")

        # 9. Vacuum journal inside container
        out("Vacuuming container journal...")
        ssh.run(f"docker exec {container} journalctl --vacuum-time=7d 2>/dev/null")
        out("  Journal vacuumed to 7 days")

        # 10. Clean PKI/Tomcat signed audit logs
        out("Cleaning PKI signed audit logs...")
        cmd = (
            f"docker exec {container} find /var/log/pki/pki-tomcat/ca/signedAudit"
            f" -type f -mtime +7 -delete -print 2>/dev/null | wc -l"
        )
        r = ssh.run(cmd)
        if r.ok and r.stdout.strip() != "0":
            out(f"  Removed {r.stdout.strip()} old PKI audit logs")
        else:
            out("  No old PKI audit logs to remove")

        # 11. Clean PKI/Tomcat CA logs
        out("Cleaning PKI CA logs...")
        ssh.run(
            f"docker exec {container} find /var/log/pki/pki-tomcat/ca -name '*.log.*' -mtime +7 -delete 2>/dev/null"
        )
        cmd = (
            f"docker exec {container} find /var/log/pki/pki-tomcat"
            f" -name '*.log' -size +10M -exec truncate -s 0 {{}} \\; 2>/dev/null"
        )
        ssh.run(cmd)
        out("  Cleaned PKI CA logs (removed >7d, truncated >10MB)")

        # 12. Clean container /var/log/journal
        out("Cleaning container journal files...")
        cmd = f"docker exec {container} find /var/log/journal -type f -mtime +7 -delete -print 2>/dev/null | wc -l"
        r = ssh.run(cmd)
        if r.ok and r.stdout.strip() != "0":
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


class UpdateServiceTool(Tool):
    name = "update-service"
    category = "Docker"
    description = "Pull repo + rebuild/recreate a service (or all)"
    read_only = False

    def __init__(self):
        self.target_service: str = ""  # Set externally; empty = all

    def dry_run(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        cmd = _bash_compose(config, "ps --services")
        r = ssh.run(cmd)
        services = [s.strip() for s in r.stdout.strip().splitlines() if s.strip()] if r.ok else []
        out("[DRY RUN] Available services:")
        for svc in services:
            out(f"  - {svc}")
        out("")
        target = self.target_service if self.target_service in services else ""
        if target:
            out(f"Would update: [bold]{target}[/bold]")
        else:
            out("Would update: [bold]all services[/bold]")
        out("")
        out("Steps:")
        out("  1. git fetch + reset to origin")
        out("  2. docker compose pull")
        out("  3. docker compose up -d --force-recreate")
        return ToolResult(success=True)

    def execute(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        cmd = _bash_compose(config, "ps --services")
        r = ssh.run(cmd)
        if not r.ok or not r.stdout.strip():
            out("[red]Could not list services[/red]")
            return ToolResult(success=False, error="Failed to list services")

        services = [s.strip() for s in r.stdout.strip().splitlines() if s.strip()]
        target = self.target_service if self.target_service in services else ""

        out("Available services:")
        for svc in services:
            marker = " [bold cyan]◀[/bold cyan]" if svc == target else ""
            out(f"  - {svc}{marker}")
        out("")
        if target:
            out(f"Updating: [bold]{target}[/bold]")
        else:
            out("Updating: [bold]all services[/bold]")
        out("")

        # Git pull
        out("Pulling latest repo...")
        project_dir = str(config.project_dir)
        dir_q = shlex.quote(project_dir)
        git_cmd = (
            f"grep -q bitbucket.org ~/.ssh/known_hosts 2>/dev/null"
            f" || ssh-keyscan -t ed25519 bitbucket.org >> ~/.ssh/known_hosts 2>/dev/null; "
            f"cd {dir_q} && git -c safe.directory={dir_q} fetch origin && "
            f"git -c safe.directory={dir_q} reset --hard "
            f"origin/$(git -c safe.directory={dir_q} rev-parse --abbrev-ref HEAD)"
        )
        # Check for detached HEAD
        branch_r = ssh.run(
            f"bash -c 'cd {dir_q} && git -c safe.directory={dir_q} rev-parse --abbrev-ref HEAD'",
            timeout=15,
        )
        if branch_r.ok and branch_r.stdout.strip() == "HEAD":
            out("[red]Repository is in detached HEAD state. Cannot determine branch.[/red]")
            return ToolResult(success=False, error="Detached HEAD state")

        r = ssh.run(f"bash -c {shlex.quote(git_cmd)}", timeout=120)
        if r.ok:
            out("  Git pull: OK")
        else:
            out(f"  [red]Git pull failed: {r.stderr}[/red]")
            return ToolResult(success=False, error=f"Git pull failed: {r.stderr}")

        # Pull images
        pull_arg = f"pull {shlex.quote(target)}" if target else "pull"
        out("Pulling latest images...")
        r = ssh.run(_bash_compose(config, pull_arg), timeout=300)
        if r.ok:
            out("  Image pull: OK")
        else:
            out(f"  [yellow]Image pull warning: {r.stderr}[/yellow]")

        # Recreate
        up_arg = f"up -d --no-deps --force-recreate {shlex.quote(target)}" if target else "up -d --force-recreate"
        out("Recreating...")
        r = ssh.run(_bash_compose(config, up_arg), timeout=120)
        if r.ok:
            out("  Recreate: OK")
        else:
            out(f"  [red]Recreate failed: {r.stderr}[/red]")
            return ToolResult(success=False, error=f"Recreate failed: {r.stderr}")

        # Status
        out("")
        out("Service status:")
        r = ssh.run(_bash_compose(config, 'ps --format "table {{.Name}}\t{{.Status}}"'))
        if r.ok:
            for line in r.stdout.strip().splitlines():
                out(f"  {line}")

        return ToolResult(success=True, output=f"{'Service ' + target if target else 'All services'} updated")


class ComposeVersionTool(Tool):
    name = "compose-version"
    category = "Docker"
    description = "Check Docker Compose version and install method; upgrade manual binary to package-managed"
    read_only = False

    _DETECT_SCRIPT = r"""
V=$(docker compose version 2>/dev/null || docker-compose --version 2>/dev/null || echo "")
# Check snap
if snap list docker 2>/dev/null | grep -q ^docker; then echo "PACKAGE"; echo "$V"; exit 0; fi
# Check dpkg packages
if dpkg -l docker-compose-plugin 2>/dev/null | grep -q ^ii; then echo "PACKAGE"; echo "$V"; exit 0; fi
if dpkg -l docker-compose-v2 2>/dev/null | grep -q ^ii; then echo "PACKAGE"; echo "$V"; exit 0; fi
# Check rpm
if rpm -q docker-compose-plugin 2>/dev/null | grep -qv 'not installed'; then echo "PACKAGE"; echo "$V"; exit 0; fi
# Check known binary paths
for p in /usr/local/bin/docker-compose /usr/local/lib/docker/cli-plugins/docker-compose /usr/bin/docker-compose; do
  if [ -f "$p" ]; then
    if dpkg -S "$p" 2>/dev/null | grep -qv 'no path found'; then echo "PACKAGE $p"; echo "$V"; exit 0; fi
    if rpm -qf "$p" 2>/dev/null | grep -qvE 'not owned|is not owned'; then echo "PACKAGE $p"; echo "$V"; exit 0; fi
    echo "MANUAL $p"; echo "$V"; exit 0
  fi
done
echo "NONE"; echo "$V"
"""

    def _detect(self, ssh: SSHRunner) -> tuple[str, str, str]:
        """Return (version_string, install_method, binary_path).

        method is 'package', 'manual', or 'none'. Single SSH round-trip.
        """
        r = ssh.run(f"bash -c {shlex.quote(self._DETECT_SCRIPT)}", timeout=20)
        if not r.ok:
            return "", "none", ""

        lines = r.stdout.strip().splitlines()
        if len(lines) < 2:
            return "", "none", ""

        status_line = lines[0].strip()
        version = lines[1].strip()

        if status_line.startswith("PACKAGE"):
            path = status_line[len("PACKAGE") :].strip()
            return version, "package", path
        elif status_line.startswith("MANUAL"):
            path = status_line[len("MANUAL") :].strip()
            return version, "manual", path
        return version, "none", ""

    def dry_run(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        version, method, path = self._detect(ssh)
        out(f"Docker Compose version: {version or 'not available'}")
        out(f"Install method: {method}")
        if path:
            out(f"Binary path: {path}")
        if method == "manual":
            out("Would replace manual binary with package-managed docker-compose-plugin (v2)")
        elif method == "none":
            out("Would install docker-compose-plugin (v2)")
        return ToolResult(success=True, output=f"{version or 'none'} ({method})")

    def execute(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        version, method, path = self._detect(ssh)
        out(f"Docker Compose version: {version or 'not available'}")
        out(f"Install method: {method}")
        if path:
            out(f"Binary path: {path}")

        if method == "package":
            out("Already package-managed, nothing to do.")
            return ToolResult(success=True, output=f"{version} (package-managed)")

        # Backup manual binary before removing (use mktemp to avoid symlink attacks)
        backup_path = ""
        if method == "manual" and path:
            tmp_r = ssh.run("mktemp /tmp/docker-compose.XXXXXX", timeout=5)
            if not tmp_r.ok:
                out("[red]Failed to create temp file for backup[/red]")
                return ToolResult(success=False, error="mktemp failed")
            backup_path = tmp_r.stdout.strip()
            out(f"Backing up {path} to {backup_path}...")
            backup_r = ssh.run(
                f"bash -c 'cp {shlex.quote(path)} {shlex.quote(backup_path)} && rm -f {shlex.quote(path)}'",
                timeout=10,
            )
            if not backup_r.ok:
                out(f"[red]Backup failed: {backup_r.stderr}[/red]")
                return ToolResult(success=False, error=f"Backup failed: {backup_r.stderr}")
        elif method == "none":
            out("No compose found. Installing package...")

        # Detect OS and install
        r = ssh.run("cat /etc/os-release", timeout=10)
        os_info = r.stdout.lower() if r.ok else ""

        if any(d in os_info for d in ("ubuntu", "debian")):
            out("Installing docker compose v2 via apt...")
            r = ssh.run(
                "bash -c 'apt-get install -y docker-compose-plugin"
                " 2>/dev/null || apt-get install -y docker-compose-v2'",
                timeout=120,
            )
            if not r.ok:
                out("Package not in cache, running apt-get update...")
                r = ssh.run(
                    "bash -c 'apt-get update && (apt-get install -y"
                    " docker-compose-plugin || apt-get install -y docker-compose-v2)'",
                    timeout=180,
                )
        else:
            out("Installing docker-compose-plugin via dnf/yum...")
            r = ssh.run(
                "bash -c 'dnf install -y docker-compose-plugin 2>/dev/null || yum install -y docker-compose-plugin'",
                timeout=120,
            )

        if not r.ok:
            if backup_path and path:
                out("[yellow]Install failed, restoring backup...[/yellow]")
                ssh.run(
                    f"bash -c 'cp {shlex.quote(backup_path)} {shlex.quote(path)} && chmod +x {shlex.quote(path)}'",
                    timeout=10,
                )
            ssh.run(f"rm -f {shlex.quote(backup_path)}", timeout=5) if backup_path else None
            out(f"[red]Install failed: {r.stderr}[/red]")
            return ToolResult(success=False, error=r.stderr)

        # Verify compose works after install
        r = ssh.run("docker compose version", timeout=15)
        if not r.ok:
            out("[yellow]Package installed but 'docker compose version' failed. Restoring backup...[/yellow]")
            if backup_path and path:
                ssh.run(
                    f"bash -c 'cp {shlex.quote(backup_path)} {shlex.quote(path)} && chmod +x {shlex.quote(path)}'",
                    timeout=10,
                )
            ssh.run(f"rm -f {shlex.quote(backup_path)}", timeout=5) if backup_path else None
            return ToolResult(success=False, error="Package installed but compose not functional")

        new_version = r.stdout.strip()
        out(f"New version: {new_version}")

        # Clean up backup
        if backup_path:
            ssh.run(f"rm -f {shlex.quote(backup_path)}", timeout=5)

        return ToolResult(success=True, output=f"Upgraded to {new_version} (package-managed)")


TOOLS = [
    ContainerLogsTool(),
    ComposePullCheckTool(),
    RestartContainerTool(),
    FreeIpaLogsTool(),
    UpdateServiceTool(),
    ComposeVersionTool(),
]
