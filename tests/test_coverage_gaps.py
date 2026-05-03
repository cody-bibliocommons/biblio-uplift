"""Targeted tests for remaining uncovered lines across all modules."""

from __future__ import annotations

import fcntl
import json
import threading
from unittest.mock import MagicMock, patch

import pytest
from freezegun import freeze_time

from biblio_uplift.core.pipeline import (
    Pipeline,
    PipelineContext,
    PipelineStep,
    StepResult,
    StepStatus,
)
from biblio_uplift.core.ssh import SSHResult, SSHRunner
from biblio_uplift.core.steps.backup import BackupCleanupStep, BackupVolumesStep
from biblio_uplift.core.steps.cleanup import LogCleanupStep
from biblio_uplift.core.steps.git import GitPullStep
from biblio_uplift.core.steps.healthcheck import HealthCheckStep
from biblio_uplift.core.steps.preflight import PreflightStep
from biblio_uplift.core.steps.system import OsUpdateStep, RebootStep
from biblio_uplift.history.audit import _rotate_history, read_history, record_run


def ok(cmd="test", stdout="ok\n"):
    return SSHResult(command=cmd, exit_code=0, stdout=stdout, stderr="")


def fail(cmd="test", stderr="error"):
    return SSHResult(command=cmd, exit_code=1, stdout="", stderr=stderr)


# ── Helpers ──


class _SuccessStep(PipelineStep):
    name = "s"

    def execute(self, ctx):
        return StepResult(status=StepStatus.SUCCESS, message="ok")


class _FailStep(PipelineStep):
    name = "f"

    def execute(self, ctx):
        return StepResult(status=StepStatus.FAILED, error="boom")


def _make_ctx(mock_ssh, mock_config, **kw):
    return PipelineContext(config=mock_config, ssh=mock_ssh, **kw)


def _patch_history(tmp_path):
    p = tmp_path / "history.jsonl"
    return patch("biblio_uplift.history.audit._get_history_path", return_value=p)


# ═══════════════════════════════════════════════════════════════════════
# ssh.py — lines 133-140 (poll-finished branch) and 194-217 (wait_for_reboot)
# ═══════════════════════════════════════════════════════════════════════


class TestSSHPollFinishedBranch:
    """Cover the 'elif proc.poll() is not None' branch (lines 133-140)."""

    def test_poll_finished_reads_remaining(self, tmp_path):
        key = tmp_path / "k.pem"
        key.write_text("x")
        runner = SSHRunner(host="h", user="u", key_path=str(key), sudo=False)

        mock_proc = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = ""
        mock_proc.returncode = 0
        mock_proc.wait.return_value = 0

        # select returns NOT ready (empty), then proc.poll says finished
        # proc.stdout iteration yields remaining lines
        mock_proc.poll.return_value = 0
        mock_proc.stdout.__iter__ = MagicMock(return_value=iter(["remaining\n"]))

        lines_out = []
        with patch("subprocess.Popen", return_value=mock_proc):
            with patch("select.select", return_value=([], [], [])):
                result = runner.run("test", on_output=lines_out.append)

        assert result.exit_code == 0
        assert "remaining" in result.stdout
        assert "remaining" in lines_out


class TestSSHWaitForReboot:
    """Cover wait_for_reboot (lines 194-217)."""

    def test_wait_for_reboot_success(self, tmp_path):
        key = tmp_path / "k.pem"
        key.write_text("x")
        runner = SSHRunner(host="h", user="u", key_path=str(key), sudo=False)

        # Port goes down then comes back, test_connection succeeds
        with patch.object(runner, "_is_port_open", side_effect=[True, False, False, True]):
            with patch.object(runner, "test_connection", return_value=ok()):
                with patch("biblio_uplift.core.ssh.time.sleep"):
                    with patch("biblio_uplift.core.ssh.time.monotonic") as mt:
                        # Phase 1 (down check): start, loop1 (port open), loop2 (port down->break)
                        # Phase 2 (up check): start, loop1 (port open->try ssh->ok)
                        mt.side_effect = [0, 0, 10, 10, 15, 20]
                        assert runner.wait_for_reboot(timeout=300) is True

    def test_wait_for_reboot_timeout(self, tmp_path):
        key = tmp_path / "k.pem"
        key.write_text("x")
        runner = SSHRunner(host="h", user="u", key_path=str(key), sudo=False)

        with patch.object(runner, "_is_port_open", return_value=False):
            with patch("biblio_uplift.core.ssh.time.sleep"):
                with patch("biblio_uplift.core.ssh.time.monotonic") as mt:
                    # down_deadline loop exits immediately (port down)
                    # up loop: start, check1 past deadline
                    mt.side_effect = [0, 0, 0, 999]
                    assert runner.wait_for_reboot(timeout=1) is False


