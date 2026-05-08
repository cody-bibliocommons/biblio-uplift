from __future__ import annotations

import contextlib
import logging

from textual import on, work
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
    UpgradePanel { width: 1fr; height: 1fr; layout: vertical; }
    #upgrade-title { text-style: bold; color: $primary; padding: 0 0 1 0; }
    #upgrade-controls { height: auto; }
    #upgrade-controls Select { width: 30; }
    #upgrade-controls Checkbox { width: auto; margin: 2 0 0 2; }
    #upgrade-body { height: 1fr; layout: horizontal; }
    #upgrade-steps { width: 35; border: solid $primary-darken-2; padding: 1; }
    #upgrade-log { width: 1fr; }
    .upgrade-actions { height: auto; padding: 1 0; }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._ctx = None
        self._task_active = False

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

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "upgrade-project" and event.value != Select.NULL:
            with contextlib.suppress(Exception):
                log = self.query_one("#upgrade-log", RichLog)
                log.clear()
                log.write(f"Selected: [bold]{event.value}[/bold]")
                log.write("Configure options and click Run Upgrade.")

    @on(Button.Pressed, "#btn-run-upgrade")
    def handle_run(self, event: Button.Pressed) -> None:
        logger.debug("handle_run fired: _task_active=%s", self._task_active)
        if self._task_active:
            logger.debug("handle_run: already running, ignoring")
            return
        select = self.query_one("#upgrade-project", Select)
        if select.value == Select.NULL:
            logger.debug("handle_run: no project selected")
            self.app.notify("Select a project first", severity="warning")
            return
        skip_reboot = self.query_one("#upgrade-skip-reboot", Checkbox).value
        skip_os = self.query_one("#upgrade-skip-os", Checkbox).value
        dry_run = self.query_one("#upgrade-dryrun", Checkbox).value
        logger.debug("handle_run: starting upgrade project=%s dry_run=%s", select.value, dry_run)
        self._task_active = True
        self._set_running_state(True)
        self._start_upgrade(str(select.value), skip_reboot, skip_os, dry_run)

    @on(Button.Pressed, "#btn-abort-upgrade")
    def handle_abort(self, event: Button.Pressed) -> None:
        if self._ctx:
            self._ctx.cancelled.set()
            log = self.query_one("#upgrade-log", RichLog)
            log.write("[bold red]Aborting after current step...[/bold red]")
            event.button.disabled = True

    def _write_output(self, lines: list[str]) -> None:
        """Write output lines to the log widget. Must be called from main thread."""
        try:
            log = self.query_one("#upgrade-log", RichLog)
            log.clear()
            for line in lines:
                log.write(line)
        except Exception as e:
            logger.error("Failed to write output: %s", e)

    def _append_line(self, line: str) -> None:
        """Append a single line to the log widget. Must be called from main thread."""
        with contextlib.suppress(Exception):
            log = self.query_one("#upgrade-log", RichLog)
            log.write(line)

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if self._task_active:
            return
        with contextlib.suppress(Exception):
            log = self.query_one("#upgrade-log", RichLog)
            label = event.checkbox.label
            state = "enabled" if event.value else "disabled"
            log.write(f"{label}: {state}")

    @work(thread=True)
    def _start_upgrade(self, project_name: str, skip_reboot: bool, skip_os: bool, dry_run: bool) -> None:
        logger.info("Worker entered: _start_upgrade(%s, dry_run=%s)", project_name, dry_run)
        try:
            self.app.call_from_thread(self._set_running_state, True)

            output_lines: list[str] = []

            configs = list_configs(get_config_dir())
            config = next((c for c in configs if c.name == project_name), None)
            if not config:
                output_lines.append("[red]Config not found[/red]")
                self.app.call_from_thread(self._write_output, output_lines)
                self._task_active = False
                self.app.call_from_thread(self._set_running_state, False)
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
                output_lines.append(f"[red]SSH key error: {e}[/red]")
                self.app.call_from_thread(self._write_output, output_lines)
                self._task_active = False
                self.app.call_from_thread(self._set_running_state, False)
                return

            skip_steps = set()
            if skip_reboot:
                skip_steps.add("reboot")
            if skip_os:
                skip_steps.add("os_update")

            steps = get_upgrade_steps()
            for step in steps:
                self.app.call_from_thread(self._update_step, step.name, STATUS_ICONS[StepStatus.PENDING], "pending")

            def on_output(line):
                output_lines.append(line)
                self.app.call_from_thread(self._append_line, line)

            def on_step_change(step):
                icon = STATUS_ICONS[step.status]
                self.app.call_from_thread(self._update_step, step.name, icon, step.status.value)

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

            output_lines.append(f"Starting upgrade for {project_name}...")
            output_lines.append(f"Dry run: {dry_run}")
            output_lines.append("")

            logger.info("TUI upgrade started: project=%s dry_run=%s", project_name, dry_run)
            pipeline = Pipeline(name="upgrade", steps=steps)
            try:
                success = pipeline.run(ctx)
                logger.info("TUI upgrade finished: project=%s success=%s", project_name, success)
                record_run(
                    project=config.name,
                    pipeline="upgrade",
                    steps=pipeline.get_summary(),
                    success=success,
                    duration=pipeline.duration,
                    dry_run=dry_run,
                )
                msg = "[green]Upgrade complete![/green]" if success else "[red]Upgrade failed.[/red]"
                output_lines.append(f"\n{msg}")
            except Exception as e:
                logger.error("TUI upgrade error: %s", e, exc_info=True)
                output_lines.append(f"[bold red]Error: {e}[/bold red]")

            self.app.call_from_thread(self._write_output, output_lines)
            self._task_active = False
            self._ctx = None
            self.app.call_from_thread(self._set_running_state, False)
        except Exception as e:
            logger.error("Worker crashed: %s", e, exc_info=True)
            with contextlib.suppress(Exception):
                self.app.call_from_thread(self._write_output, [f"[bold red]Worker error: {e}[/bold red]"])

    def _update_step(self, name: str, icon: str, status: str) -> None:
        with contextlib.suppress(Exception):
            w = self.query_one(f"#ustep-{name}", Static)
            w.update(f"  {icon} {name}")

    def _set_running_state(self, running: bool) -> None:
        self.query_one("#btn-run-upgrade", Button).disabled = running
        self.query_one("#btn-abort-upgrade", Button).disabled = not running
