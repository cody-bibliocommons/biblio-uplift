import threading
from unittest.mock import MagicMock, patch

import pytest

from biblio_uplift.config.schema import ProjectConfig
from biblio_uplift.core.pipeline import (
    Pipeline,
    PipelineContext,
    PipelineStep,
    StepResult,
    StepStatus,
)
from biblio_uplift.core.ssh import SSHResult


def make_mock_config(tmp_path):
    return ProjectConfig(
        name="test-project",
        ssh_host="test.example.com",
        project_dir=str(tmp_path),
        ssh_key=str(tmp_path / "fake.pem"),
    )


def make_mock_ssh():
    ssh = MagicMock()
    ssh.run.return_value = SSHResult(command="test", exit_code=0, stdout="ok", stderr="")
    ssh.test_connection.return_value = SSHResult(command="echo ok", exit_code=0, stdout="ok", stderr="")
    return ssh


class SuccessStep(PipelineStep):
    name = "success_step"

    def execute(self, ctx):
        return StepResult(status=StepStatus.SUCCESS, message="ok")

    def rollback(self, ctx):
        ctx.state.setdefault("rollbacks", []).append(self.name)


class FailStep(PipelineStep):
    name = "fail_step"

    def execute(self, ctx):
        return StepResult(status=StepStatus.FAILED, error="boom")


class ExplodeStep(PipelineStep):
    name = "explode_step"

    def execute(self, ctx):
        raise RuntimeError("kaboom")


def _make_ctx(tmp_path, **kwargs):
    return PipelineContext(
        config=make_mock_config(tmp_path),
        ssh=make_mock_ssh(),
        **kwargs,
    )


# --- StepStatus ---


class TestStepStatus:
    def test_values(self):
        assert StepStatus.PENDING == "pending"
        assert StepStatus.RUNNING == "running"
        assert StepStatus.SUCCESS == "success"
        assert StepStatus.FAILED == "failed"
        assert StepStatus.SKIPPED == "skipped"


# --- StepResult ---


class TestStepResult:
    def test_status(self):
        r = StepResult(status=StepStatus.SUCCESS, message="done")
        assert r.status == StepStatus.SUCCESS
        assert r.message == "done"


# --- PipelineStep ---


class TestPipelineStep:
    def test_base_raises(self):
        s = PipelineStep()
        with pytest.raises(NotImplementedError):
            s.execute(MagicMock())

    def test_rollback_noop(self):
        s = PipelineStep()
        s.rollback(MagicMock())  # should not raise


# --- Pipeline ---


@patch("biblio_uplift.core.pipeline.fcntl")
class TestPipelineRun:
    def test_all_succeed(self, mock_fcntl, tmp_path):
        p = Pipeline("test", [SuccessStep(), SuccessStep()])
        assert p.run(_make_ctx(tmp_path)) is True
        assert all(s.status == StepStatus.SUCCESS for s in p.steps)

    def test_failure_stops(self, mock_fcntl, tmp_path):
        s1, s2, s3 = SuccessStep(), FailStep(), SuccessStep()
        p = Pipeline("test", [s1, s2, s3])
        assert p.run(_make_ctx(tmp_path)) is False
        assert s1.status == StepStatus.SUCCESS
        assert s2.status == StepStatus.FAILED
        assert s3.status == StepStatus.PENDING

    def test_skip_steps(self, mock_fcntl, tmp_path):
        s1 = SuccessStep()
        s1.name = "skip_me"
        p = Pipeline("test", [s1])
        ctx = _make_ctx(tmp_path, skip_steps={"skip_me"})
        assert p.run(ctx) is True
        assert s1.status == StepStatus.SKIPPED

    def test_dry_run(self, mock_fcntl, tmp_path):
        p = Pipeline("test", [SuccessStep(), SuccessStep()])
        ctx = _make_ctx(tmp_path, dry_run=True)
        assert p.run(ctx) is True
        assert all(s.status == StepStatus.SKIPPED for s in p.steps)

    def test_cancellation(self, mock_fcntl, tmp_path):
        cancel = threading.Event()
        cancel.set()
        ctx = _make_ctx(tmp_path)
        ctx.cancelled = cancel
        p = Pipeline("test", [SuccessStep(), SuccessStep()])
        assert p.run(ctx) is False
        assert all(s.status == StepStatus.SKIPPED for s in p.steps)

    def test_rollback_on_failure(self, mock_fcntl, tmp_path):
        s1, s2, s3 = SuccessStep(), SuccessStep(), FailStep()
        s1.name = "step1"
        s2.name = "step2"
        p = Pipeline("test", [s1, s2, s3])
        ctx = _make_ctx(tmp_path)
        p.run(ctx)
        # rollback called in reverse on successful steps before the failure
        assert ctx.state.get("rollbacks") == ["step2", "step1"]

    def test_exception_in_step(self, mock_fcntl, tmp_path):
        p = Pipeline("test", [ExplodeStep()])
        assert p.run(_make_ctx(tmp_path)) is False
        assert p.steps[0].status == StepStatus.FAILED
        assert "kaboom" in p.steps[0].result.error


class TestPipelineSummary:
    @patch("biblio_uplift.core.pipeline.fcntl")
    def test_get_summary(self, mock_fcntl, tmp_path):
        p = Pipeline("test", [SuccessStep(), FailStep()])
        p.run(_make_ctx(tmp_path))
        summary = p.get_summary()
        assert len(summary) == 2
        assert summary[0]["status"] == "success"
        assert summary[1]["status"] == "failed"
        assert "name" in summary[0]
        assert "duration" in summary[0]