# ═══════════════════════════════════════════════════════════════════════
# pipeline.py — on_step_change callbacks (129/136/144/150), lock contention (101-102)
# ═══════════════════════════════════════════════════════════════════════


class TestPipelineOnStepChange:
    """Cover on_step_change callback lines 129, 136, 144, 150."""

    @patch("biblio_uplift.core.pipeline.fcntl")
    def test_on_step_change_called_for_cancel(self, _fcntl, mock_ssh, mock_config):
        changes = []
        cancel = threading.Event()
        cancel.set()
        ctx = _make_ctx(mock_ssh, mock_config, on_step_change=changes.append)
        ctx.cancelled = cancel
        Pipeline("t", [_SuccessStep()]).run(ctx)
        assert any(s.status == StepStatus.SKIPPED for s in changes)

    @patch("biblio_uplift.core.pipeline.fcntl")
    def test_on_step_change_called_for_dry_run(self, _fcntl, mock_ssh, mock_config):
        changes = []
        ctx = _make_ctx(mock_ssh, mock_config, dry_run=True, on_step_change=changes.append)
        Pipeline("t", [_SuccessStep()]).run(ctx)
        assert len(changes) == 1
        assert changes[0].status == StepStatus.SKIPPED

    @patch("biblio_uplift.core.pipeline.fcntl")
    def test_on_step_change_called_for_skip(self, _fcntl, mock_ssh, mock_config):
        changes = []
        ctx = _make_ctx(mock_ssh, mock_config, skip_steps={"s"}, on_step_change=changes.append)
        Pipeline("t", [_SuccessStep()]).run(ctx)
        assert len(changes) == 1
        assert changes[0].status == StepStatus.SKIPPED

    @patch("biblio_uplift.core.pipeline.fcntl")
    def test_on_step_change_called_for_running_and_result(self, _fcntl, mock_ssh, mock_config):
        statuses = []
        ctx = _make_ctx(mock_ssh, mock_config, on_step_change=lambda s: statuses.append(s.status))
        Pipeline("t", [_SuccessStep()]).run(ctx)
        # RUNNING then SUCCESS
        assert statuses == [StepStatus.RUNNING, StepStatus.SUCCESS]


class TestPipelineLockContention:
    """Cover lines 101-102: lock contention with on_output."""

    def test_lock_contention_with_on_output(self, mock_ssh, mock_config):
        lock_path = f"/tmp/biblio-uplift-{mock_config.name}.lock"
        lf = open(lock_path, "w")
        fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            output = []
            ctx = _make_ctx(mock_ssh, mock_config, on_output=output.append)
            result = Pipeline("t", [_SuccessStep()]).run(ctx)
            assert result is False
            assert any("already running" in o for o in output)
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)
            lf.close()


class TestPipelineNotificationEdgeCases:
    """Cover lines 169, 179, 184-185, 211, 217-218."""

    @patch("biblio_uplift.core.pipeline._subprocess")
    @patch("biblio_uplift.core.pipeline.fcntl")
    def test_notification_with_on_output(self, _fcntl, mock_sub, mock_ssh, mock_config):
        """Line 211: on_output called inside _fire_notification."""
        config = mock_config.model_copy(update={"on_success_cmd": "echo done"})
        output = []
        ctx = PipelineContext(config=config, ssh=mock_ssh, on_output=output.append)
        Pipeline("t", [_SuccessStep()]).run(ctx)
        assert any("Running notification" in o for o in output)

    @patch("biblio_uplift.core.pipeline._subprocess")
    @patch("biblio_uplift.core.pipeline.fcntl")
    def test_notification_command_fails(self, _fcntl, mock_sub, mock_ssh, mock_config):
        """Line 217-218: notification command returns non-zero."""
        mock_sub.run.return_value = MagicMock(returncode=1, stderr="notify err")
        config = mock_config.model_copy(update={"on_success_cmd": "bad-cmd"})
        ctx = PipelineContext(config=config, ssh=mock_ssh)
        # Should not raise, just log warning
        Pipeline("t", [_SuccessStep()]).run(ctx)

    @patch("biblio_uplift.core.pipeline._subprocess")
    @patch("biblio_uplift.core.pipeline.fcntl")
    def test_notification_exception(self, _fcntl, mock_sub, mock_ssh, mock_config):
        """Line 219 area: notification raises exception."""
        mock_sub.run.side_effect = OSError("no such file")
        config = mock_config.model_copy(update={"on_success_cmd": "missing"})
        ctx = PipelineContext(config=config, ssh=mock_ssh)
        Pipeline("t", [_SuccessStep()]).run(ctx)

    @patch("biblio_uplift.core.pipeline._subprocess")
    @patch("biblio_uplift.core.pipeline.fcntl")
    def test_cancel_fires_failure_hook(self, _fcntl, mock_sub, mock_ssh, mock_config):
        """Line 179, 184-185: cancellation fires failure notification."""
        config = mock_config.model_copy(update={"on_failure_cmd": "alert.sh"})
        cancel = threading.Event()
        cancel.set()
        ctx = PipelineContext(config=config, ssh=mock_ssh)
        ctx.cancelled = cancel
        Pipeline("t", [_SuccessStep()]).run(ctx)
        mock_sub.run.assert_called_once()

    @patch("biblio_uplift.core.pipeline._subprocess")
    @patch("biblio_uplift.core.pipeline.fcntl")
    def test_rollback_with_on_output(self, _fcntl, mock_sub, mock_ssh, mock_config):
        """Line 169: on_output('Initiating rollback...')."""
        output = []
        ctx = PipelineContext(config=mock_config, ssh=mock_ssh, on_output=output.append)
        Pipeline("t", [_SuccessStep(), _FailStep()]).run(ctx)
        assert any("rollback" in o.lower() for o in output)


