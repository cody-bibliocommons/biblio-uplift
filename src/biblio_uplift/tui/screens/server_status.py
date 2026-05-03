from __future__ import annotations

import logging

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Button, RichLog, Select, Static

from biblio_uplift.config.loader import get_config_dir, list_configs
from biblio_uplift.core.ssh import SSHRunner

logger = logging.getLogger(__name__)


class ServerStatusPanel(Widget):
    DEFAULT_CSS = """
    ServerStatusPanel { width: 1fr; height: 1fr; padding: 1; }
    #status-title { text-style: bold; color: $primary; padding: 0 0 1 0; }
    #status-select { width: 40; margin: 0 0 1 0; }
    #status-log { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Static("Server Status", id="status-title")
        configs = list_configs(get_config_dir())
        options = [(cfg.name, cfg.name) for cfg in configs]
        with Horizontal():
            yield Select(options, id="status-select", prompt="Select project")
            yield Button("Check", id="btn-check", variant="primary")
        yield RichLog(id="status-log", wrap=True, highlight=True, markup=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-check":
            select = self.query_one("#status-select", Select)
            if select.value == Select.BLANK:
                self.app.notify("Select a project first", severity="warning")
                return
            self._run_check(str(select.value))

    @work(thread=True)
    def _run_check(self, project_name: str) -> None:
        import shlex
        from pathlib import Path

        log = self.query_one("#status-log", RichLog)
        self.call_from_thread(log.clear)
        self.call_from_thread(log.write, f"[bold]Checking {project_name}...[/bold]")

        configs = list_configs(get_config_dir())
        config = next((c for c in configs if c.name == project_name), None)
        if not config:
            self.call_from_thread(log.write, "[red]Config not found[/red]")
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
            self.call_from_thread(log.write, f"[red]SSH key error: {e}[/red]")
            return

        def out(line):
            self.call_from_thread(log.write, line)

        # Uptime
        r = ssh.run("uptime -p")
        if r.ok:
            out(f"Uptime: {r.stdout.strip()}")

        # Reboot required
        r = ssh.run("cat /var/run/reboot-required 2>/dev/null || echo 'No reboot required'")
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
        r = ssh.run(f"cd {shlex.quote(str(config.project_dir))} && git log --oneline -1")
        if r.ok:
            out(f"Git: {r.stdout.strip()}")

        # Docker
        r = ssh.run("docker info --format '{{.ServerVersion}}'")
        if r.ok:
            out(f"Docker: {r.stdout.strip()}")

        # Containers
        out("")
        out("[bold]Containers:[/bold]")
        from biblio_uplift.core.steps.docker import _compose_cmd

        r = ssh.run(f"{_compose_cmd(config)} ps --format 'table {{{{.Name}}}}\t{{{{.Status}}}}\t{{{{.Image}}}}'")
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
        r = ssh.run(f"ls -1t {shlex.quote(str(config.backup_dir))}/*.tar.gz 2>/dev/null | head -5")
        if r.ok and r.stdout.strip():
            for line in r.stdout.strip().splitlines():
                out(f"  {Path(line.strip()).name}")
        else:
            out("  [yellow]None found[/yellow]")

        out("")
        out("[green]Status check complete.[/green]")
