from __future__ import annotations

import fcntl
import logging
import os
import subprocess as _subprocess  # nosec B404
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from biblio_uplift.config.schema import ProjectConfig
    from biblio_uplift.core.ssh import SSHRunner

logger = logging.getLogger(__name__)


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StepResult:
    status: StepStatus
    message: str = ""
    error: str = ""
    duration: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)


class PipelineStep:
    """Base class for all pipeline steps."""

    name: str = "unnamed"
    description: str = ""
    skippable: bool = True

    def __init__(self):
        self.status = StepStatus.PENDING
        self.result: StepResult | None = None

    def execute(self, ctx: PipelineContext) -> StepResult:
        """Override in subclasses. Run the step logic."""
        raise NotImplementedError

    def rollback(self, ctx: PipelineContext) -> None:
        """Optional rollback logic. Override if needed."""
        pass


@dataclass
class PipelineContext:
    """Shared context passed to all steps."""

    config: ProjectConfig
    ssh: SSHRunner
    on_output: Callable[[str], None] | None = None
    on_step_change: Callable[[PipelineStep], None] | None = None
    dry_run: bool = False
    skip_steps: set[str] = field(default_factory=set)
    state: dict[str, Any] = field(default_factory=dict)
    cancelled: threading.Event = field(default_factory=threading.Event)


