from __future__ import annotations

import contextlib
import logging

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Button, Checkbox, Input, RichLog, Select, Static, Tree

from biblio_uplift.config.loader import get_config_dir, list_configs
from biblio_uplift.core.ssh import SSHRunner
from biblio_uplift.core.tools import get_all_tools

logger = logging.getLogger(__name__)


class ToolsPanel(Widget):
    DEFAULT_CSS = """
    ToolsPanel { width: 1fr; height: 1fr; layout: vertical; }
    #tools-title { text-style: bold; color: $primary; padding: 0 0 1 0; }
    #tools-controls { height: auto; }
    #tools-controls Select { width: 30; }
    #tools-controls Input { width: 20; }
    #tools-body { height: 1fr; layout: horizontal; }
    #tools-tree { width: 30; border: solid $primary-darken-2; padding: 1; }
    #tools-log { width: 1fr; }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._selected_tool = None
        self._task_active = False

    def compose(self) -> ComposeResult:
        yield Static("Tools", id="tools-title")
        configs = list_configs(get_config_dir())
        options = [(cfg.name, cfg.name) for cfg in configs]
        with Horizontal(id="tools-controls"):
            yield Select(options, id="tools-project", prompt="Select project")
            yield Input(placeholder="service (optional)", id="tools-service")
            yield Checkbox("Dry run", id="tools-dryrun", classes="toolbar-chk")
            yield Button("Run", id="btn-run-tool", variant="success", classes="toolbar-btn")
        with Horizontal(id="tools-body"):
            tree: Tree[str] = Tree("Tools", id="tools-tree")
            tree.show_root = False
            tree.root.expand()
            # Group tools by category
            tools = get_all_tools()
            categories: dict[str, list] = {}
            for tool in tools:
                categories.setdefault(tool.category, []).append(tool)
            for cat, cat_tools in categories.items():
                branch = tree.root.add(cat, expand=True)
                for tool in cat_tools:
                    branch.add_leaf(tool.name, data=tool)
            yield tree
            yield RichLog(id="tools-log", wrap=True, highlight=True, markup=True)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        if event.node.data is not None:
            self._selected_tool = event.node.data
            with contextlib.suppress(Exception):
                log = self.query_one("#tools-log", RichLog)
                log.clear()
                tool = self._selected_tool
                log.write(f"[bold]{tool.name}[/bold]")
                log.write(f"{tool.description}")
                log.write(f"Category: {tool.category}")
                log.write(
                    f"Read-only: {'[green]Yes[/green]' if tool.read_only else '[bold red]No[/bold red] (modifies system)'}"
                )
                log.write("")
                log.write("Select a project and click Run.")

    @on(Button.Pressed, "#btn-run-tool")
    def handle_run(self, event: Button.Pressed) -> None:
        logger.debug("Tools handle_run called")
        if self._task_active:
            return
        if self._selected_tool is None:
            self.app.notify("Select a tool from the tree first", severity="warning")
            return
        select = self.query_one("#tools-project", Select)
        if select.value == Select.NULL:
            self.app.notify("Select a project first", severity="warning")
            return
        dry_run = self.query_one("#tools-dryrun", Checkbox).value
        tool = self._selected_tool
        # Set target_service if the tool supports it
        if hasattr(tool, "target_service"):
            tool.target_service = self.query_one("#tools-service", Input).value.strip()
        # For mutating tools without dry-run, ask confirmation
        if not tool.read_only and not dry_run:
            # Simple confirmation via notify + proceed
            # For v1, just run it. Confirmation dialog can be added later.
            pass
        self._run_tool(str(select.value), tool, dry_run)

    def _write_output(self, lines: list[str]) -> None:
        try:
            log = self.query_one("#tools-log", RichLog)
            log.clear()
            for line in lines:
                log.write(line)
        except Exception as e:
            logger.error("Failed to write tool output: %s", e)

    @work(thread=True)
    def _run_tool(self, project_name: str, tool, dry_run: bool) -> None:
        import time as _time

        _tool_start = _time.monotonic()
        logger.info("Tool run: %s on %s (dry_run=%s)", tool.name, project_name, dry_run)
        self._task_active = True
        output_lines: list[str] = []

        try:
            configs = list_configs(get_config_dir())
            config = next((c for c in configs if c.name == project_name), None)
            if not config:
                output_lines.append("[red]Config not found[/red]")
                self.app.call_from_thread(self._write_output, output_lines)
                return

            ssh = SSHRunner(
                host=config.ssh_host,
                user=config.ssh_user,
                key_path=config.ssh_key,
                sudo=config.sudo,
                port=config.ssh_port,
            )

            def out(line: str) -> None:
                output_lines.append(line)

            output_lines.append(f"[bold]{tool.name}[/bold] on {project_name}")
            if dry_run and not tool.read_only:
                output_lines.append("[yellow]DRY RUN[/yellow]")
            output_lines.append("")

            if dry_run and not tool.read_only:
                result = tool.dry_run(ssh, config, out)
            else:
                result = tool.execute(ssh, config, out)

            output_lines.append("")
            if result.success:
                output_lines.append("[green]Done.[/green]")
            else:
                output_lines.append(f"[red]Failed: {result.error}[/red]")

        except Exception as e:
            logger.error("Tool error: %s", e, exc_info=True)
            output_lines.append(f"[bold red]Error: {e}[/bold red]")
            _tool_error = str(e)
            _tool_success = False
        else:
            _tool_error = ""
            _tool_success = "result" in dir() and hasattr(result, "success") and result.success
        finally:
            _tool_duration = _time.monotonic() - _tool_start
            try:
                from biblio_uplift.history.audit import record_tool_execution

                record_tool_execution(
                    project=project_name,
                    tool_name=tool.name,
                    success=_tool_success,
                    duration=_tool_duration,
                    dry_run=dry_run,
                    error=_tool_error,
                )
            except Exception as rec_err:
                logger.debug("Failed to record tool execution: %s", rec_err)
            # Reset tool state
            if hasattr(tool, "target_service"):
                tool.target_service = ""
            self._task_active = False
            self.app.call_from_thread(self._write_output, output_lines)
