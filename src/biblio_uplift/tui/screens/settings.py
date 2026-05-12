"""Settings panel for the TUI."""

from __future__ import annotations

import logging

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Button, Checkbox, Input, Select, Static

from biblio_uplift.settings import get_available_editors, load_settings, save_settings, sync_config_repo

logger = logging.getLogger(__name__)


class SettingsPanel(Widget):
    DEFAULT_CSS = """
    SettingsPanel { width: 1fr; height: 1fr; layout: vertical; padding: 1; overflow-y: auto; }
    #settings-title { text-style: bold; color: $primary; padding: 0 0 1 0; }
    .settings-label { height: auto; padding: 0; margin: 1 0 0 0; }
    .settings-input { height: auto; }
    #settings-buttons { height: auto; layout: horizontal; margin: 1 0; }
    #settings-buttons Button { margin: 0 1 0 0; }
    #settings-status { height: auto; color: $success; padding: 1 0; }
    #inp-editor-custom { display: none; }
    """

    def compose(self) -> ComposeResult:
        yield Static("Settings", id="settings-title")
        yield Static("Config Repo URL", classes="settings-label")
        yield Input(id="inp-config-repo-url", placeholder="git@host:org/repo.git")
        yield Static("Config Repo SSH Key", classes="settings-label")
        yield Input(id="inp-config-repo-ssh-key", placeholder="~/.ssh/id_ed25519")
        yield Static("Config Repo Branch", classes="settings-label")
        yield Input(id="inp-config-repo-branch", placeholder="main")
        with Vertical(classes="settings-field"):
            yield Static("Config Repo Path (subdirectory)")
            yield Input(value="", id="inp-repo-path", placeholder="configs")
        yield Checkbox("Sync config repo on launch", id="chk-sync-on-launch")
        yield Static("Default SSH Key", classes="settings-label")
        yield Input(id="inp-default-ssh-key", placeholder="~/.ssh/id_ed25519")
        yield Static("Theme", classes="settings-label")
        yield Input(id="inp-theme", placeholder="dark")
        yield Static("Editor", classes="settings-label")
        editors = get_available_editors()
        editor_options = [(f"{name} ({cmd})", cmd) for cmd, name in editors]
        editor_options.append(("Custom...", "__custom__"))
        yield Select(editor_options, id="sel-editor", prompt="Auto-detect")
        yield Input(id="inp-editor-custom", placeholder="/path/to/editor or command")
        yield Static("Analytics Retention (days)", classes="settings-label")
        yield Input(id="inp-analytics-retention-days", placeholder="90")
        yield Static("Default Notification Command", classes="settings-label")
        yield Input(id="inp-default-notification-cmd", placeholder="")
        with Vertical(id="settings-buttons"):
            yield Button("Save", id="btn-save-settings", variant="success")
            yield Button("Sync Now", id="btn-sync-now", variant="primary")
        yield Static("", id="settings-status")

    def on_mount(self) -> None:
        self._load()

    def _load(self) -> None:
        settings = load_settings()
        self.query_one("#inp-config-repo-url", Input).value = str(settings.get("config_repo_url", ""))
        self.query_one("#inp-config-repo-ssh-key", Input).value = str(settings.get("config_repo_ssh_key", ""))
        self.query_one("#inp-config-repo-branch", Input).value = str(settings.get("config_repo_branch", ""))
        self.query_one("#inp-repo-path", Input).value = str(settings.get("config_repo_path", ""))
        self.query_one("#chk-sync-on-launch", Checkbox).value = bool(settings.get("config_sync_on_launch"))
        self.query_one("#inp-default-ssh-key", Input).value = str(settings.get("default_ssh_key", ""))
        self.query_one("#inp-theme", Input).value = str(settings.get("theme", ""))
        editor_val = str(settings.get("editor", ""))
        editors = get_available_editors()
        known_cmds = [cmd for cmd, _ in editors]
        sel_editor = self.query_one("#sel-editor", Select)
        custom_input = self.query_one("#inp-editor-custom", Input)
        if not editor_val:
            sel_editor.value = Select.NULL
            custom_input.styles.display = "none"
        elif editor_val in known_cmds:
            sel_editor.value = editor_val
            custom_input.styles.display = "none"
        else:
            sel_editor.value = "__custom__"
            custom_input.value = editor_val
            custom_input.styles.display = "block"
        self.query_one("#inp-analytics-retention-days", Input).value = str(
            settings.get("analytics_retention_days", "90")
        )
        self.query_one("#inp-default-notification-cmd", Input).value = str(settings.get("default_notification_cmd", ""))

    def _gather(self) -> dict[str, object]:
        retention = self.query_one("#inp-analytics-retention-days", Input).value
        try:
            retention_int = int(retention)
        except ValueError:
            retention_int = 90
        editor_sel = self.query_one("#sel-editor", Select)
        if editor_sel.value == "__custom__":
            editor_val = self.query_one("#inp-editor-custom", Input).value
        elif editor_sel.value == Select.NULL:
            editor_val = ""
        else:
            editor_val = str(editor_sel.value)
        return {
            "config_repo_url": self.query_one("#inp-config-repo-url", Input).value,
            "config_repo_ssh_key": self.query_one("#inp-config-repo-ssh-key", Input).value,
            "config_repo_branch": self.query_one("#inp-config-repo-branch", Input).value,
            "config_repo_path": self.query_one("#inp-repo-path", Input).value,
            "config_sync_on_launch": self.query_one("#chk-sync-on-launch", Checkbox).value,
            "default_ssh_key": self.query_one("#inp-default-ssh-key", Input).value,
            "theme": self.query_one("#inp-theme", Input).value,
            "editor": editor_val,
            "analytics_retention_days": retention_int,
            "default_notification_cmd": self.query_one("#inp-default-notification-cmd", Input).value,
        }

    @on(Button.Pressed, "#btn-save-settings")
    def handle_save(self, event: Button.Pressed) -> None:
        settings = self._gather()
        save_settings(settings)
        self.query_one("#settings-status", Static).update("[green]Settings saved.[/green]")

    @on(Button.Pressed, "#btn-sync-now")
    def handle_sync(self, event: Button.Pressed) -> None:
        self.query_one("#settings-status", Static).update("Syncing...")
        self._do_sync()

    @on(Select.Changed, "#sel-editor")
    def _editor_changed(self, event: Select.Changed) -> None:
        custom_input = self.query_one("#inp-editor-custom", Input)
        if event.value == "__custom__":
            custom_input.styles.display = "block"
            custom_input.focus()
        else:
            custom_input.styles.display = "none"

    @work(thread=True)
    def _do_sync(self) -> None:
        settings = self._gather()
        result = sync_config_repo(settings)
        self.app.call_from_thread(self.query_one("#settings-status", Static).update, result)
        self.app.call_from_thread(self.app.refresh_config_selects)
