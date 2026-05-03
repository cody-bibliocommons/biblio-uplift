from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Button, DataTable, Static

from biblio_uplift.config.loader import get_config_dir, list_configs
from biblio_uplift.history.audit import read_history


class DashboardPanel(Widget):
    DEFAULT_CSS = """
    DashboardPanel { width: 1fr; height: 1fr; padding: 1; }
    #dash-title { text-style: bold; color: $primary; padding: 0 0 1 0; }
    #dash-table { height: 1fr; }
    .dash-actions { height: auto; padding: 1 0; }
    """

    def compose(self) -> ComposeResult:
        yield Static("Biblio Uplift", id="dash-title")
        yield DataTable(id="dash-table")
        with Horizontal(classes="dash-actions"):
            yield Button("Refresh", id="btn-refresh", variant="default")

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        table = self.query_one("#dash-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Project", "Host", "Last Run", "Result", "Duration")

        configs = list_configs(get_config_dir())
        for cfg in configs:
            history = read_history(project=cfg.name, last=1)
            if history:
                entry = history[-1]
                ts = entry.get("timestamp", "")[:19]
                result = "\u2705" if entry.get("success") else "\u274c"
                duration = f"{entry.get('duration_seconds', 0):.0f}s"
            else:
                ts = "Never"
                result = "\u2014"
                duration = "\u2014"
            table.add_row(cfg.name, cfg.ssh_host, ts, result, duration)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-refresh":
            self._refresh()
