from unittest.mock import patch

from biblio_uplift.core.pipeline import StepStatus
from biblio_uplift.core.ssh import SSHResult
from biblio_uplift.core.steps import get_cleanup_steps, get_upgrade_steps
from biblio_uplift.core.steps.backup import BackupCleanupStep, BackupFilesStep, BackupVolumesStep
from biblio_uplift.core.steps.cleanup import DockerCleanupStep, LogCleanupStep
from biblio_uplift.core.steps.docker import DockerDownStep, DockerPullStep, DockerUpStep, _compose_cmd
from biblio_uplift.core.steps.git import GitPullStep
from biblio_uplift.core.steps.healthcheck import HealthCheckStep
from biblio_uplift.core.steps.hooks import HooksStep
from biblio_uplift.core.steps.preflight import PreflightStep
from biblio_uplift.core.steps.system import OsUpdateStep, RebootStep


def ok(cmd="test", stdout="ok\n"):
    return SSHResult(command=cmd, exit_code=0, stdout=stdout, stderr="")


def fail(cmd="test", stderr="error"):
    return SSHResult(command=cmd, exit_code=1, stdout="", stderr=stderr)


# ── PreflightStep ──


class TestPreflightStep:
    def test_success(self, mock_ctx):
        mock_ctx.ssh.test_connection.return_value = ok()
        # df output
        mock_ctx.ssh.run.side_effect = [
            ok(stdout="Filesystem 1M-blocks Used Available Use% Mounted\n/dev/sda1 50000M 10000M 40000M 20% /"),  # df
            ok(stdout="500"),  # du project dir
            ok(stdout="200"),  # du volume
            ok(stdout="24.0.7"),  # docker info
        ]
        result = PreflightStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS

    def test_ssh_fails(self, mock_ctx):
        mock_ctx.ssh.test_connection.return_value = fail(stderr="conn refused")
        result = PreflightStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED
        assert "SSH connection failed" in result.error

    def test_disk_too_low_for_backup(self, mock_ctx):
        mock_ctx.ssh.test_connection.return_value = ok()
        mock_ctx.ssh.run.side_effect = [
            ok(
                stdout="Filesystem 1M-blocks Used Available Use% Mounted\n/dev/sda1 1000M 900M 100M 90% /"
            ),  # df: 100MB free
            ok(stdout="500"),  # du project: 500MB
            ok(stdout="200"),  # du volume: 200MB
            # total estimate = 700MB, need 1050MB, have 100MB -> fail
        ]
        result = PreflightStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED
        assert "Insufficient disk space" in result.error

    def test_preflight_maintenance_window_outside(self, mock_ctx):
        # Set window to a range that excludes current time
        mock_ctx.config = mock_ctx.config.model_copy(update={"maintenance_window": "03:00-03:01"})
        from freezegun import freeze_time

        with freeze_time("2026-01-01 12:00:00"):
            result = PreflightStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED
        assert "Outside maintenance window" in result.error

    def test_preflight_maintenance_window_inside(self, mock_ctx):
        mock_ctx.config = mock_ctx.config.model_copy(update={"maintenance_window": "00:00-23:59"})
        mock_ctx.ssh.test_connection.return_value = ok()
        mock_ctx.ssh.run.side_effect = [
            ok(stdout="Filesystem 1M-blocks Used Available Use% Mounted\n/dev/sda1 50000M 10000M 40000M 20% /"),
            ok(stdout="500"),
            ok(stdout="200"),
            ok(stdout="24.0.7"),
        ]
        result = PreflightStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS


# ── BackupFilesStep ──


class TestBackupFilesStep:
    def test_success(self, mock_ctx):
        mock_ctx.ssh.run.return_value = ok()
        result = BackupFilesStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS
        assert "backup_timestamp" in mock_ctx.state
        # Verify mkdir, chmod, tar were called
        calls = [c.args[0] for c in mock_ctx.ssh.run.call_args_list]
        assert any("mkdir -p" in c for c in calls)
        assert any("chmod 700" in c for c in calls)
        assert any("tar czf" in c for c in calls)

    def test_mkdir_fails(self, mock_ctx):
        mock_ctx.ssh.run.return_value = fail(stderr="permission denied")
        result = BackupFilesStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED
        assert "Failed to create backup dir" in result.error

    def test_chmod_fails(self, mock_ctx):
        mock_ctx.ssh.run.side_effect = [ok(), fail(stderr="chmod err")]
        result = BackupFilesStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED
        assert "permissions" in result.error.lower()