class TestPipelineDuration:
    @patch("biblio_uplift.core.pipeline.fcntl")
    def test_duration(self, mock_fcntl, tmp_path):
        p = Pipeline("test", [SuccessStep()])
        assert p.duration == 0.0
        p.run(_make_ctx(tmp_path))
        assert p.duration > 0.0

    def test_duration_before_run(self):
        p = Pipeline("test", [])
        assert p.duration == 0.0


class TestPipelineLocking:
    def test_lock_conflict(self, tmp_path):
        """Second pipeline can't acquire lock while first holds it."""
        import fcntl as real_fcntl

        lock_path = "/tmp/biblio-uplift-test-project.lock"
        # Hold the lock externally
        lf = open(lock_path, "w")
        real_fcntl.flock(lf, real_fcntl.LOCK_EX | real_fcntl.LOCK_NB)
        try:
            p = Pipeline("test", [SuccessStep()])
            result = p.run(_make_ctx(tmp_path))
            assert result is False
        finally:
            real_fcntl.flock(lf, real_fcntl.LOCK_UN)
            lf.close()


# --- Dry-run with non-skippable steps ---


class NonSkippableStep(PipelineStep):
    name = "preflight"
    skippable = False

    def execute(self, ctx):
        return StepResult(status=StepStatus.SUCCESS, message="preflight ran")


class TestDryRunNonSkippable:
    @patch("biblio_uplift.core.pipeline.fcntl")
    def test_dry_run_skips_all_steps(self, mock_fcntl, tmp_path):
        """Dry run should skip ALL steps, including non-skippable ones."""
        non_skip = NonSkippableStep()
        skip = SuccessStep()
        p = Pipeline("test", [non_skip, skip])
        ctx = _make_ctx(tmp_path, dry_run=True)
        assert p.run(ctx) is True
        assert non_skip.status == StepStatus.SKIPPED
        assert skip.status == StepStatus.SKIPPED


# --- Failure notification ---


class TestFailureNotification:
    @patch("biblio_uplift.core.pipeline._subprocess")
    @patch("biblio_uplift.core.pipeline.fcntl")
    def test_failure_notification_fires_on_failure(self, mock_fcntl, mock_subprocess, tmp_path):
        """on_failure_cmd should be called locally when a step fails."""
        config = make_mock_config(tmp_path)
        config = config.model_copy(update={"on_failure_cmd": "notify-failure.sh"})
        ssh = make_mock_ssh()
        ctx = PipelineContext(config=config, ssh=ssh)
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.returncode = 0
        mock_proc.pid = 12345
        mock_subprocess.Popen.return_value = mock_proc
        p = Pipeline("test", [FailStep()])
        p.run(ctx)
        mock_subprocess.Popen.assert_called_with(
            "notify-failure.sh",
            shell=True,
            stdout=mock_subprocess.PIPE,
            stderr=mock_subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

    @patch("biblio_uplift.core.pipeline._subprocess")
    @patch("biblio_uplift.core.pipeline.fcntl")
    def test_failure_notification_not_called_on_success(self, mock_fcntl, mock_subprocess, tmp_path):
        """on_failure_cmd should NOT be called when pipeline succeeds."""
        config = make_mock_config(tmp_path)
        config = config.model_copy(update={"on_failure_cmd": "notify-failure.sh"})
        ssh = make_mock_ssh()
        ctx = PipelineContext(config=config, ssh=ssh)
        p = Pipeline("test", [SuccessStep()])
        p.run(ctx)
        mock_subprocess.Popen.assert_not_called()


class TestSuccessNotification:
    @patch("biblio_uplift.core.pipeline._subprocess")
    @patch("biblio_uplift.core.pipeline.fcntl")
    def test_success_notification_fires(self, mock_fcntl, mock_subprocess, tmp_path):
        """on_success_cmd fires when pipeline succeeds."""
        config = make_mock_config(tmp_path)
        config = config.model_copy(update={"on_success_cmd": "notify-success.sh"})
        ssh = make_mock_ssh()
        ctx = PipelineContext(config=config, ssh=ssh)
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.returncode = 0
        mock_proc.pid = 12345
        mock_subprocess.Popen.return_value = mock_proc
        p = Pipeline("test", [SuccessStep()])
        p.run(ctx)
        mock_subprocess.Popen.assert_called_with(
            "notify-success.sh",
            shell=True,
            stdout=mock_subprocess.PIPE,
            stderr=mock_subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

    @patch("biblio_uplift.core.pipeline._subprocess")
    @patch("biblio_uplift.core.pipeline.fcntl")
    def test_notification_runs_locally(self, mock_fcntl, mock_subprocess, tmp_path):
        """Notifications run via local subprocess, not SSH."""
        config = make_mock_config(tmp_path)
        config = config.model_copy(update={"on_success_cmd": "notify.sh"})
        ssh = make_mock_ssh()
        ctx = PipelineContext(config=config, ssh=ssh)
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.returncode = 0
        mock_proc.pid = 12345
        mock_subprocess.Popen.return_value = mock_proc
        p = Pipeline("test", [SuccessStep()])
        p.run(ctx)
        # subprocess.Popen was called locally
        mock_subprocess.Popen.assert_called_once()
        # ssh.run was NOT called with the notification command
        for c in ssh.run.call_args_list:
            assert "notify.sh" not in str(c)
