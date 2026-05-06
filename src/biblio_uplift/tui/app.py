import logging

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import ContentSwitcher, Footer, Header
from textual.worker import Worker, WorkerState

from biblio_uplift.tui.widgets.sidebar import Sidebar

logger = logging.getLogger(__name__)

SECTIONS = [
    ("dashboard", "Dashboard"),
    ("upgrade", "Upgrade"),
    ("cleanup", "Cleanup"),
    ("status", "Server Status"),
    ("backups", "Backups"),
    ("config", "Config Editor"),
    ("history", "History"),
    ("tools", "Tools"),
    ("about", "About"),
]


class UpgradeApp(App):
    """Biblio Uplift TUI."""

    TITLE = "Biblio Uplift"
    CSS_PATH = "css/app.tcss"
    BINDINGS = [
        Binding("q", "quit", "Quit", show=True, priority=True),
        Binding("1", "switch_section('dashboard')", "Dashboard", show=False),
        Binding("2", "switch_section('upgrade')", "Upgrade", show=False),
        Binding("3", "switch_section('cleanup')", "Cleanup", show=False),
        Binding("4", "switch_section('status')", "Status", show=False),
        Binding("5", "switch_section('backups')", "Backups", show=False),
        Binding("6", "switch_section('config')", "Config", show=False),
        Binding("7", "switch_section('history')", "History", show=False),
        Binding("8", "switch_section('tools')", "Tools", show=False),
        Binding("9", "switch_section('about')", "About", show=False),
    ]

    def __init__(self, debug: bool = False, **kwargs):
        super().__init__(**kwargs)
        self._debug = debug

    def on_mount(self) -> None:
        if not logging.getLogger().handlers:
            from biblio_uplift.cli.main import setup_logging

            setup_logging(debug=self._debug)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="app-layout"):
            yield Sidebar(items=SECTIONS, title="Biblio Uplift", id="sidebar")
            with ContentSwitcher(id="content-switcher", initial="dashboard"):
                from biblio_uplift.tui.screens.about import AboutPanel
                from biblio_uplift.tui.screens.backups import BackupsPanel
                from biblio_uplift.tui.screens.cleanup import CleanupPanel
                from biblio_uplift.tui.screens.config_edit import ConfigPanel
                from biblio_uplift.tui.screens.dashboard import DashboardPanel
                from biblio_uplift.tui.screens.history import HistoryPanel
                from biblio_uplift.tui.screens.server_status import ServerStatusPanel
                from biblio_uplift.tui.screens.tools import ToolsPanel
                from biblio_uplift.tui.screens.upgrade import UpgradePanel

                yield DashboardPanel(id="dashboard")
                yield UpgradePanel(id="upgrade")
                yield CleanupPanel(id="cleanup")
                yield ServerStatusPanel(id="status")
                yield BackupsPanel(id="backups")
                yield ConfigPanel(id="config")
                yield HistoryPanel(id="history")
                yield ToolsPanel(id="tools")
                yield AboutPanel(id="about")
        yield Footer()

    def action_switch_section(self, section_id: str) -> None:
        switcher = self.query_one("#content-switcher", ContentSwitcher)
        switcher.current = section_id
        sidebar = self.query_one("#sidebar", Sidebar)
        sidebar.current = section_id

    def on_sidebar_selected(self, event: Sidebar.Selected) -> None:
        self.action_switch_section(event.section_id)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.ERROR:
            error = event.worker.error
            logger.error("Worker '%s' failed: %s", event.worker.name, error, exc_info=error)
            self.notify(f"Background task failed: {error}", severity="error", timeout=10)
