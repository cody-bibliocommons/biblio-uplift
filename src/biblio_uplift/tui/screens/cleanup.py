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
    CleanupPanel { width: 1fr; height: 1fr; padding: 1; layout: vertical; }
    #cleanup-title { text-style: bold; color: $primary; padding: 0 0 1 0; }
    #cleanup-body { height: 1fr; layout: horizontal; }
    #cleanup-steps { width: 35; border: solid $primary-darken-2; padding: 1; }
    #cleanup-log { width: 1fr; }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._running = False
        self._ctx = None

    def compose(self) -> ComposeResult:
        yield Static("Cleanup Pipeline", id="cleanup-title")
        configs = list_configs(get_config_dir())
        options = [(cfg.name, cfg.name) for cfg in configs]
        with Horizontal():
            yield Select(options, id="cleanup-project", prompt="Select project")
            yield Checkbox("Dry run", id="cleanup-dryrun")
        with Horizontal(id="cleanup-body"):
            with Vertical(id="cleanup-steps"):
                yield Static("Steps", classes="section-header")
                for step in get_cleanup_steps():
                    yield Static(f"  {STATUS_ICONS[StepStatus.PENDING]} {step.name}", id=f"cstep-{step.name}")
            yield RichLog(id="cleanup-log", wrap=True, highlight=True, markup=True)
        with Horizontal(classes="upgrade-actions"):
            yield Button("Run Cleanup", id="btn-run-cleanup", variant="warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-run-cleanup" and not self._running:
            select = self.query_one("#cleanup-project", Select)
            if select.value == Select.BLANK:
                self.app.notify("Select a project first", severity="warning")
                return
            self._start_cleanup(str(select.value))

    @work(thread=True)
    def _start_cleanup(self, project_name: str) -> None:
        self._running = True
        self.call_from_thread(self.query_one("#btn-run-cleanup", Button).__setattr__, "disabled", True)
        log = self.query_one("#cleanup-log", RichLog)
        self.call_from_thread(log.clear)

        configs = list_configs(get_config_dir())
        config = next((c for c in configs if c.name == project_name), None)
        if not config:
            self.call_from_thread(log.write, "[red]Config not found[/red]")
            self._running = False
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
            self.call_from_thread(log.write, f"[red]{e}[/red]")
            self._running = False
            return

        dry_run = self.query_one("#cleanup-dryrun", Checkbox).value
        steps = get_cleanup_steps()

        def on_output(line):
            self.call_from_thread(log.write, line)

        def on_step_change(step):
            try:
                w = self.query_one(f"#cstep-{step.name}", Static)
                self.call_from_thread(w.update, f"  {STATUS_ICONS[step.status]} {step.name}")
            except Exception:
                pass

        ctx = PipelineContext(
            config=config, ssh=ssh, on_output=on_output, on_step_change=on_step_change, dry_run=dry_run
        )
        pipeline = Pipeline(name="cleanup", steps=steps)
        try:
            success = pipeline.run(ctx)
            record_run(
                project=config.name,
                pipeline="cleanup",
                steps=pipeline.get_summary(),
                success=success,
                duration=pipeline.duration,
            )
            msg = "[green]Cleanup complete![/green]" if success else "[red]Cleanup failed.[/red]"
            self.call_from_thread(log.write, f"\n{msg}")
        except Exception as e:
            self.call_from_thread(log.write, f"[bold red]Error: {e}[/bold red]")

        self._running = False
        self.call_from_thread(self.query_one("#btn-run-cleanup", Button).__setattr__, "disabled", False)