# ── BackupVolumesStep ──


class TestBackupVolumesStep:
    def test_success_with_volumes(self, mock_ctx):
        mock_ctx.ssh.run.return_value = ok()
        result = BackupVolumesStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS
        assert "volume_backup_paths" in mock_ctx.state

    def test_no_volumes(self, mock_ctx):
        mock_ctx.config.volumes = []
        result = BackupVolumesStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS
        assert "No volumes" in result.message

    def test_docker_run_fails(self, mock_ctx):
        # First call is docker pull (ok), second is volume inspect (ok), third is docker run (fail)
        mock_ctx.ssh.run.side_effect = [ok(), ok(), fail(stderr="docker err")]
        result = BackupVolumesStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED
        assert "Volume backup failed" in result.error


# ── BackupCleanupStep ──


class TestBackupCleanupStep:
    def test_finds_and_removes_old(self, mock_ctx):
        # 7 backup sets (each with 1 file), retention is 5 -> remove 2 sets
        bdir = str(mock_ctx.config.backup_dir)
        files = "\n".join(f"{bdir}/test-project_files_2026050{i}_120000.tar.gz" for i in range(7))
        mock_ctx.ssh.run.side_effect = [
            ok(stdout=files),  # ls for all tar.gz
            ok(),  # rm file 0
            ok(),  # rm file 1
        ]
        result = BackupCleanupStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS
        assert "Removed 2 sets" in result.message

    def test_nothing_to_clean(self, mock_ctx):
        mock_ctx.ssh.run.return_value = ok(stdout="")
        result = BackupCleanupStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS
        assert "No backups to clean" in result.message


# ── Docker Steps ──


class TestComposeCmd:
    def test_basic(self, mock_config):
        cmd = _compose_cmd(mock_config)
        assert "docker compose" in cmd
        assert "-f docker-compose.yml" in cmd

    def test_profile_hostname(self, mock_config):
        mock_config.compose_profile = "hostname"
        cmd = _compose_cmd(mock_config)
        assert "--profile $(hostname -s)" in cmd

    def test_profile_literal(self, mock_config):
        mock_config.compose_profile = "web"
        cmd = _compose_cmd(mock_config)
        assert "--profile web" in cmd


class TestDockerDownStep:
    def test_success(self, mock_ctx):
        mock_ctx.ssh.run.return_value = ok()
        result = DockerDownStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS
        cmd = mock_ctx.ssh.run.call_args[0][0]
        assert "down" in cmd

    def test_fail(self, mock_ctx):
        mock_ctx.ssh.run.return_value = fail()
        result = DockerDownStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED

    def test_rollback_brings_up(self, mock_ctx):
        DockerDownStep().rollback(mock_ctx)
        cmd = mock_ctx.ssh.run.call_args[0][0]
        assert "up -d" in cmd


class TestDockerPullStep:
    def test_success(self, mock_ctx):
        mock_ctx.ssh.run.return_value = ok()
        result = DockerPullStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS
        assert "pull" in mock_ctx.ssh.run.call_args[0][0]

    def test_fail(self, mock_ctx):
        mock_ctx.ssh.run.return_value = fail()
        result = DockerPullStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED


class TestDockerUpStep:
    def test_success(self, mock_ctx):
        mock_ctx.ssh.run.return_value = ok()
        result = DockerUpStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS
        assert "up -d" in mock_ctx.ssh.run.call_args[0][0]

    def test_fail(self, mock_ctx):
        mock_ctx.ssh.run.return_value = fail()
        result = DockerUpStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED


# ── GitPullStep ──


