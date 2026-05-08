from __future__ import annotations

import logging

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widget import Widget
from textual.widgets import (
    Button,
    Collapsible,
    Input,
    Label,
    Select,
    Static,
    Switch,
    TextArea,
)

from biblio_uplift.config.loader import (
    get_config_dir,
    list_configs,
    load_config,
    save_config,
)
from biblio_uplift.config.schema import CleanupConfig, ProjectConfig

logger = logging.getLogger(__name__)


class ConfigPanel(Widget):
    DEFAULT_CSS = """
    ConfigPanel { width: 1fr; height: 1fr; layout: vertical; }
    #config-title { text-style: bold; color: $primary; padding: 0 0 1 0; }
    #config-controls { height: auto; }
    #config-controls Select { width: 30; }
    #config-form { height: 1fr; }
    ConfigPanel Input { margin: 0 0 1 0; }
    ConfigPanel Label { margin: 1 0 0 0; text-style: bold; }
    ConfigPanel Switch { margin: 0 0 0 1; }
    ConfigPanel TextArea { height: 4; margin: 0 0 1 0; }
    ConfigPanel Collapsible { margin: 1 0; border: solid $primary-darken-2; }
    .form-section { text-style: bold; color: $warning; margin: 1 0 0 0; border-bottom: solid $primary-darken-2; padding: 0 0 1 0; }
    .switch-row { height: auto; align: left middle; }
    .switch-row Label { width: 20; margin: 0; }
    .switch-row Switch { margin: 0; }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._current_config: ProjectConfig | None = None
        self._is_new = False
        self._editor_warned = False

    def compose(self) -> ComposeResult:
        yield Static("Configuration Editor", id="config-title")
        configs = list_configs(get_config_dir())
        options = [(cfg.name, cfg.name) for cfg in configs]
        with Horizontal(id="config-controls"):
            yield Select(options, id="config-select", prompt="Select project")
            yield Button("Load", id="btn-load-config", variant="primary", classes="toolbar-btn")
            yield Button("New", id="btn-new-config", variant="warning", classes="toolbar-btn")
            yield Button("Save", id="btn-save-config", variant="success", disabled=True, classes="toolbar-btn")
            yield Button("Delete", id="btn-delete-config", variant="error", disabled=True, classes="toolbar-btn")
            yield Button(
                "Open in Editor", id="btn-open-editor", variant="default", disabled=True, classes="toolbar-btn"
            )

        with VerticalScroll(id="config-form"):
            # -- Core --
            yield Static("Core Settings", classes="form-section")
            yield Label("Project Name")
            yield Input(id="cfg-name", placeholder="itops-myproject")
            yield Label("SSH Host")
            yield Input(id="cfg-ssh_host", placeholder="server.example.com")
            yield Label("SSH User")
            yield Input(id="cfg-ssh_user", placeholder="ansible", value="ansible")
            yield Label("SSH Key")
            yield Input(id="cfg-ssh_key", placeholder="~/.ssh/integration.pem", value="~/.ssh/integration.pem")
            yield Label("Project Dir")
            yield Input(id="cfg-project_dir", placeholder="/opt/docker/itops-project")
            yield Label("Compose Files (comma-separated)")
            yield Input(id="cfg-compose_files", placeholder="docker-compose.yml", value="docker-compose.yml")

            # -- Backup --
            yield Static("Backup Settings", classes="form-section")
            yield Label("Backup Dir")
            yield Input(id="cfg-backup_dir", placeholder="/var/backups/itops/project")
            yield Label("Backup Retention")
            yield Input(id="cfg-backup_retention", placeholder="5", value="5")
            yield Label("Volumes (comma-separated)")
            yield Input(id="cfg-volumes", placeholder="vol_data, vol_db")
            yield Label("Extra Backup Paths (comma-separated)")
            yield Input(id="cfg-extra_backup_paths", placeholder="/opt/docker/project/.env, /opt/docker/project/ssl")

            # -- Health --
            yield Static("Health Check", classes="form-section")
            yield Label("Healthcheck URLs (comma-separated)")
            yield Input(id="cfg-healthcheck_urls", placeholder="https://server.example.com")
            yield Label("Healthcheck Timeout (seconds)")
            yield Input(id="cfg-healthcheck_timeout", placeholder="120", value="120")

            # -- Toggles --
            yield Static("Default Behavior", classes="form-section")
            with Horizontal(classes="switch-row"):
                yield Label("Sudo")
                yield Switch(id="cfg-sudo", value=True)
            with Horizontal(classes="switch-row"):
                yield Label("Skip OS Update")
                yield Switch(id="cfg-skip_os_update")
            with Horizontal(classes="switch-row"):
                yield Label("Skip Reboot")
                yield Switch(id="cfg-skip_reboot")

            # -- Advanced (collapsible) --
            with Collapsible(title="Advanced Settings", collapsed=True):
                yield Label("SSH Port")
                yield Input(id="cfg-ssh_port", placeholder="22", value="22")
                yield Label("Compose Command")
                yield Input(id="cfg-compose_command", placeholder="docker compose", value="docker compose")
                yield Label("Compose Profile")
                yield Input(id="cfg-compose_profile", placeholder="hostname or blank")
                yield Label("Git Branch (blank = auto-detect)")
                yield Input(id="cfg-git_branch", placeholder="main")
                yield Label("Reboot Timeout (seconds)")
                yield Input(id="cfg-reboot_timeout", placeholder="300", value="300")
                yield Label("APT Timeout (seconds)")
                yield Input(id="cfg-apt_timeout", placeholder="600", value="600")
                yield Label("Maintenance Window (e.g. 02:00-06:00)")
                yield Input(id="cfg-maintenance_window", placeholder="blank = anytime")

            # -- Notifications (collapsible) --
            with Collapsible(title="Notifications & Hooks", collapsed=True):
                yield Label("On Failure Command (runs locally)")
                yield Input(id="cfg-on_failure_cmd", placeholder="curl -X POST https://hooks.slack.com/...")
                yield Label("On Success Command (runs locally)")
                yield Input(id="cfg-on_success_cmd", placeholder="curl -X POST https://hooks.slack.com/...")
                yield Label("Pre-Upgrade Hooks (one per line, runs on remote)")
                yield TextArea(id="cfg-pre_upgrade_hooks")
                yield Label("Post-Upgrade Hooks (one per line, runs on remote)")
                yield TextArea(id="cfg-post_upgrade_hooks")

            # -- Cleanup (collapsible) --
            with Collapsible(title="Cleanup Settings", collapsed=True):
                with Horizontal(classes="switch-row"):
                    yield Label("Prune Images")
                    yield Switch(id="cfg-prune_images", value=True)
                with Horizontal(classes="switch-row"):
                    yield Label("Prune Containers")
                    yield Switch(id="cfg-prune_containers", value=True)
                with Horizontal(classes="switch-row"):
                    yield Label("Prune Volumes")
                    yield Switch(id="cfg-prune_volumes")
                with Horizontal(classes="switch-row"):
                    yield Label("Prune Build Cache")
                    yield Switch(id="cfg-prune_build_cache", value=True)
                yield Label("Log Retention (days)")
                yield Input(id="cfg-log_retention_days", placeholder="30", value="30")
                yield Label("Log Paths to Truncate (comma-separated)")
                yield Input(id="cfg-log_paths", placeholder="/var/log/app.log")

    @on(Button.Pressed, "#btn-load-config")
    def handle_load(self, event: Button.Pressed) -> None:
        logger.debug("handle_load fired")
        select = self.query_one("#config-select", Select)
        if select.value == Select.NULL:
            self.app.notify("Select a project", severity="warning")
            return
        self._load_config(str(select.value))

    @on(Button.Pressed, "#btn-new-config")
    def handle_new(self, event: Button.Pressed) -> None:
        logger.debug("handle_new fired")
        self._new_config()

    @on(Button.Pressed, "#btn-save-config")
    def handle_save(self, event: Button.Pressed) -> None:
        logger.debug("handle_save fired")
        self._save_config()

    @on(Button.Pressed, "#btn-delete-config")
    def handle_delete(self, event: Button.Pressed) -> None:
        logger.debug("handle_delete fired")
        self._delete_config()

    @on(Button.Pressed, "#btn-open-editor")
    def _open_in_editor(self, event: Button.Pressed) -> None:
        """Open current config in external editor, refresh on return."""
        import os

        select = self.query_one("#config-select", Select)
        if select.value == Select.NULL:
            return

        from biblio_uplift.settings import load_settings

        settings = load_settings()
        has_editor = settings.get("editor") or os.environ.get("EDITOR") or os.environ.get("VISUAL")

        if not has_editor and not self._editor_warned:
            self._editor_warned = True
            from biblio_uplift.settings import detect_editor

            detected = detect_editor()
            self.app.notify(
                f"No editor configured. Detected [bold]{detected}[/bold].\n"
                f"Press again to use it, or set one in [bold]Settings[/bold] (key 0).",
                severity="warning",
                timeout=8,
            )
            return

        self._launch_editor(str(select.value))

    @work(thread=True)
    def _launch_editor(self, project_name: str) -> None:
        import shlex
        import shutil
        import subprocess

        from biblio_uplift.settings import detect_editor, load_settings

        settings = load_settings()
        editor = detect_editor(settings)
        config_dir = get_config_dir()
        config_path = None
        for p in config_dir.glob("*.yml"):
            try:
                cfg = load_config(p)
                if cfg.name == project_name:
                    config_path = p
                    break
            except Exception:  # noqa: S112
                continue
        if not config_path:
            return

        if not shutil.which(shlex.split(editor)[0]):
            self.app.call_from_thread(
                self.app.notify,
                f"Editor not found: {editor.split()[0]}",
                severity="error",
            )
            return

        cmd = shlex.split(editor) + [str(config_path)]
        with self.app.suspend():
            subprocess.call(cmd)  # noqa: S603

        self.app.call_from_thread(self._reload_config, project_name)

    def _reload_config(self, project_name: str) -> None:
        """Reload the config into the form after external edit."""
        select = self.query_one("#config-select", Select)
        select.value = project_name
        self._load_config(project_name)

    def _new_config(self) -> None:
        """Clear form for a new config."""
        self._current_config = None
        self._is_new = True
        # Clear all inputs
        for inp in self.query(Input):
            if inp.id and inp.id.startswith("cfg-"):
                field = inp.id.removeprefix("cfg-")
                # Keep defaults for some fields
                defaults = {
                    "ssh_user": "ansible",
                    "ssh_key": "~/.ssh/integration.pem",
                    "ssh_port": "22",
                    "compose_files": "docker-compose.yml",
                    "compose_command": "docker compose",
                    "backup_retention": "5",
                    "healthcheck_timeout": "120",
                    "reboot_timeout": "300",
                    "apt_timeout": "600",
                    "log_retention_days": "30",
                }
                inp.value = defaults.get(field, "")
        # Clear switches to defaults
        self.query_one("#cfg-sudo", Switch).value = True
        self.query_one("#cfg-skip_os_update", Switch).value = False
        self.query_one("#cfg-skip_reboot", Switch).value = False
        self.query_one("#cfg-prune_images", Switch).value = True
        self.query_one("#cfg-prune_containers", Switch).value = True
        self.query_one("#cfg-prune_volumes", Switch).value = False
        self.query_one("#cfg-prune_build_cache", Switch).value = True
        # Clear text areas
        self.query_one("#cfg-pre_upgrade_hooks", TextArea).clear()
        self.query_one("#cfg-post_upgrade_hooks", TextArea).clear()
        # Enable save, enable name field
        self.query_one("#btn-save-config", Button).disabled = False
        self.query_one("#btn-delete-config", Button).disabled = True
        self.query_one("#cfg-name", Input).disabled = False
        self.app.notify("New config - fill in the fields and save")

    def _load_config(self, name: str) -> None:
        path = get_config_dir() / f"{name}.yml"
        try:
            config = load_config(path)
        except Exception as e:
            self.app.notify(f"Error: {e}", severity="error")
            return
        self._current_config = config
        self._is_new = False
        c = config

        # Core
        self.query_one("#cfg-name", Input).value = c.name
        self.query_one("#cfg-name", Input).disabled = True  # can't rename
        self.query_one("#cfg-ssh_host", Input).value = c.ssh_host
        self.query_one("#cfg-ssh_user", Input).value = c.ssh_user
        self.query_one("#cfg-ssh_key", Input).value = str(c.ssh_key)
        self.query_one("#cfg-project_dir", Input).value = str(c.project_dir)
        self.query_one("#cfg-compose_files", Input).value = ", ".join(c.compose_files)

        # Backup
        self.query_one("#cfg-backup_dir", Input).value = str(c.backup_dir)
        self.query_one("#cfg-backup_retention", Input).value = str(c.backup_retention)
        self.query_one("#cfg-volumes", Input).value = ", ".join(c.volumes)
        self.query_one("#cfg-extra_backup_paths", Input).value = ", ".join(c.extra_backup_paths)

        # Health
        self.query_one("#cfg-healthcheck_urls", Input).value = ", ".join(c.healthcheck_urls)
        self.query_one("#cfg-healthcheck_timeout", Input).value = str(c.healthcheck_timeout)

        # Toggles
        self.query_one("#cfg-sudo", Switch).value = c.sudo
        self.query_one("#cfg-skip_os_update", Switch).value = c.skip_os_update
        self.query_one("#cfg-skip_reboot", Switch).value = c.skip_reboot

        # Advanced
        self.query_one("#cfg-ssh_port", Input).value = str(c.ssh_port)
        self.query_one("#cfg-compose_command", Input).value = c.compose_command
        self.query_one("#cfg-compose_profile", Input).value = c.compose_profile or ""
        self.query_one("#cfg-git_branch", Input).value = c.git_branch or ""
        self.query_one("#cfg-reboot_timeout", Input).value = str(c.reboot_timeout)
        self.query_one("#cfg-apt_timeout", Input).value = str(c.apt_timeout)
        self.query_one("#cfg-maintenance_window", Input).value = c.maintenance_window or ""

        # Notifications
        self.query_one("#cfg-on_failure_cmd", Input).value = c.on_failure_cmd or ""
        self.query_one("#cfg-on_success_cmd", Input).value = c.on_success_cmd or ""
        self.query_one("#cfg-pre_upgrade_hooks", TextArea).clear()
        if c.pre_upgrade_hooks:
            self.query_one("#cfg-pre_upgrade_hooks", TextArea).insert("\n".join(c.pre_upgrade_hooks))
        self.query_one("#cfg-post_upgrade_hooks", TextArea).clear()
        if c.post_upgrade_hooks:
            self.query_one("#cfg-post_upgrade_hooks", TextArea).insert("\n".join(c.post_upgrade_hooks))

        # Cleanup
        self.query_one("#cfg-prune_images", Switch).value = c.cleanup.prune_images
        self.query_one("#cfg-prune_containers", Switch).value = c.cleanup.prune_containers
        self.query_one("#cfg-prune_volumes", Switch).value = c.cleanup.prune_volumes
        self.query_one("#cfg-prune_build_cache", Switch).value = c.cleanup.prune_build_cache
        self.query_one("#cfg-log_retention_days", Input).value = str(c.cleanup.log_retention_days)
        self.query_one("#cfg-log_paths", Input).value = ", ".join(c.cleanup.log_paths)

        self.query_one("#btn-save-config", Button).disabled = False
        self.query_one("#btn-delete-config", Button).disabled = False
        self.query_one("#btn-open-editor", Button).disabled = False
        self.app.notify(f"Loaded {name}")

    def _save_config(self) -> None:
        def val(fid: str) -> str:
            return self.query_one(f"#cfg-{fid}", Input).value.strip()

        def csv(fid: str) -> list[str]:
            raw = val(fid)
            return [x.strip() for x in raw.split(",") if x.strip()] if raw else []

        def sw(fid: str) -> bool:
            return self.query_one(f"#cfg-{fid}", Switch).value

        def lines(fid: str) -> list[str]:
            text = self.query_one(f"#cfg-{fid}", TextArea).text.strip()
            return [line.strip() for line in text.splitlines() if line.strip()] if text else []

        name = val("name")
        if not name:
            self.app.notify("Project name is required", severity="error")
            return

        # Check for duplicate on new
        if self._is_new:
            path = get_config_dir() / f"{name}.yml"
            if path.exists():
                self.app.notify(f"Config '{name}' already exists", severity="error")
                return

        try:
            config = ProjectConfig(
                name=name,
                ssh_host=val("ssh_host"),
                ssh_user=val("ssh_user"),
                ssh_key=val("ssh_key"),
                ssh_port=int(val("ssh_port") or "22"),
                sudo=sw("sudo"),
                project_dir=val("project_dir"),
                compose_files=csv("compose_files"),
                compose_command=val("compose_command") or "docker compose",
                compose_profile=val("compose_profile") or None,
                git_branch=val("git_branch") or None,
                backup_dir=val("backup_dir") or "/var/backups/itops",
                backup_retention=int(val("backup_retention") or "5"),
                volumes=csv("volumes"),
                extra_backup_paths=csv("extra_backup_paths"),
                healthcheck_urls=csv("healthcheck_urls"),
                healthcheck_timeout=int(val("healthcheck_timeout") or "120"),
                skip_os_update=sw("skip_os_update"),
                skip_reboot=sw("skip_reboot"),
                reboot_timeout=int(val("reboot_timeout") or "300"),
                apt_timeout=int(val("apt_timeout") or "600"),
                maintenance_window=val("maintenance_window") or None,
                on_failure_cmd=val("on_failure_cmd") or None,
                on_success_cmd=val("on_success_cmd") or None,
                pre_upgrade_hooks=lines("pre_upgrade_hooks"),
                post_upgrade_hooks=lines("post_upgrade_hooks"),
                cleanup=CleanupConfig(
                    prune_images=sw("prune_images"),
                    prune_containers=sw("prune_containers"),
                    prune_volumes=sw("prune_volumes"),
                    prune_build_cache=sw("prune_build_cache"),
                    log_retention_days=int(val("log_retention_days") or "30"),
                    log_paths=csv("log_paths"),
                ),
            )
            path = get_config_dir() / f"{config.name}.yml"
            save_config(config, path)
            self._current_config = config
            self._is_new = False
            self.query_one("#cfg-name", Input).disabled = True
            self.query_one("#btn-delete-config", Button).disabled = False
            # Refresh the select dropdown
            self._refresh_select()
            self.app.notify(f"Saved {config.name}", severity="information")
            logger.info("Config saved: %s", config.name)
        except Exception as e:
            self.app.notify(f"Error: {e}", severity="error")

    def _delete_config(self) -> None:
        if not self._current_config:
            return
        path = get_config_dir() / f"{self._current_config.name}.yml"
        if path.exists():
            path.unlink()
            self.app.notify(f"Deleted {self._current_config.name}")
            self._current_config = None
            self._refresh_select()
            self._new_config()  # clear form

    def _refresh_select(self) -> None:
        """Rebuild the project dropdown after save/delete."""
        select = self.query_one("#config-select", Select)
        configs = list_configs(get_config_dir())
        select.set_options([(cfg.name, cfg.name) for cfg in configs])
