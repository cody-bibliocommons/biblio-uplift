from __future__ import annotations

import shlex
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from biblio_uplift.core.tools import Tool, ToolResult

if TYPE_CHECKING:
    from biblio_uplift.config.schema import ProjectConfig
    from biblio_uplift.core.ssh import SSHRunner


class DnsResolutionTool(Tool):
    name = "dns-resolution"
    category = "Network"
    description = "Test DNS resolution for key hostnames"
    read_only = True

    def dry_run(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        return self.execute(ssh, config, out)

    def execute(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        # Resolve remote hostname via separate call (avoids shell expansion injection)
        hostname_r = ssh.run("hostname -f", timeout=5)
        remote_host = hostname_r.stdout.strip() if hostname_r.ok else "localhost"

        hosts = [remote_host, "google.com"]
        for url in config.healthcheck_urls:
            host = urlparse(url).hostname
            if host and host not in hosts:
                hosts.append(host)

        lines = []
        for h in hosts:
            result = ssh.run(f"dig +short {shlex.quote(h)}", timeout=15)
            resolved = result.stdout.strip() or "NXDOMAIN"
            lines.append(f"{h}: {resolved}")

        output = "\n".join(lines)
        out(output)
        return ToolResult(success=True, output=output)


class NtpSyncTool(Tool):
    name = "ntp-sync"
    category = "Network"
    description = "Check NTP synchronization status"
    read_only = True

    def dry_run(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        return self.execute(ssh, config, out)

    def execute(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        sync = ssh.run("timedatectl show --property=NTPSynchronized --value", timeout=15)
        detail = ssh.run(
            "bash -c 'timedatectl timesync-status 2>/dev/null || chronyc tracking 2>/dev/null || ntpq -p 2>/dev/null'",
            timeout=15,
        )
        output = f"NTPSynchronized: {sync.stdout.strip()}\n{detail.stdout.strip()}"
        out(output)
        return ToolResult(success=sync.ok, output=output, error=sync.stderr)


class CertificateExpiryTool(Tool):
    name = "certificate-expiry"
    category = "Network"
    description = "Check SSL certificate expiry for healthcheck URLs"
    read_only = True

    def dry_run(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        return self.execute(ssh, config, out)

    def execute(self, ssh: SSHRunner, config: ProjectConfig, out: Callable[[str], None]) -> ToolResult:
        lines = []
        for url in config.healthcheck_urls:
            host = urlparse(url).hostname
            if not host:
                continue
            host_q = shlex.quote(host)
            inner = (
                f"echo | openssl s_client -connect {host_q}:443"
                f" -servername {host_q} 2>/dev/null"
                f" | openssl x509 -noout -dates 2>/dev/null"
            )
            cmd = f"bash -c {shlex.quote(inner)}"
            result = ssh.run(cmd, timeout=15)
            if result.ok and result.stdout.strip():
                for line in result.stdout.strip().splitlines():
                    if line.startswith("notAfter="):
                        date_str = line.split("=", 1)[1]
                        try:
                            expiry = datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                            days = (expiry - datetime.now(timezone.utc)).days
                            warn = " ⚠ EXPIRING SOON" if days < 30 else ""
                            lines.append(f"{host}: expires in {days} days{warn}")
                        except ValueError:
                            lines.append(f"{host}: {line}")
            else:
                lines.append(f"{host}: unable to check certificate")

        output = "\n".join(lines) if lines else "No HTTPS healthcheck URLs configured."
        out(output)
        return ToolResult(success=True, output=output)


TOOLS = [DnsResolutionTool(), NtpSyncTool(), CertificateExpiryTool()]
