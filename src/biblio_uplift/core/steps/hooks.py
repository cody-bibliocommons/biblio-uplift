from __future__ import annotations

import logging

from biblio_uplift.core.pipeline import PipelineContext, PipelineStep, StepResult, StepStatus

logger = logging.getLogger(__name__)


class HooksStep(PipelineStep):
    """Run a list of shell commands as hooks."""

    def __init__(self, name: str, description: str, hooks_attr: str):
        super().__init__()
        self.name = name
        self.description = description
        self._hooks_attr = hooks_attr  # "pre_upgrade_hooks" or "post_upgrade_hooks"

    def execute(self, ctx: PipelineContext) -> StepResult:
        hooks = getattr(ctx.config, self._hooks_attr, [])
        out = ctx.on_output or (lambda x: None)

        if not hooks:
            return StepResult(status=StepStatus.SUCCESS, message="No hooks configured")

        for i, cmd in enumerate(hooks, 1):
            out(f"Hook {i}/{len(hooks)}: {cmd}")
            result = ctx.ssh.run(cmd, timeout=300, on_output=out)
            if not result.ok:
                return StepResult(
                    status=StepStatus.FAILED,
                    error=f"Hook failed: {cmd}\n{result.stderr}",
                )

        return StepResult(
            status=StepStatus.SUCCESS,
            message=f"Ran {len(hooks)} hook(s)",
        )