# ═══════════════════════════════════════════════════════════════════════
# healthcheck.py — timeout path (43-80), second-check logging, starting containers
# ═══════════════════════════════════════════════════════════════════════


class TestHealthCheckTimeout:
    """Cover lines 43-62, 72, 77-80: timeout with starting/unhealthy containers."""

    def test_timeout_with_starting_containers(self, mock_ctx):
        mock_ctx.config.healthcheck_timeout = 0
        mock_ctx.config.healthcheck_urls = []
        # After timeout, final check shows starting container
        mock_ctx.ssh.run.return_value = ok(stdout="app\tUp 10s (health: starting)")
        with patch("biblio_uplift.core.steps.healthcheck.time.sleep"):
            with patch("biblio_uplift.core.steps.healthcheck.time.monotonic") as mt:
                mt.side_effect = [0, 100, 100]
                result = HealthCheckStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED
        assert "still starting" in result.error

    def test_timeout_docker_ps_fails(self, mock_ctx):
        mock_ctx.config.healthcheck_timeout = 0
        mock_ctx.config.healthcheck_urls = []
        mock_ctx.ssh.run.return_value = fail(stderr="docker not available")
        with patch("biblio_uplift.core.steps.healthcheck.time.sleep"):
            with patch("biblio_uplift.core.steps.healthcheck.time.monotonic") as mt:
                mt.side_effect = [0, 100, 100]
                result = HealthCheckStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED
        assert "Could not check" in result.error

    def test_second_check_logging(self, mock_ctx):
        """Cover lines 55-57, 59-62, 72: second iteration logging."""
        mock_ctx.config.healthcheck_urls = []
        output = []
        mock_ctx.on_output = output.append

        # First check: starting. Second check: still starting. Third: healthy.
        mock_ctx.ssh.run.side_effect = [
            ok(stdout="app\tUp 5s (health: starting)\ndb\tUp 5s (unhealthy)"),
            ok(stdout="app\tUp 15s (health: starting)\ndb\tUp 15s (unhealthy)"),
            ok(stdout="app\tUp 25s (healthy)\ndb\tUp 25s (healthy)"),
        ]
        with patch("biblio_uplift.core.steps.healthcheck.time.sleep"):
            with patch("biblio_uplift.core.steps.healthcheck.time.monotonic") as mt:
                mt.side_effect = [0, 1, 2, 3, 4, 5]
                result = HealthCheckStep().execute(mock_ctx)

        assert result.status == StepStatus.SUCCESS
        assert any("Waiting..." in o for o in output)
        # Second-check final healthy logging
        assert any("✓" in o and "healthy" in o for o in output)


# ═══════════════════════════════════════════════════════════════════════
# preflight.py — maintenance window outside (29-35), disk insufficient (95-96),
#                volume estimation (82-83), line 67, 111
# ═══════════════════════════════════════════════════════════════════════