class Pipeline:
    """Runs a sequence of PipelineSteps."""

    def __init__(self, name: str, steps: list[PipelineStep]):
        self.name = name
        self.steps = steps
        self.start_time: float | None = None
        self.end_time: float | None = None
        self._lock_file: Any = None

    def _try_lock(self, lock_fd) -> bool:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock_fd.write(str(os.getpid()))
            lock_fd.flush()
            return True
        except OSError:
            return False

    def _release_lock(self):
        if self._lock_file:
            try:
                fcntl.flock(self._lock_file, fcntl.LOCK_UN)
                self._lock_file.close()
            except Exception as e:
                logger.debug("Lock release failed: %s", e)

    @property
    def duration(self) -> float:
        if self.start_time is None:
            return 0.0
        end = self.end_time or time.monotonic()
        return end - self.start_time

    def run(self, ctx: PipelineContext) -> bool:
        """Run all steps. Returns True if all succeeded/skipped."""
        lock_path = Path(tempfile.gettempdir()) / f"biblio-uplift-{ctx.config.name}.lock"
        with open(lock_path, "w") as lock_fd:
            if not self._try_lock(lock_fd):
                logger.error("Another upgrade is already running for %s", ctx.config.name)
                if ctx.on_output:
                    ctx.on_output(f"ERROR: Another upgrade is already running for {ctx.config.name}")
                return False
            self._lock_file = lock_fd
            return self._run_steps(ctx)

    def _run_steps(self, ctx: PipelineContext) -> bool:
        self.start_time = time.monotonic()
        success = True
        failure_hook_fired = False

        try:
            for step in self.steps:
                if ctx.cancelled.is_set():
                    success = False
                    step.status = StepStatus.SKIPPED
                    step.result = StepResult(status=StepStatus.SKIPPED, message="Cancelled by user")
                    if ctx.on_step_change:
                        ctx.on_step_change(step)
                    continue

                if ctx.dry_run and not getattr(step, "supports_dry_run", False):
                    step.status = StepStatus.SKIPPED
                    step.result = StepResult(status=StepStatus.SKIPPED, message="Dry run — skipped")
                    if ctx.on_output:
                        ctx.on_output(f"[DRY RUN] Skipping: {step.name} — {step.description}")
                    if ctx.on_step_change:
                        ctx.on_step_change(step)
                    logger.info("DRY RUN SKIP: %s", step.name)
                    continue

                if step.name in ctx.skip_steps:
                    step.status = StepStatus.SKIPPED
                    step.result = StepResult(status=StepStatus.SKIPPED, message="Skipped by user")
                    if ctx.on_step_change:
                        ctx.on_step_change(step)
                    logger.info("SKIP: %s", step.name)
                    continue

                step.status = StepStatus.RUNNING
                if ctx.on_step_change:
                    ctx.on_step_change(step)
                logger.info("START: %s", step.name)

                start = time.monotonic()
                try:
                    result = step.execute(ctx)
                except Exception as e:
                    result = StepResult(
                        status=StepStatus.FAILED,
                        error=str(e),
                        duration=time.monotonic() - start,
                    )
                    logger.exception("EXCEPTION in %s", step.name)

                result.duration = time.monotonic() - start
                step.status = result.status
                step.result = result

                if ctx.on_step_change:
                    ctx.on_step_change(step)

                if result.status == StepStatus.SUCCESS:
                    ctx.state.setdefault("_completed_steps", []).append(step.name)

                if result.status == StepStatus.FAILED:
                    logger.error("FAIL: %s — %s", step.name, result.error)
                    success = False
                    # Rollback completed steps in reverse
                    if ctx.on_output:
                        ctx.on_output("Initiating rollback...")
                    # Rollback the failed step itself (partial execution may need cleanup)
                    try:
                        step.rollback(ctx)
                    except Exception as e:
                        logger.warning("Rollback failed for %s: %s", step.name, e)
                    for completed in reversed(self.steps[: self.steps.index(step)]):
                        if completed.status == StepStatus.SUCCESS:
                            try:
                                completed.rollback(ctx)
                            except Exception as e:
                                logger.warning("Rollback failed for %s: %s", completed.name, e)
                    # Fire failure notification
                    self._fire_failure_hook(ctx)
                    failure_hook_fired = True
                    break
                else:
                    logger.info("DONE: %s (%.1fs)", step.name, result.duration)

            # Fire failure notification for cancellation (only if not already fired)
            if not success and ctx.cancelled.is_set() and not failure_hook_fired:
                self._fire_failure_hook(ctx)
        finally:
            self.end_time = time.monotonic()
            if success and ctx.config.on_success_cmd:
                self._fire_notification(ctx.config.on_success_cmd, ctx)
        return success

    def _fire_failure_hook(self, ctx: PipelineContext) -> None:
        """Execute the on_failure_cmd if configured."""
        if ctx.config.on_failure_cmd:
            self._fire_notification(ctx.config.on_failure_cmd, ctx)

    def _fire_notification(self, cmd: str, ctx: PipelineContext) -> None:
        """Run a notification command locally."""
        try:
            if ctx.on_output:
                ctx.on_output(f"Running notification: {cmd}")
            proc = _subprocess.Popen(
                cmd,
                shell=True,
                stdout=_subprocess.PIPE,
                stderr=_subprocess.PIPE,
                text=True,
                start_new_session=True,  # nosec B602
            )
            try:
                stdout, stderr = proc.communicate(timeout=30)
                if proc.returncode != 0:
                    logger.warning("Notification command failed: %s", stderr)
                    if ctx.on_output:
                        ctx.on_output(f"Notification failed (exit {proc.returncode}): {stderr.strip()}")
            except _subprocess.TimeoutExpired:
                os.killpg(os.getpgid(proc.pid), 9)
                proc.wait()
                logger.warning("Notification command timed out: %s", cmd)
                if ctx.on_output:
                    ctx.on_output(f"Notification timed out: {cmd}")
        except Exception as e:
            logger.warning("Notification failed: %s", e)
            if ctx.on_output:
                ctx.on_output(f"Notification error: {e}")

    def get_summary(self) -> list[dict[str, Any]]:
        """Return a summary of all step results."""
        return [
            {
                "name": s.name,
                "status": s.status.value,
                "duration": s.result.duration if s.result else 0,
                "message": s.result.message if s.result else "",
                "error": s.result.error if s.result else "",
            }
            for s in self.steps
        ]
