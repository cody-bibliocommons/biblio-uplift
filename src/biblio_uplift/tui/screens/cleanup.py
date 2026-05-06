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
from biblio_uplift.core.steps import get_cleanup_steps
from biblio_uplift.history.audit import record_run

logger = logging.getLogger(__name__)

STATUS_ICONS = {
    StepStatus.PENDING: "*",
    StepStatus.RUNNING: ">",
    StepStatus.SUCCESS: "+",
    StepStatus.FAILED: "!",
    StepStatus.SKIPPED: "-",
}


class CleanupPanel(Widget):
    DEFAULT_CSS = """
    CleanupPanel { width: 1fr; height: 1fr; layout: vertical; }
    #cleanup-title { text-style: bold; color: $primary; padding: 0 0 1 0; }
    #cleanup-controls { height: auto; }
    #cleanup-controls Select { width: 30; }
    #cleanup-controls Checkbox { width: auto; margin: 2 0 0 2; }
    #cleanup-body { height: 1fr; layout: horizontal; }
    #cleanup-steps { width: 35; border: solid $primary-darken-2; padding: 1; }
    #cleanup-log { width: 1fr; }
    .cleanup-actions { height: auto; padding: 1 0; }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._task_active = False
        self._ctx = None

    def compose(self) -> ComposeResult:
        yield Static("Cleanup Pipeline", id="cleanup-title")
        configs = list_configs(get_config_dir())
        options = [(cfg.name, cfg.name) for cfg in configs]
        with Horizontal(id="cleanup-controls"):
            yield Select(options, id="cleanup-project", prompt="Select project")
            yield Checkbox("Dry run", id="cleanup-dryrun")
        with Horizontal(id="cleanup-body"):
            with Vertical(id="cleanup-steps"):
                yield Static("Steps", classes="section-header")
                for step in get_cleanup_steps():
                    yield Static(f"  {STATUS_ICONS[StepStatus.PENDING]} {step.name}", id=f"cstep-{step.name}")
            yield RichLog(id="cleanup-log", wrap=True, highlight=True, markup=True)
        with Horizontal(classes="cleanup-actions"):
            yield Button("Run Cleanup", id="btn-run-cleanup", variant="warning")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "cleanup-project" and event.value != Select.NULL:
            try:
                log = self.query_one("#cleanup-log", RichLog)
                log.clear()
                log.write(f"Selected: [bold]{event.value}[/bold]")
                log.write("Configure options and click Run Cleanup.")
            except Exception:
                pass

    @on(Button.Pressed, "#btn-run-cleanup")
    def handle_run_cleanup(self, event: Button.Pressed) -> None:
        logger.debug("handle_run_cleanup fired: _task_active=%s", self._task_active)
        if self._task_active:
            logger.debug("handle_run_cleanup: already running, ignoring")
            return
        select = self.query_one("#cleanup-project", Select)
        if select.value == Select.NULL:
            logger.debug("handle_run_cleanup: no project selected")
            self.app.notify("Select a project first", severity="warning")
            return
        dry_run = self.query_one("#cleanup-dryrun", Checkbox).value
        logger.debug("handle_run_cleanup: starting cleanup project=%s dry_run=%s", select.value, dry_run)
        self._task_active = True
        self._set_cleanup_btn(True)
        self._start_cleanup(str(select.value), dry_run)

    def _write_output(self, lines: list[str]) -> None:
        """Write output lines to the log widget. Must be called from main thread."""
        try:
            log = self.query_one("#cleanup-log", RichLog)
            log.clear()
            for line in lines:
                log.write(line)
        except Exception as e:
            logger.error("Failed to write output: %s", e)

    def _append_line(self, line: str) -> None:
        """Append a single line to the log widget. Must be called from main thread."""
        try:
            log = self.query_one("#cleanup-log", RichLog)
            log.write(line)
        except Exception:
            pass

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if self._task_active:
            return
        try:
            log = self.query_one("#cleanup-log", RichLog)
            label = event.checkbox.label
            state = "enabled" if event.value else "disabled"
            log.write(f"{label}: {state}")
        except Exception:
            pass

    def _set_cleanup_btn(self, disabled: bool) -> None:
        self.query_one("#btn-run-cleanup", Button).disabled = disabled

    @work(thread=True)
    def _start_cleanup(self, project_name: str, dry_run: bool) -> None:
        logger.info("Worker entered: _start_cleanup(%s, dry_run=%s)", project_name, dry_run)
        try:
            self.app.call_from_thread(self._set_cleanup_btn, True)

            output_lines: list[str] = []

            configs = list_configs(get_config_dir())
            config = next((c for c in configs if c.name == project_name), None)
            if not config:
                output_lines.append("[red]Config not found[/red]")
                self.app.call_from_thread(self._write_output, output_lines)
                self._task_active = False
                self.app.call_from_thread(self._set_cleanup_btn, False)
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
                output_lines.append(f"[red]{e}[/red]")
                self.app.call_from_thread(self._write_output, output_lines)
                self._task_active = False
                self.app.call_from_thread(self._set_cleanup_btn, False)
                return

            steps = get_cleanup_steps()

            def on_output(line):
                output_lines.append(line)
                self.app.call_from_thread(self._append_line, line)

            def on_step_change(step):
                def _update():
                    try:
                        w = self.query_one(f"#cstep-{step.name}", Static)
                        w.update(f"  {STATUS_ICONS[step.status]} {step.name}")
                    except Exception:
                        pass

                self.app.call_from_thread(_update)

            ctx = PipelineContext(
                config=config, ssh=ssh, on_output=on_output, on_step_change=on_step_change, dry_run=dry_run
            )

            output_lines.append(f"Starting cleanup for {project_name}...")
            output_lines.append(f"Dry run: {dry_run}")
            output_lines.append("")

            logger.info("TUI cleanup started: project=%s dry_run=%s", project_name, dry_run)
            pipeline = Pipeline(name="cleanup", steps=steps)
            try:
                success = pipeline.run(ctx)
                logger.info("TUI cleanup finished: project=%s success=%s", project_name, success)
                record_run(
                    project=config.name,
                    pipeline="cleanup",
                    steps=pipeline.get_summary(),
                    success=success,
                    duration=pipeline.duration,
                    dry_run=dry_run,
                )
                msg = "[green]Cleanup complete![/green]" if success else "[red]Cleanup failed.[/red]"
                output_lines.append(f"\n{msg}")
            except Exception as e:
                logger.error("TUI cleanup error: %s", e, exc_info=True)
                output_lines.append(f"[bold red]Error: {e}[/bold red]")

            self.app.call_from_thread(self._write_output, output_lines)
            self._task_active = False
            self.app.call_from_thread(self._set_cleanup_btn, False)
        except Exception as e:
            logger.error("Worker crashed: %s", e, exc_info=True)
            with contextlib.suppress(Exception):
                self.app.call_from_thread(self._write_output, [f"[bold red]Worker error: {e}[/bold red]"])