class TestPreflightMaintenanceWindow:
    def test_outside_window_crosses_midnight(self, mock_ctx):
        """Cover lines 34-35: crosses-midnight window."""
        mock_ctx.config = mock_ctx.config.model_copy(update={"maintenance_window": "22:00-04:00"})
        with freeze_time("2026-01-01 12:00:00"):
            result = PreflightStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED
        assert "Outside maintenance window" in result.error

    def test_inside_window_crosses_midnight(self, mock_ctx):
        """Cover line 34-35: inside a crosses-midnight window."""
        mock_ctx.config = mock_ctx.config.model_copy(update={"maintenance_window": "22:00-04:00"})
        mock_ctx.ssh.test_connection.return_value = ok()
        mock_ctx.ssh.run.side_effect = [
            ok(stdout="Filesystem 1M-blocks Used Available Use% Mounted\n/dev/sda1 50000M 10000M 40000M 20% /"),
            ok(stdout="500"),
            ok(stdout="200"),
            ok(stdout="24.0.7"),
        ]
        with freeze_time("2026-01-01 23:00:00"):
            result = PreflightStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS

    def test_invalid_maintenance_window_format(self, mock_ctx):
        """Cover line 67 area: bad format logs warning and continues."""
        mock_ctx.config = mock_ctx.config.model_copy(update={"maintenance_window": "bad"})
        mock_ctx.ssh.test_connection.return_value = ok()
        mock_ctx.ssh.run.side_effect = [
            ok(stdout="Filesystem 1M-blocks Used Available Use% Mounted\n/dev/sda1 50000M 10000M 40000M 20% /"),
            ok(stdout="500"),
            ok(stdout="200"),
            ok(stdout="24.0.7"),
        ]
        result = PreflightStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS


class TestPreflightVolumeEstimation:
    def test_volume_estimation_parse_failure(self, mock_ctx):
        """Cover line 82-83: volume du returns non-numeric."""
        mock_ctx.ssh.test_connection.return_value = ok()
        mock_ctx.ssh.run.side_effect = [
            ok(stdout="Filesystem 1M-blocks Used Available Use% Mounted\n/dev/sda1 50000M 10000M 40000M 20% /"),
            ok(stdout="500"),  # project dir
            ok(stdout="not-a-number"),  # volume du fails to parse
            ok(stdout="24.0.7"),  # docker info
        ]
        result = PreflightStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS

    def test_disk_space_insufficient_with_estimate(self, mock_ctx):
        """Cover lines 95-96, 111: estimate * 1.5 > available."""
        mock_ctx.ssh.test_connection.return_value = ok()
        mock_ctx.ssh.run.side_effect = [
            ok(stdout="Filesystem 1M-blocks Used Available Use% Mounted\n/dev/sda1 1000M 900M 500M 90% /"),
            ok(stdout="400"),  # project dir: 400MB
            ok(stdout="200"),  # volume: 200MB -> total 600, need 900, have 500
        ]
        result = PreflightStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED
        assert "Insufficient disk space" in result.error


# ═══════════════════════════════════════════════════════════════════════
# backup.py — volume backup failure (62), cleanup no files (108, 114)
# ═══════════════════════════════════════════════════════════════════════


class TestBackupVolumeFailure:
    def test_volume_backup_docker_pull_fails(self, mock_ctx):
        """Cover line 62 area: docker pull alpine fails."""
        mock_ctx.ssh.run.return_value = fail(stderr="pull failed")
        result = BackupVolumesStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED
        assert "Failed to pull alpine" in result.error


class TestBackupCleanupNoFiles:
    def test_find_returns_failure(self, mock_ctx):
        """Cover line 108: find command fails."""
        mock_ctx.ssh.run.return_value = fail(stderr="find err")
        result = BackupCleanupStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS
        assert "removed 0" in result.message

    def test_files_within_retention(self, mock_ctx):
        """Cover line 114: files <= retention, nothing removed."""
        bdir = str(mock_ctx.config.backup_dir)
        mock_ctx.ssh.run.side_effect = [
            ok(stdout=f"{bdir}/test-project_files_1.tar.gz"),  # 1 file, retention=5
            ok(stdout=""),  # volume pattern
        ]
        result = BackupCleanupStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS
        assert "removed 0" in result.message


# ═══════════════════════════════════════════════════════════════════════
# cleanup.py — log truncation failure (61-62), journalctl failure (71)
# ═══════════════════════════════════════════════════════════════════════


class TestLogCleanupEdgeCases:
    def test_truncate_fails_continues(self, mock_ctx):
        """Cover lines 61-62: truncate fails, logs warning, continues."""
        mock_ctx.config.cleanup.log_paths = ["/var/log/app.log"]
        output = []
        mock_ctx.on_output = output.append
        mock_ctx.ssh.run.side_effect = [
            fail(stderr="permission denied"),  # truncate fails
            ok(),  # journalctl succeeds
        ]
        result = LogCleanupStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS
        assert any("failed to truncate" in o.lower() for o in output)

    def test_journalctl_fails(self, mock_ctx):
        """Cover line 71: journalctl fails -> step fails."""
        mock_ctx.config.cleanup.log_paths = []
        mock_ctx.ssh.run.return_value = fail(stderr="journal err")
        result = LogCleanupStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED
        assert "Journal cleanup failed" in result.message


# ═══════════════════════════════════════════════════════════════════════
# system.py — apt failure (29-30), docker not responsive after reboot (71)
# ═══════════════════════════════════════════════════════════════════════


