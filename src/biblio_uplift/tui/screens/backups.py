from __future__ import annotations

import logging
import shlex
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Button, DataTable, RichLog, Select, Static

from biblio_uplift.config.loader import get_config_dir, list_configs
from biblio_uplift.core.ssh import SSHRunner

logger = logging.getLogger(__name__)


class BackupsPanel(Widget):
    DEFAULT_CSS = """
    BackupsPanel { width: 1fr; height: 1fr; layout: vertical; }
    #backups-title { text-style: bold; color: $primary; padding: 0 0 1 0; }
    #backups-controls { height: auto; }
    #backups-controls Select { width: 30; }
    #backups-table { height: 1fr; }
    #backups-log { height: 8; }
    """

    def compose(self) -> ComposeResult:
        yield Static("Backup Management", id="backups-title")
        configs = list_configs(get_config_dir())
        options = [(cfg.name, cfg.name) for cfg in configs]
        with Horizontal(id="backups-controls"):
            yield Select(options, id="backups-project", prompt="Select project")
            yield Button("List Backups", id="btn-list-backups", variant="primary", classes="toolbar-btn")
            yield Button("Prune Old", id="btn-prune-backups", variant="warning", classes="toolbar-btn")
        yield DataTable(id="backups-table")
        yield RichLog(id="backups-log", wrap=True, highlight=True, markup=True)

    @on(Button.Pressed, "#btn-list-backups")
    def handle_list_backups(self, event: Button.Pressed) -> None:
        logger.debug("handle_list_backups fired")
        select = self.query_one("#backups-project", Select)
        if select.value == Select.NULL:
            logger.debug("handle_list_backups: no project selected")
            self.app.notify("Select a project first", severity="warning")
            return
        logger.debug("handle_list_backups: listing backups for %s", select.value)
        self._list_backups(str(select.value))

    def _get_backups_table(self) -> DataTable:
        return self.query_one("#backups-table", DataTable)

    def _get_backups_log(self) -> RichLog:
        return self.query_one("#backups-log", RichLog)

    @work(thread=True)
    def _list_backups(self, project_name: str) -> None:
        logger.info("TUI backup list started: project=%s", project_name)
        table = self.app.call_from_thread(self._get_backups_table)
        self.app.call_from_thread(table.clear, True)  # clear columns too
        self.app.call_from_thread(table.add_columns, "File", "Size", "Date")

        configs = list_configs(get_config_dir())
        config = next((c for c in configs if c.name == project_name), None)
        if not config:
            return

        try:
            ssh = SSHRunner(
                host=config.ssh_host,
                user=config.ssh_user,
                key_path=config.ssh_key,
                sudo=config.sudo,
                port=config.ssh_port,
            )
        except FileNotFoundError:
            return

        inner = f"ls -lhS {shlex.quote(str(config.backup_dir))}/*.tar.gz 2>/dev/null"
        result = ssh.run(f"bash -c {shlex.quote(inner)}")
        if not result.ok or not result.stdout.strip():
            log = self.app.call_from_thread(self._get_backups_log)
            self.app.call_from_thread(log.write, "No backups found.")
            return

        for line in result.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 9:
                size = parts[4]
                date = " ".join(parts[5:8])
                name = Path(parts[-1]).name
                self.app.call_from_thread(table.add_row, name, size, date)

    @on(Button.Pressed, "#btn-prune-backups")
    def handle_prune(self, event: Button.Pressed) -> None:
        select = self.query_one("#backups-project", Select)
        if select.value == Select.NULL:
            self.app.notify("Select a project first", severity="warning")
            return
        self._prune_backups(str(select.value))

    @work(thread=True)
    def _prune_backups(self, project_name: str) -> None:
        import re

        output_lines: list[str] = []
        try:
            configs = list_configs(get_config_dir())
            config = next((c for c in configs if c.name == project_name), None)
            if not config:
                output_lines.append("[red]Config not found[/red]")
                self.app.call_from_thread(self._write_output, output_lines)
                return

            ssh = SSHRunner(
                host=config.ssh_host,
                user=config.ssh_user,
                key_path=config.ssh_key,
                sudo=config.sudo,
                port=config.ssh_port,
            )
            backup_dir = str(config.backup_dir)
            retention = config.backup_retention

            inner = f"ls -1 {shlex.quote(backup_dir)}/*.tar.gz 2>/dev/null"
            result = ssh.run(f"bash -c {shlex.quote(inner)}")
            if not result.ok or not result.stdout.strip():
                output_lines.append("No backups found.")
                self.app.call_from_thread(self._write_output, output_lines)
                return

            files = [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]

            # Extract timestamps and group files by timestamp
            ts_pattern = re.compile(r"_(\d{8}_\d{6})\.tar\.gz$")
            groups: dict[str, list[str]] = {}
            for f in files:
                match = ts_pattern.search(f)
                if match:
                    ts = match.group(1)
                    groups.setdefault(ts, []).append(f)

            sorted_ts = sorted(groups.keys(), reverse=True)
            output_lines.append(f"Found {len(sorted_ts)} backup sets ({len(files)} files, keeping {retention})")

            if len(sorted_ts) <= retention:
                output_lines.append(f"Nothing to prune ({len(sorted_ts)} sets <= {retention})")
                self.app.call_from_thread(self._write_output, output_lines)
                return

            to_remove_ts = sorted_ts[retention:]
            to_remove_files = [f for ts in to_remove_ts for f in groups[ts]]
            output_lines.append(f"Removing {len(to_remove_ts)} old backup sets ({len(to_remove_files)} files)...")
            for ts in to_remove_ts:
                for f in groups[ts]:
                    r = ssh.run(f"rm -f {shlex.quote(f)}")
                    if r.ok:
                        output_lines.append(f"  Removed: {Path(f).name}")
                    else:
                        output_lines.append(f"  [red]Failed: {Path(f).name}[/red]")

            output_lines.append("[green]Prune complete.[/green]")
        except Exception as e:
            output_lines.append(f"[red]Error: {e}[/red]")
        finally:
            self.app.call_from_thread(self._write_output, output_lines)

    def _write_output(self, lines: list[str]) -> None:
        """Write output lines to the log widget. Must be called from main thread."""
        try:
            log = self.query_one("#backups-log", RichLog)
            log.clear()
            for line in lines:
                log.write(line)
        except Exception as e:
            logger.error("Failed to write output: %s", e)
