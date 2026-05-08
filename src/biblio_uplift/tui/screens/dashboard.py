from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Button, DataTable, Static

from biblio_uplift.config.loader import get_config_dir, list_configs
from biblio_uplift.history.audit import get_analytics, read_history

logger = logging.getLogger(__name__)


class DashboardPanel(Widget):
    DEFAULT_CSS = """
    DashboardPanel { width: 1fr; height: 1fr; layout: vertical; padding: 1; }
    #dash-title { text-style: bold; color: $primary; padding: 0 0 1 0; }
    #dash-stats { height: auto; layout: horizontal; padding: 0 0 1 0; }
    .stat-box { width: 1fr; border: solid $primary-darken-2; padding: 1; margin: 0 1 0 0; }
    .stat-box Static { text-align: center; }
    #dash-table { height: 1fr; }
    #dash-analytics-summary { height: auto; padding: 0 0 1 0; }
    #dash-activity { height: auto; padding: 1 0 0 0; }
    .dash-actions { height: auto; padding: 1 0; }
    """

    def compose(self) -> ComposeResult:
        yield Static("Dashboard", id="dash-title")
        with Horizontal(id="dash-stats"):
            yield Static("", id="stat-projects", classes="stat-box")
            yield Static("", id="stat-runs", classes="stat-box")
            yield Static("", id="stat-alerts", classes="stat-box")
        yield Static("", id="dash-analytics-summary")
        yield DataTable(id="dash-table")
        yield Static("", id="dash-activity")
        with Horizontal(classes="dash-actions"):
            yield Button("Refresh", id="btn-refresh", variant="default")

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        configs = list_configs(get_config_dir())
        history = read_history(last=50)

        try:
            analytics = get_analytics(days=30)
        except Exception:
            analytics = {}

        # Stats
        total_projects = len(configs)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        recent_runs = [h for h in history if h.get("timestamp", "") > cutoff]
        fail_count = sum(1 for h in recent_runs if not h.get("success"))

        self.query_one("#stat-projects", Static).update(f"[bold]{total_projects}[/bold]\nProjects")
        self.query_one("#stat-runs", Static).update(f"[bold]{len(recent_runs)}[/bold]\nRuns (24h)")
        color = "red" if fail_count > 0 else "green"
        self.query_one("#stat-alerts", Static).update(f"[bold {color}]{fail_count}[/bold {color}]\nFailed (24h)")

        # Analytics summary (30d)
        if analytics:
            total_runs = analytics.get("total_runs", 0)
            success_rate = analytics.get("success_rate", 0.0)
            avg_dur = analytics.get("avg_duration", 0.0)
            summary = (
                f"[bold]30-Day Summary:[/bold]  "
                f"Runs: {total_runs}  |  "
                f"Success rate: {success_rate:.1f}%  |  "
                f"Avg duration: {avg_dur:.1f}s"
            )
            self.query_one("#dash-analytics-summary", Static).update(summary)
        else:
            self.query_one("#dash-analytics-summary", Static).update("")

        # Build failure rate lookup from analytics
        failure_by_project: dict[str, dict] = {}
        for entry in analytics.get("failure_rate_by_project", []):
            failure_by_project[entry["project"]] = entry

        # Table
        table = self.query_one("#dash-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Project", "Host", "Last Run", "Result", "Duration", "Avg Dur (30d)", "Fail % (30d)")

        for cfg in configs:
            proj_history = [h for h in history if h.get("project") == cfg.name]
            if proj_history:
                entry = proj_history[-1]
                ts = entry.get("timestamp", "")[:16].replace("T", " ")
                result = "\u2705" if entry.get("success") else "\u274c"
                duration = f"{entry.get('duration_seconds', 0):.0f}s"
            else:
                ts = "Never"
                result = "\u2014"
                duration = "\u2014"

            proj_stats = failure_by_project.get(cfg.name)
            if proj_stats:
                avg_dur_col = f"{proj_stats.get('avg_duration', 0):.0f}s" if "avg_duration" in proj_stats else "\u2014"
                fail_pct = f"{proj_stats['pct']:.1f}%"
            else:
                avg_dur_col = "\u2014"
                fail_pct = "\u2014"

            table.add_row(cfg.name, cfg.ssh_host, ts, result, duration, avg_dur_col, fail_pct)

        # Recent activity
        recent = history[-5:]
        if recent:
            lines = ["[bold]Recent Activity:[/bold]"]
            for entry in reversed(recent):
                icon = "\u2705" if entry.get("success") else "\u274c"
                ts = entry.get("timestamp", "")[:16].replace("T", " ")
                proj = entry.get("project", "?")
                lines.append(f"  {icon} {ts} {proj}")
            self.query_one("#dash-activity", Static).update("\n".join(lines))
        else:
            self.query_one("#dash-activity", Static).update("")

    @on(Button.Pressed, "#btn-refresh")
    def handle_refresh(self, event: Button.Pressed) -> None:
        logger.debug("handle_refresh fired")
        self._refresh()