class TestOsUpdateAptFailure:
    def test_second_command_fails(self, mock_ctx):
        """Cover lines 29-30: apt-get upgrade fails."""
        mock_ctx.ssh.run.side_effect = [ok(), fail(stderr="dpkg lock")]
        result = OsUpdateStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED
        assert "dpkg lock" in result.error


class TestRebootDockerNotResponsive:
    def test_docker_not_responsive_after_reboot(self, mock_ctx):
        """Cover line 71: docker info fails after reboot."""
        output = []
        mock_ctx.on_output = output.append
        mock_ctx.ssh.run.side_effect = [
            ok(),  # reboot
            ok(stdout="test.example.com"),  # hostname
            fail(stderr="Cannot connect to Docker"),  # docker info fails
        ]
        mock_ctx.ssh.wait_for_reboot.return_value = True
        result = RebootStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS  # still succeeds
        assert any("Docker not responsive" in o for o in output)


# ═══════════════════════════════════════════════════════════════════════
# git.py — fetch failure (44), rollback (70)
# ═══════════════════════════════════════════════════════════════════════


class TestGitRollbackNoHash:
    def test_rollback_without_pre_hash_is_noop(self, mock_ctx):
        """Cover line 70: rollback with no pre_pull_hash does nothing."""
        GitPullStep().rollback(mock_ctx)
        mock_ctx.ssh.run.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════
# history/audit.py — rotation 600 entries (67-78), lock contention (63-64),
#                    corrupt JSON (104-105)
# ═══════════════════════════════════════════════════════════════════════


class TestAuditRotation600:
    def test_rotation_trims_to_500(self, tmp_path):
        """Cover lines 67-78: write 600 entries, verify only 500 remain."""
        with _patch_history(tmp_path):
            p = tmp_path / "history.jsonl"
            lines = [json.dumps({"project": f"p{i}", "i": i}) for i in range(600)]
            p.write_text("\n".join(lines) + "\n")
            _rotate_history(max_entries=500)
            remaining = p.read_text().strip().splitlines()
            assert len(remaining) == 500
            # Last entry should be p599
            assert json.loads(remaining[-1])["project"] == "p599"
            # First entry should be p100
            assert json.loads(remaining[0])["project"] == "p100"


class TestAuditLockContention:
    def test_rotation_skipped_when_locked(self, tmp_path):
        """Cover lines 63-64: another process holds the lock."""
        with _patch_history(tmp_path):
            p = tmp_path / "history.jsonl"
            lines = [json.dumps({"project": f"p{i}"}) for i in range(10)]
            p.write_text("\n".join(lines) + "\n")

            lock_path = p.with_suffix(".lock")
            lf = open(lock_path, "w")
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                _rotate_history(max_entries=3)
                # Should skip rotation, file unchanged
                assert len(p.read_text().strip().splitlines()) == 10
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)
                lf.close()


class TestAuditCorruptJSON:
    def test_read_history_skips_corrupt_lines(self, tmp_path):
        """Cover lines 104-105: corrupt JSON lines are skipped."""
        with _patch_history(tmp_path):
            p = tmp_path / "history.jsonl"
            p.write_text(
                json.dumps({"project": "good", "success": True})
                + "\n"
                + "NOT VALID JSON\n"
                + json.dumps({"project": "also_good", "success": False})
                + "\n"
            )
            entries = read_history()
            assert len(entries) == 2
            assert entries[0]["project"] == "good"
            assert entries[1]["project"] == "also_good"


class TestAuditRecordRunTriggersRotation:
    def test_record_run_rotates(self, tmp_path):
        """Cover lines 51-52, 58: record_run calls _rotate_history."""
        with _patch_history(tmp_path):
            p = tmp_path / "history.jsonl"
            lines = [json.dumps({"project": f"p{i}"}) for i in range(505)]
            p.write_text("\n".join(lines) + "\n")
            record_run("new", "upgrade", [], True, 1.0)
            remaining = p.read_text().strip().splitlines()
            # 505 + 1 = 506, rotated to 500
            assert len(remaining) == 500


class TestAuditRecordRunRotationFailure:
    def test_rotation_failure_is_swallowed(self, tmp_path):
        """Cover line 58: rotation exception is caught."""
        with _patch_history(tmp_path):
            with patch("biblio_uplift.history.audit._rotate_history", side_effect=OSError("disk full")):
                # Should not raise
                record_run("proj", "upgrade", [], True, 1.0)
            p = tmp_path / "history.jsonl"
            assert p.exists()


class TestAuditReadHistoryEmpty:
    def test_read_skips_blank_lines(self, tmp_path):
        """Cover line 98: blank lines skipped."""
        with _patch_history(tmp_path):
            p = tmp_path / "history.jsonl"
            p.write_text("\n\n" + json.dumps({"project": "x"}) + "\n\n")
            entries = read_history()
            assert len(entries) == 1