class TestGitPullStep:
    def test_success(self, mock_ctx):
        mock_ctx.ssh.run.side_effect = [
            ok(stdout="abc1234 initial commit"),  # git log
            ok(stdout="main"),  # git rev-parse branch
            ok(),  # git fetch
            ok(stdout=""),  # git status --porcelain
            ok(),  # git reset
            ok(stdout="def5678 new commit"),  # git log after
            ok(stdout=" file.txt | 2 +-\n"),  # git diff --stat
        ]
        result = GitPullStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS
        assert mock_ctx.state["git_pre_pull_hash"] == "abc1234"
        assert mock_ctx.state["git_branch"] == "main"

    def test_fetch_fails(self, mock_ctx):
        mock_ctx.ssh.run.side_effect = [
            ok(stdout="abc1234 initial"),  # git log
            ok(stdout="main"),  # branch
            fail(stderr="network err"),  # fetch fails
        ]
        result = GitPullStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED
        assert "git fetch failed" in result.error

    def test_git_pull_uses_config_branch_override(self, mock_ctx):
        mock_ctx.config = mock_ctx.config.model_copy(update={"git_branch": "develop"})
        mock_ctx.ssh.run.side_effect = [
            ok(stdout="abc1234 initial commit"),  # git log
            ok(stdout="main"),  # git rev-parse (ignored due to override)
            ok(),  # git fetch
            ok(stdout=""),  # git status --porcelain
            ok(),  # git reset
            ok(stdout="def5678 new commit"),  # git log after
            ok(stdout=""),  # git diff --stat (no changes)
        ]
        result = GitPullStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS
        # Verify git reset used origin/develop
        reset_call = mock_ctx.ssh.run.call_args_list[4]
        assert "origin/develop" in reset_call.args[0]

    def test_rollback(self, mock_ctx):
        mock_ctx.state["git_pre_pull_hash"] = "abc1234"
        mock_ctx.state["git_branch"] = "main"
        GitPullStep().rollback(mock_ctx)
        cmd = mock_ctx.ssh.run.call_args[0][0]
        assert "checkout" in cmd
        assert "reset --hard abc1234" in cmd


# ── OsUpdateStep ──


class TestOsUpdateStep:
    def test_success(self, mock_ctx):
        mock_ctx.ssh.run.return_value = ok()
        result = OsUpdateStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS
        assert mock_ctx.ssh.run.call_count == 3

    def test_first_cmd_fails(self, mock_ctx):
        mock_ctx.ssh.run.return_value = fail(stderr="apt err")
        result = OsUpdateStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED
        assert mock_ctx.ssh.run.call_count == 1  # stops on first failure


# ── RebootStep ──


class TestRebootStep:
    def test_success(self, mock_ctx):
        mock_ctx.ssh.run.side_effect = [
            ok(),  # reboot (ignored)
            ok(stdout="test.example.com"),  # hostname -f
            ok(stdout="24.0.7"),  # docker info
        ]
        mock_ctx.ssh.wait_for_reboot.return_value = True
        result = RebootStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS

    def test_wait_for_reboot_fails(self, mock_ctx):
        mock_ctx.ssh.run.return_value = ok()
        mock_ctx.ssh.wait_for_reboot.return_value = False
        result = RebootStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED
        assert "did not come back" in result.error


# ── HealthCheckStep ──


class TestHealthCheckStep:
    def test_success(self, mock_ctx):
        mock_ctx.ssh.run.side_effect = [
            ok(stdout="web\tUp 5 minutes (healthy)"),  # docker ps
            ok(stdout="200"),  # curl
        ]
        with patch("biblio_uplift.core.steps.healthcheck.time.sleep"):
            result = HealthCheckStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS

    def test_unhealthy_after_timeout(self, mock_ctx):
        mock_ctx.config.healthcheck_timeout = 0  # immediate timeout
        mock_ctx.ssh.run.side_effect = [
            # The while loop expires immediately (timeout=0), falls to else branch
            ok(stdout="web\tUp 5 minutes (unhealthy)"),  # final check after timeout
            fail(stderr="connection refused"),  # curl
        ]
        with patch("biblio_uplift.core.steps.healthcheck.time.sleep"):
            with patch("biblio_uplift.core.steps.healthcheck.time.monotonic") as mock_time:
                # First call: start, second: already past deadline, third: in else branch
                mock_time.side_effect = [0, 100, 100, 100]
                result = HealthCheckStep().execute(mock_ctx)
        assert result.status == StepStatus.FAILED

    def test_no_containers(self, mock_ctx):
        mock_ctx.ssh.run.side_effect = [
            ok(stdout=""),  # docker ps: empty
            ok(stdout="200"),  # curl
        ]
        with patch("biblio_uplift.core.steps.healthcheck.time.sleep"):
            result = HealthCheckStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS


