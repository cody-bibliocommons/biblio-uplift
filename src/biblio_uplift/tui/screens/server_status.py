from __future__ import annotations

import logging

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Button, RichLog, Select, Static

from biblio_uplift.config.loader import get_config_dir, list_configs
from biblio_uplift.core.ssh import SSHRunner

logger = logging.getLogger(__name__)


class ServerStatusPanel(Widget):
    DEFAULT_CSS = """
    ServerStatusPanel { width: 1fr; height: 1fr; layout: vertical; }
    #status-title { text-style: bold; color: $primary; padding: 0 0 1 0; }
    #status-controls { height: auto; }
    #status-controls Select { width: 30; }
    #status-log { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Static("Server Status", id="status-title")
        configs = list_configs(get_config_dir())
        options = [(cfg.name, cfg.name) for cfg in configs]
        with Horizontal(id="status-controls"):
            yield Select(options, id="status-select", prompt="Select project")
            yield Button("Check", id="btn-check", variant="primary", classes="toolbar-btn")
        yield RichLog(id="status-log", wrap=True, highlight=True, markup=True)

    @on(Button.Pressed, "#btn-check")
    def handle_check(self, event: Button.Pressed) -> None:
        logger.debug("handle_check fired")
        select = self.query_one("#status-select", Select)
        if select.value == Select.NULL:
            logger.debug("handle_check: no project selected")
            self.app.notify("Select a project first", severity="warning")
            return
        logger.debug("handle_check: starting check for %s", select.value)
        self._run_check(str(select.value))

    def _get_status_log(self) -> RichLog:
        return self.query_one("#status-log", RichLog)

    @work(thread=True)
    def _run_check(self, project_name: str) -> None:
        import shlex
        from pathlib import Path

        logger.info("TUI status check started: project=%s", project_name)
        log = self.app.call_from_thread(self._get_status_log)
        self.app.call_from_thread(log.clear)
        self.app.call_from_thread(log.write, f"[bold]Checking {project_name}...[/bold]")

        configs = list_configs(get_config_dir())
        config = next((c for c in configs if c.name == project_name), None)
        if not config:
            self.app.call_from_thread(log.write, "[red]Config not found[/red]")
            return

        try:
            ssh = SSHRunner(
                host=config.ssh_host,
                user=config.ssh_user,
                key_path=config.ssh_key,
                sudo=config.sudo,
                port=config.ssh_port,
            )
        except FileNotFoundError as e:
            self.app.call_from_thread(log.write, f"[red]SSH key error: {e}[/red]")
            return

        def out(line):
            self.app.call_from_thread(log.write, line)

        # Uptime
        r = ssh.run("uptime -p", sudo=False)
        if r.ok:
            out(f"Uptime: {r.stdout.strip()}")

        # Reboot required
        r = ssh.run("cat /var/run/reboot-required 2>/dev/null || echo 'No reboot required'", sudo=False)
        if r.ok:
            msg = r.stdout.strip()
            if "restart required" in msg.lower():
                out(f"[yellow]Reboot: {msg}[/yellow]")
            else:
                out(f"Reboot: {msg}")

        # Disk
        r = ssh.run(f"df -h {shlex.quote(str(config.project_dir))} | tail -1")
        if r.ok:
            out(f"Disk: {r.stdout.strip()}")

        # Git
        dir_q = shlex.quote(str(config.project_dir))
        inner = (
            f"grep -q bitbucket.org ~/.ssh/known_hosts 2>/dev/null"
            f" || ssh-keyscan -t ed25519 bitbucket.org >> ~/.ssh/known_hosts 2>/dev/null; "
            f"cd {dir_q} && git -c safe.directory={dir_q} log --oneline -1"
        )
        r = ssh.run(f"bash -c {shlex.quote(inner)}")
        if r.ok:
            out(f"Git: {r.stdout.strip()}")

        # Docker
        r = ssh.run("docker info --format '{{.ServerVersion}}'")
        if r.ok:
            out(f"Docker: {r.stdout.strip()}")

        # Containers
        out("")
        out("[bold]Containers:[/bold]")
        r = ssh.run('docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"')
        if r.ok and r.stdout.strip():
            for line in r.stdout.strip().splitlines():
                if "(healthy)" in line:
                    out(f"  [green]{line}[/green]")
                elif "(unhealthy)" in line:
                    out(f"  [red]{line}[/red]")
                else:
                    out(f"  {line}")
        else:
            out("  [yellow]No containers running[/yellow]")

        # Backups
        out("")
        out("[bold]Recent backups:[/bold]")
        inner = f"ls -1t {shlex.quote(str(config.backup_dir))}/*.tar.gz 2>/dev/null | head -5"
        r = ssh.run(f"bash -c {shlex.quote(inner)}")
        if r.ok and r.stdout.strip():
            for line in r.stdout.strip().splitlines():
                out(f"  {Path(line.strip()).name}")
        else:
            out("  [yellow]None found[/yellow]")

        # Memory & Swap
        out("")
        out("[bold]Memory:[/bold]")
        r = ssh.run("free -h")
        if r.ok:
            for line in r.stdout.strip().splitlines():
                out(f"  {line}")

        # Top Processes by CPU
        out("")
        out("[bold]Top Processes (CPU):[/bold]")
        r = ssh.run("ps aux --sort=-%cpu | head -6")
        if r.ok:
            for line in r.stdout.strip().splitlines():
                out(f"  {line}")

        # Container Resource Usage
        out("")
        out("[bold]Container Resources:[/bold]")
        r = ssh.run('docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}"')
        if r.ok:
            for line in r.stdout.strip().splitlines():
                out(f"  {line}")

        # Disk Usage Breakdown
        out("")
        out("[bold]Disk Usage Breakdown:[/bold]")
        for d in ["/var/log", "/var/cache", "/tmp", str(config.project_dir)]:  # nosec B108
            r = ssh.run(f"du -sh {shlex.quote(d)} 2>/dev/null")
            if r.ok and r.stdout.strip():
                out(f"  {r.stdout.strip()}")

        out("")
        out("[green]Status check complete.[/green]")
        logger.info("TUI status check finished: project=%s", project_name)