# ═══════════════════════════════════════════════════════════════════════
# Additional edge cases for remaining uncovered lines
# ═══════════════════════════════════════════════════════════════════════


class TestPipelineRollbackException:
    """Cover lines 184-185: rollback raises exception."""

    @patch("biblio_uplift.core.pipeline.fcntl")
    def test_rollback_exception_is_caught(self, _fcntl, mock_ssh, mock_config):
        class BadRollbackStep(PipelineStep):
            name = "bad_rb"

            def execute(self, ctx):
                return StepResult(status=StepStatus.SUCCESS, message="ok")

            def rollback(self, ctx):
                raise RuntimeError("rollback exploded")

        ctx = _make_ctx(mock_ssh, mock_config)
        Pipeline("t", [BadRollbackStep(), _FailStep()]).run(ctx)
        # Should not raise despite rollback exception


class TestBackupTarFailure:
    """Cover backup.py line 41: tar command fails."""

    def test_tar_fails(self, mock_ctx):
        from biblio_uplift.core.steps.backup import BackupFilesStep

        mock_ctx.ssh.run.side_effect = [ok(), ok(), fail(stderr="tar: error")]
        result = BackupFilesStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED
        assert "tar failed" in result.error


class TestBackupCleanupSafetyCheck:
    """Cover backup.py line 114: file outside backup_dir is skipped."""

    def test_file_outside_backup_dir_skipped(self, mock_ctx):
        bdir = str(mock_ctx.config.backup_dir)
        # Return files where one is outside backup_dir
        files = f"{bdir}/old1.tar.gz\n{bdir}/old2.tar.gz\n/etc/passwd\n{bdir}/old3.tar.gz\n{bdir}/old4.tar.gz\n{bdir}/old5.tar.gz\n{bdir}/old6.tar.gz"
        mock_ctx.ssh.run.side_effect = [
            ok(stdout=files),  # find for files pattern
            ok(),
            ok(),  # rm for the 2 oldest inside backup_dir
            ok(stdout=""),  # volume pattern
        ]
        result = BackupCleanupStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS
        # /etc/passwd should NOT have been rm'd
        rm_calls = [c.args[0] for c in mock_ctx.ssh.run.call_args_list if "rm -f" in str(c)]
        assert not any("/etc/passwd" in c for c in rm_calls)


class TestCleanupDockerPruneFails:
    """Cover cleanup.py line 35: prune command fails."""

    def test_prune_fails(self, mock_ctx):
        from biblio_uplift.core.steps.cleanup import DockerCleanupStep

        mock_ctx.ssh.run.side_effect = [ok(), fail(stderr="prune err")]
        result = DockerCleanupStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED


class TestHealthCheckNoContainersFirstCheck:
    """Cover healthcheck.py lines 50-51: no containers on first check."""

    def test_no_containers_first_check(self, mock_ctx):
        mock_ctx.config.healthcheck_urls = []
        mock_ctx.ssh.run.return_value = ok(stdout="")
        with patch("biblio_uplift.core.steps.healthcheck.time.sleep"):
            result = HealthCheckStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS


class TestHealthCheckSecondCheckHealthyLog:
    """Cover healthcheck.py line 72: second-check final healthy state logging."""

    def test_second_check_logs_healthy(self, mock_ctx):
        mock_ctx.config.healthcheck_urls = []
        output = []
        mock_ctx.on_output = output.append
        # First: starting. Second: healthy.
        mock_ctx.ssh.run.side_effect = [
            ok(stdout="app\tUp 5s (health: starting)"),
            ok(stdout="app\tUp 15s (healthy)"),
        ]
        with patch("biblio_uplift.core.steps.healthcheck.time.sleep"):
            with patch("biblio_uplift.core.steps.healthcheck.time.monotonic") as mt:
                mt.side_effect = [0, 1, 2, 3]
                result = HealthCheckStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS
        # The second-check should log the healthy state
        assert any("✓" in o and "app" in o for o in output)


class TestPreflightDfFails:
    """Cover preflight.py line 67: df command fails."""

    def test_df_fails_continues(self, mock_ctx):
        mock_ctx.ssh.test_connection.return_value = ok()
        mock_ctx.ssh.run.side_effect = [
            fail(stderr="df err"),  # df fails
            ok(stdout="500"),  # du project
            ok(stdout="200"),  # du volume
            ok(stdout="24.0.7"),  # docker info
        ]
        result = PreflightStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS


