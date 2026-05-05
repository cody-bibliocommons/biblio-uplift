from __future__ import annotations

import logging

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Button, DataTable, Select, Static

from biblio_uplift.config.loader import get_config_dir, list_configs
from biblio_uplift.history.audit import read_history

logger = logging.getLogger(__name__)


class HistoryPanel(Widget):
    DEFAULT_CSS = """
    HistoryPanel { width: 1fr; height: 1fr; layout: vertical; }
    #history-title { text-style: bold; color: $primary; padding: 0 0 1 0; }
    #history-controls { height: auto; }
    #history-controls Select { width: 30; }
    #history-table { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Static("Upgrade History", id="history-title")
        configs = list_configs(get_config_dir())
        options = [("All Projects", "all")] + [(cfg.name, cfg.name) for cfg in configs]
        with Horizontal(id="history-controls"):
            yield Select(options, id="history-filter", value="all")
            yield Button("Refresh", id="btn-refresh-history", variant="default", classes="toolbar-btn")
        yield DataTable(id="history-table")

    def on_mount(self) -> None:
        self._refresh()

    @on(Button.Pressed, "#btn-refresh-history")
    def handle_refresh(self, event: Button.Pressed) -> None:
        logger.debug("handle_refresh fired")
        self._refresh()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "history-filter":
            self._refresh()

    def _refresh(self) -> None:
        table = self.query_one("#history-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Timestamp", "Project", "Pipeline", "Result", "Dry Run", "Duration")

        select = self.query_one("#history-filter", Select)
        project = None if select.value == "all" else str(select.value)

        entries = read_history(project=project, last=50)
        for entry in reversed(entries):
            result = "\u2705" if entry.get("success") else "\u274c"
            dry = "Yes" if entry.get("dry_run") else ""
            duration = f"{entry.get('duration_seconds', 0):.0f}s"
            ts = entry.get("timestamp", "")[:19]
            table.add_row(ts, entry.get("project", ""), entry.get("pipeline", ""), result, dry, duration)
