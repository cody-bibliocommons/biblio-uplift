from __future__ import annotations

import logging

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, Checkbox, RichLog, Select, Static

from biblio_uplift.config.loader import get_config_dir, list_configs
from biblio_uplift.core.pipeline import Pipeline, PipelineContext, StepStatus
from biblio_uplift.core.ssh import SSHRunner
from biblio_uplift.core.steps import get_upgrade_steps
from biblio_uplift.history.audit import record_run

logger = logging.getLogger(__name__)

STATUS_ICONS = {
    StepStatus.PENDING: "*",
    StepStatus.RUNNING: ">",
    StepStatus.SUCCESS: "+",
    StepStatus.FAILED: "!",
    StepStatus.SKIPPED: "-",
}


class UpgradePanel(Widget):
    DEFAULT_CSS = """
    UpgradePanel { width: 1fr; height: 1fr; padding: 1; layout: vertical; }
    #upgrade-title { text-style: bold; color: $primary; padding: 0 0 1 0; }
    #upgrade-controls { height: auto; padding: 0 0 1 0; }
    #upgrade-body { height: 1fr; layout: horizontal; }
    #upgrade-steps { width: 35; border: solid $primary-darken-2; padding: 1; }
    #upgrade-log { width: 1fr; }
    .upgrade-actions { height: auto; padding: 1 0; }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._ctx = None
        self._running = False

    def compose(self) -> ComposeResult:
        yield Static("Upgrade Pipeline", id="upgrade-title")
        configs = list_configs(get_config_dir())
        options = [(cfg.name, cfg.name) for cfg in configs]
        with Horizontal(id="upgrade-controls"):
            yield Select(options, id="upgrade-project", prompt="Select project")
            yield Checkbox("Dry run", id="upgrade-dryrun")
            yield Checkbox("Skip reboot", id="upgrade-skip-reboot")
            yield Checkbox("Skip OS update", id="upgrade-skip-os")
        with Horizontal(id="upgrade-body"):
            with Vertical(id="upgrade-steps"):
                yield Static("Steps", classes="section-header")
                for step in get_upgrade_steps():
                    yield Static(f"  {STATUS_ICONS[StepStatus.PENDING]} {step.name}", id=f"ustep-{step.name}")
            yield RichLog(id="upgrade-log", wrap=True, highlight=True, markup=True)
        with Horizontal(classes="upgrade-actions"):
            yield Button("Run Upgrade", id="btn-run-upgrade", variant="success")
            yield Button("Abort", id="btn-abort-upgrade", variant="error", disabled=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-run-upgrade" and not self._running:
            select = self.query_one("#upgrade-project", Select)
            if select.value == Select.BLANK:
                self.app.notify("Select a project first", severity="warning")
                return
            self._start_upgrade(str(select.value))
        elif event.button.id == "btn-abort-upgrade" and self._ctx:
            self._ctx.cancelled.set()
            log = self.query_one("#upgrade-log", RichLog)
            log.write("[bold red]Aborting after current step...[/bold red]")
            event.button.disabled = True

    @work(thread=True)
    def _start_upgrade(self, project_name: str) -> None:
        self._running = True
        self.call_from_thread(self._set_running_state, True)
        log = self.query_one("#upgrade-log", RichLog)
        self.call_from_thread(log.clear)

        configs = list_configs(get_config_dir())
        config = next((c for c in configs if c.name == project_name), None)
        if not config:
            self.call_from_thread(log.write, "[red]Config not found[/red]")
            self._running = False
            self.call_from_thread(self._set_running_state, False)
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
            self._running = False
            self.call_from_thread(self._set_running_state, False)
            return

        skip_steps = set()
        if self.query_one("#upgrade-skip-reboot", Checkbox).value:
            skip_steps.add("reboot")
        if self.query_one("#upgrade-skip-os", Checkbox).value:
            skip_steps.add("os_update")
        dry_run = self.query_one("#upgrade-dryrun", Checkbox).value

        steps = get_upgrade_steps()
        for step in steps:
            self.call_from_thread(self._update_step, step.name, STATUS_ICONS[StepStatus.PENDING], "pending")

        def on_output(line):
            self.call_from_thread(log.write, line)

        def on_step_change(step):
            icon = STATUS_ICONS[step.status]
            self.call_from_thread(self._update_step, step.name, icon, step.status.value)

        ctx = PipelineContext(
            config=config,
            ssh=ssh,
            on_output=on_output,
            on_step_change=on_step_change,
            skip_steps=skip_steps,
            dry_run=dry_run,
        )
        ssh.cancel_event = ctx.cancelled
        self._ctx = ctx

        pipeline = Pipeline(name="upgrade", steps=steps)
        try:
            success = pipeline.run(ctx)
            record_run(
                project=config.name,
                pipeline="upgrade",
                steps=pipeline.get_summary(),
                success=success,
                duration=pipeline.duration,
            )
            msg = "[green]Upgrade complete![/green]" if success else "[red]Upgrade failed.[/red]"
            self.call_from_thread(log.write, f"\n{msg}")
        except Exception as e:
            self.call_from_thread(log.write, f"[bold red]Error: {e}[/bold red]")

        self._running = False
        self._ctx = None
        self.call_from_thread(self._set_running_state, False)

    def _update_step(self, name: str, icon: str, status: str) -> None:
        try:
            w = self.query_one(f"#ustep-{name}", Static)
            w.update(f"  {icon} {name}")
        except Exception:
            pass

    def _set_running_state(self, running: bool) -> None:
        self.query_one("#btn-run-upgrade", Button).disabled = running
        self.query_one("#btn-abort-upgrade", Button).disabled = not running