class TestPreflightDockerFails:
    """Cover preflight.py line 111: docker info fails."""

    def test_docker_check_fails(self, mock_ctx):
        mock_ctx.ssh.test_connection.return_value = ok()
        mock_ctx.ssh.run.side_effect = [
            ok(stdout="Filesystem 1M-blocks Used Available Use% Mounted\n/dev/sda1 50000M 10000M 40000M 20% /"),
            ok(stdout="500"),
            ok(stdout="200"),
            fail(stderr="docker not found"),
        ]
        result = PreflightStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED
        assert "Docker check failed" in result.error


class TestGitFetchFailure:
    """Cover git.py line 44: git fetch fails."""

    def test_fetch_fails_returns_error(self, mock_ctx):
        mock_ctx.ssh.run.side_effect = [
            ok(stdout="abc1234 initial"),
            ok(stdout="main"),
            fail(stderr="Could not resolve host"),
        ]
        result = GitPullStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED
        assert "git fetch failed" in result.error


class TestOsUpdateSecondCmdFails:
    """Cover system.py lines 29-30: second apt command fails."""

    def test_upgrade_fails(self, mock_ctx):
        mock_ctx.ssh.run.side_effect = [ok(), fail(stderr="E: Unable to lock")]
        result = OsUpdateStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED
        assert "Command failed" in result.message


class TestAuditRotationWriteFailure:
    """Cover audit.py lines 73-78: write to tmp fails, cleanup."""

    def test_rotation_write_failure(self, tmp_path):
        with _patch_history(tmp_path):
            p = tmp_path / "history.jsonl"
            lines = [json.dumps({"project": f"p{i}"}) for i in range(10)]
            p.write_text("\n".join(lines) + "\n")
            with patch("os.fdopen", side_effect=OSError("disk full")):
                with pytest.raises(OSError, match="disk full"):
                    _rotate_history(max_entries=3)
            # Original file should be unchanged
            assert len(p.read_text().strip().splitlines()) == 10


class TestSSHRunPipeNone:
    """Cover ssh.py line 101: proc.stdout is None."""

    def test_pipe_none_returns_error(self, tmp_path):
        key = tmp_path / "k.pem"
        key.write_text("x")
        runner = SSHRunner(host="h", user="u", key_path=str(key), sudo=False)
        mock_proc = MagicMock()
        mock_proc.stdout = None
        mock_proc.stderr = None
        with patch("subprocess.Popen", return_value=mock_proc):
            result = runner.run("test")
        assert result.exit_code == -1
        assert "Failed to open subprocess pipes" in result.stderr


# ═══════════════════════════════════════════════════════════════════════
# Final remaining lines
# ═══════════════════════════════════════════════════════════════════════


class TestPipelineLockReleaseFailure:
    """Cover pipeline.py lines 101-102: _release_lock exception."""

    @patch("biblio_uplift.core.pipeline.fcntl")
    def test_release_lock_exception(self, mock_fcntl, mock_ssh, mock_config):
        # Make flock succeed on acquire but fail on release
        call_count = [0]

        def flock_side_effect(fd, op):
            call_count[0] += 1
            if op == fcntl.LOCK_UN:
                raise OSError("lock release failed")

        mock_fcntl.flock = flock_side_effect
        mock_fcntl.LOCK_EX = fcntl.LOCK_EX
        mock_fcntl.LOCK_NB = fcntl.LOCK_NB
        mock_fcntl.LOCK_UN = fcntl.LOCK_UN
        ctx = _make_ctx(mock_ssh, mock_config)
        # Should not raise despite lock release failure
        Pipeline("t", [_SuccessStep()]).run(ctx)


class TestOsUpdateRollback:
    """Cover system.py lines 29-30: rollback method."""

    def test_rollback_logs_warning(self, mock_ctx):
        output = []
        mock_ctx.on_output = output.append
        OsUpdateStep().rollback(mock_ctx)
        assert any("cannot be automatically rolled back" in o for o in output)


class TestGitResetFailure:
    """Cover git.py line 44: git reset fails."""

    def test_reset_fails(self, mock_ctx):
        mock_ctx.ssh.run.side_effect = [
            ok(stdout="abc1234 initial"),
            ok(stdout="main"),
            ok(),  # fetch ok
            fail(stderr="reset error"),  # reset fails
        ]
        result = GitPullStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED
        assert "git reset failed" in result.error


class TestHealthCheckUnknownStatus:
    """Cover healthcheck.py lines 50-51: unknown container status on first check."""

    def test_unknown_status_first_check(self, mock_ctx):
        mock_ctx.config.healthcheck_urls = []
        output = []
        mock_ctx.on_output = output.append
        # Container with unknown status (no healthy/unhealthy/starting)
        mock_ctx.ssh.run.return_value = ok(stdout="myapp\tUp 5 minutes")
        with patch("biblio_uplift.core.steps.healthcheck.time.sleep"):
            result = HealthCheckStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS
        assert any("?" in o and "myapp" in o for o in output)


