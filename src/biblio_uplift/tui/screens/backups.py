from __future__ import annotations

import logging
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Button, DataTable, RichLog, Select, Static

from biblio_uplift.config.loader import get_config_dir, list_configs
from biblio_uplift.core.ssh import SSHRunner

logger = logging.getLogger(__name__)


class BackupsPanel(Widget):
    DEFAULT_CSS = """
    BackupsPanel { width: 1fr; height: 1fr; padding: 1; layout: vertical; }
    #backups-title { text-style: bold; color: $primary; padding: 0 0 1 0; }
    #backups-table { height: 1fr; }
    #backups-log { height: 10; }
    """

    def compose(self) -> ComposeResult:
        yield Static("Backup Management", id="backups-title")
        configs = list_configs(get_config_dir())
        options = [(cfg.name, cfg.name) for cfg in configs]
        with Horizontal():
            yield Select(options, id="backups-project", prompt="Select project")
            yield Button("List Backups", id="btn-list-backups", variant="primary")
        yield DataTable(id="backups-table")
        yield RichLog(id="backups-log", wrap=True, highlight=True, markup=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-list-backups":
            select = self.query_one("#backups-project", Select)
            if select.value == Select.BLANK:
                self.app.notify("Select a project first", severity="warning")
                return
            self._list_backups(str(select.value))

    @work(thread=True)
    def _list_backups(self, project_name: str) -> None:
        import shlex

        table = self.query_one("#backups-table", DataTable)
        self.call_from_thread(table.clear, True)  # clear columns too
        self.call_from_thread(table.add_columns, "File", "Size", "Date")

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

        result = ssh.run(f"ls -lhS {shlex.quote(str(config.backup_dir))}/*.tar.gz 2>/dev/null")
        if not result.ok or not result.stdout.strip():
            log = self.query_one("#backups-log", RichLog)
            self.call_from_thread(log.write, "No backups found.")
            return

        for line in result.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 9:
                size = parts[4]
                date = " ".join(parts[5:8])
                name = Path(parts[-1]).name
                self.call_from_thread(table.add_row, name, size, date)