# ── HooksStep ──


class TestHooksStep:
    def test_success_with_hooks(self, mock_ctx):
        mock_ctx.config.pre_upgrade_hooks = ["echo pre1", "echo pre2"]
        step = HooksStep("pre_hooks", "Pre-upgrade hooks", "pre_upgrade_hooks")
        mock_ctx.ssh.run.return_value = ok()
        result = step.execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS
        assert "2 hook" in result.message

    def test_no_hooks(self, mock_ctx):
        mock_ctx.config.pre_upgrade_hooks = []
        step = HooksStep("pre_hooks", "Pre-upgrade hooks", "pre_upgrade_hooks")
        result = step.execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS
        assert "No hooks" in result.message

    def test_hook_fails(self, mock_ctx):
        mock_ctx.config.post_upgrade_hooks = ["bad_cmd"]
        step = HooksStep("post_hooks", "Post-upgrade hooks", "post_upgrade_hooks")
        mock_ctx.ssh.run.return_value = fail(stderr="not found")
        result = step.execute(mock_ctx)
        assert result.status == StepStatus.FAILED
        assert "Hook failed" in result.error


# ── DockerCleanupStep ──


class TestDockerCleanupStep:
    def test_runs_all_prune_commands(self, mock_ctx):
        mock_ctx.config.cleanup.prune_volumes = True
        mock_ctx.ssh.run.return_value = ok()
        result = DockerCleanupStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS
        cmds = [c.args[0] for c in mock_ctx.ssh.run.call_args_list]
        assert any("container prune" in c for c in cmds)
        assert any("image prune" in c for c in cmds)
        assert any("volume prune" in c for c in cmds)
        assert any("builder prune" in c for c in cmds)

    def test_skips_disabled(self, mock_ctx):
        mock_ctx.config.cleanup.prune_containers = False
        mock_ctx.config.cleanup.prune_images = False
        mock_ctx.config.cleanup.prune_volumes = False
        mock_ctx.config.cleanup.prune_build_cache = False
        mock_ctx.ssh.run.return_value = ok()
        result = DockerCleanupStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS
        cmds = [c.args[0] for c in mock_ctx.ssh.run.call_args_list]
        assert not any("prune" in c for c in cmds if "docker system df" not in c)


# ── LogCleanupStep ──


class TestLogCleanupStep:
    def test_truncates_and_vacuums(self, mock_ctx):
        mock_ctx.config.cleanup.log_paths = ["/var/log/app.log", "/var/log/other.log"]
        mock_ctx.ssh.run.return_value = ok()
        result = LogCleanupStep().execute(mock_ctx)
        assert result.status == StepStatus.SUCCESS
        cmds = [c.args[0] for c in mock_ctx.ssh.run.call_args_list]
        assert any("truncate" in c and "app.log" in c for c in cmds)
        assert any("truncate" in c and "other.log" in c for c in cmds)
        assert any("journalctl --vacuum-time=" in c for c in cmds)


# ── get_upgrade_steps / get_cleanup_steps ──


class TestStepLists:
    def test_upgrade_steps_count(self):
        steps = get_upgrade_steps()
        assert len(steps) == 13

    def test_upgrade_step_names(self):
        names = [s.name for s in get_upgrade_steps()]
        assert names == [
            "preflight",
            "pre_hooks",
            "backup_files",
            "backup_volumes",
            "backup_cleanup",
            "docker_down",
            "git_pull",
            "docker_pull",
            "os_update",
            "reboot",
            "docker_up",
            "healthcheck",
            "post_hooks",
        ]

    def test_cleanup_steps_count(self):
        steps = get_cleanup_steps()
        assert len(steps) == 3

    def test_cleanup_step_names(self):
        names = [s.name for s in get_cleanup_steps()]
        assert names == ["preflight", "docker_cleanup", "log_cleanup"]