class TestPreflightVolumeParseError:
    """Cover preflight.py lines 82-83: volume du returns non-numeric."""

    def test_volume_du_non_numeric(self, mock_ctx):
        mock_ctx.ssh.test_connection.return_value = ok()
        mock_ctx.config.volumes = ["vol1", "vol2"]
        mock_ctx.ssh.run.side_effect = [
            ok(stdout="Filesystem 1M-blocks Used Available Use% Mounted\n/dev/sda1 50000M 10000M 40000M 20% /"),
            ok(stdout="500"),  # project dir
            ok(stdout="not-a-num"),  # vol1 du fails parse
            ok(stdout="100"),  # vol2 du ok
            ok(stdout="24.0.7"),  # docker info
        ]
        result = PreflightStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS
        # estimated_backup_mb should be 500 + 100 = 600 (vol1 skipped)
        assert mock_ctx.state.get("estimated_backup_mb") == 600


class TestBackupCleanupSafetySkip:
    """Cover backup.py line 114: file path not starting with backup_dir is skipped."""

    def test_unsafe_path_skipped(self, mock_ctx):
        bdir = str(mock_ctx.config.backup_dir)
        mock_ctx.config.backup_retention = 1
        # 3 files, retention=1, so remove 2. One is outside backup_dir.
        files = f"/tmp/evil.tar.gz\n{bdir}/f1.tar.gz\n{bdir}/f2.tar.gz"
        mock_ctx.ssh.run.side_effect = [
            ok(stdout=files),  # find
            ok(),  # rm f1 (the only one inside bdir that's old enough)
            ok(stdout=""),  # volume pattern
        ]
        result = BackupCleanupStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS
        rm_cmds = [str(c) for c in mock_ctx.ssh.run.call_args_list if "rm -f" in str(c)]
        assert not any("evil" in c for c in rm_cmds)


class TestAuditRotationTmpUnlinkFailure:
    """Cover audit.py lines 76-77: os.unlink fails during cleanup."""

    def test_rotation_unlink_failure(self, tmp_path):
        with _patch_history(tmp_path):
            p = tmp_path / "history.jsonl"
            lines = [json.dumps({"project": f"p{i}"}) for i in range(10)]
            p.write_text("\n".join(lines) + "\n")
            with patch("os.replace", side_effect=OSError("replace failed")):
                with patch("os.unlink", side_effect=OSError("unlink failed")):
                    with pytest.raises(OSError, match="replace failed"):
                        _rotate_history(max_entries=3)


class TestAuditRecordRunCallsRotation:
    """Cover audit.py line 58: record_run actually calls _rotate_history."""

    def test_record_triggers_rotation(self, tmp_path):
        with _patch_history(tmp_path), patch("biblio_uplift.history.audit._rotate_history") as mock_rot:
            record_run("proj", "upgrade", [], True, 1.0)
            mock_rot.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════
# Final 3 lines
# ═══════════════════════════════════════════════════════════════════════


class TestHealthCheckTimeoutEmptyLine:
    """Cover healthcheck.py line 72: empty line in timeout else branch."""

    def test_timeout_with_empty_lines_in_output(self, mock_ctx):
        mock_ctx.config.healthcheck_timeout = 0
        mock_ctx.config.healthcheck_urls = []
        # After timeout, docker ps returns output with an empty line between entries
        mock_ctx.ssh.run.return_value = ok(stdout="app\tUp 5s (unhealthy)\n\ndb\tUp 5s (healthy)")
        with patch("biblio_uplift.core.steps.healthcheck.time.sleep"):
            with patch("biblio_uplift.core.steps.healthcheck.time.monotonic") as mt:
                mt.side_effect = [0, 100, 100]
                result = HealthCheckStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED
        assert "unhealthy" in result.error


class TestPreflightProjectDirDuParseError:
    """Cover preflight.py lines 82-83: project dir du returns non-numeric."""

    def test_project_dir_du_non_numeric(self, mock_ctx):
        mock_ctx.ssh.test_connection.return_value = ok()
        mock_ctx.ssh.run.side_effect = [
            ok(stdout="Filesystem 1M-blocks Used Available Use% Mounted\n/dev/sda1 50000M 10000M 40000M 20% /"),
            ok(stdout="not-a-number"),  # project dir du fails parse
            ok(stdout="200"),  # volume du ok
            ok(stdout="24.0.7"),  # docker info
        ]
        result = PreflightStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS


class TestAuditRotateNonExistentFile:
    """Cover audit.py line 58: _rotate_history when file doesn't exist."""

    def test_rotate_no_file(self, tmp_path):
        with _patch_history(tmp_path):
            # Don't create the file
            _rotate_history()  # should return early, no error
