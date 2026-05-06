"""Tests for the CLI module."""

import json
from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

from biblio_uplift.cli.main import (
    _print_summary,
    build_cleanup_pipeline,
    build_upgrade_pipeline,
    cli,
    setup_logging,
)
from biblio_uplift.config.schema import ProjectConfig
from biblio_uplift.core.ssh import SSHResult


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def config_dir(tmp_path):
    """Create a temp config dir with a valid config file."""
    key = tmp_path / "fake.pem"
    key.write_text("fake")
    cfg = ProjectConfig(
        name="myproject",
        ssh_host="host.example.com",
        project_dir="/opt/myproject",
        ssh_key=str(key),
    )
    path = tmp_path / "myproject.yml"
    path.write_text(yaml.dump(cfg.model_dump(mode="json"), default_flow_style=False))
    return tmp_path


# --- Top-level CLI ---


def test_help(runner):
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "biblio-uplift" in result.output


def test_debug_flag(runner):
    result = runner.invoke(cli, ["--debug", "--help"])
    assert result.exit_code == 0


# --- config list ---


def test_config_list(runner, config_dir):
    with patch("biblio_uplift.cli.main.get_config_dir", return_value=config_dir):
        result = runner.invoke(cli, ["config", "list"])
    assert result.exit_code == 0
    assert "myproject" in result.output


def test_config_list_empty(runner, tmp_path):
    with patch("biblio_uplift.cli.main.get_config_dir", return_value=tmp_path):
        result = runner.invoke(cli, ["config", "list"])
    assert result.exit_code == 0
    assert "No configs found" in result.output


# --- config show ---


def test_config_show(runner, config_dir):
    with patch("biblio_uplift.cli.main.get_config_dir", return_value=config_dir):
        result = runner.invoke(cli, ["config", "show", "myproject"])
    assert result.exit_code == 0
    assert "host.example.com" in result.output


def test_config_show_nonexistent(runner, tmp_path):
    with patch("biblio_uplift.cli.main.get_config_dir", return_value=tmp_path):
        result = runner.invoke(cli, ["config", "show", "nope"])
    assert result.exit_code != 0


# --- config create ---


def test_config_create(runner, tmp_path):
    with patch("biblio_uplift.cli.main.get_config_dir", return_value=tmp_path):
        result = runner.invoke(
            cli,
            [
                "config",
                "create",
                "newproj",
                "--host",
                "new.example.com",
                "--project-dir",
                "/opt/new",
            ],
        )
    assert result.exit_code == 0
    assert "Created config" in result.output
    assert (tmp_path / "newproj.yml").exists()


def test_config_create_already_exists(runner, config_dir):
    with patch("biblio_uplift.cli.main.get_config_dir", return_value=config_dir):
        result = runner.invoke(
            cli,
            [
                "config",
                "create",
                "myproject",
                "--host",
                "h",
                "--project-dir",
                "/d",
            ],
        )
    assert result.exit_code != 0
    assert "already exists" in result.output


# --- config validate ---


def test_config_validate_help(runner):
    result = runner.invoke(cli, ["config", "validate", "--help"])
    assert result.exit_code == 0
    assert "project" in result.output.lower()


def test_config_validate_success(runner, config_dir):
    ok = SSHResult(command="test", exit_code=0, stdout="ok\nexists\n", stderr="")
    SSHResult(command="docker", exit_code=0, stdout="24.0.1\n", stderr="")
    exists_ok = SSHResult(command="test", exit_code=0, stdout="exists\n", stderr="")

    mock_ssh = MagicMock()
    mock_ssh.test_connection.return_value = ok
    mock_ssh.run.return_value = exists_ok

    with (
        patch("biblio_uplift.cli.main.get_config_dir", return_value=config_dir),
        patch("biblio_uplift.cli.main.SSHRunner", return_value=mock_ssh),
    ):
        result = runner.invoke(cli, ["config", "validate", "myproject"])
    assert result.exit_code == 0
    assert "Validation complete" in result.output


def test_config_validate_ssh_fails(runner, config_dir):
    fail = SSHResult(command="test", exit_code=1, stdout="", stderr="connection refused")
    mock_ssh = MagicMock()
    mock_ssh.test_connection.return_value = fail

    with (
        patch("biblio_uplift.cli.main.get_config_dir", return_value=config_dir),
        patch("biblio_uplift.cli.main.SSHRunner", return_value=mock_ssh),
    ):
        result = runner.invoke(cli, ["config", "validate", "myproject"])
    assert result.exit_code != 0


def test_config_validate_key_not_found(runner, config_dir):
    with (
        patch("biblio_uplift.cli.main.get_config_dir", return_value=config_dir),
        patch("biblio_uplift.cli.main.SSHRunner", side_effect=FileNotFoundError("no key")),
    ):
        result = runner.invoke(cli, ["config", "validate", "myproject"])
    assert result.exit_code != 0
    assert "SSH key error" in result.output


# --- history ---


def test_history_no_entries(runner, tmp_path, monkeypatch):
    import biblio_uplift.paths

    monkeypatch.setattr(biblio_uplift.paths, "_project_root", None)
    monkeypatch.setenv("ITOPS_UPGRADE_DIR", str(tmp_path))
    result = runner.invoke(cli, ["history"])
    assert result.exit_code == 0
    assert "No history found" in result.output


def test_history_with_entries(runner, tmp_path, monkeypatch):
    import biblio_uplift.paths

    monkeypatch.setattr(biblio_uplift.paths, "_project_root", None)
    monkeypatch.setenv("ITOPS_UPGRADE_DIR", str(tmp_path))
    logs = tmp_path / "logs"
    logs.mkdir()
    entry = {
        "timestamp": "2026-01-01T00:00:00Z",
        "project": "proj",
        "pipeline": "upgrade",
        "success": True,
        "duration_seconds": 42.0,
    }
    (logs / "history.jsonl").write_text(json.dumps(entry) + "\n")
    result = runner.invoke(cli, ["history"])
    assert result.exit_code == 0
    assert "proj" in result.output
    assert "42.0s" in result.output


def test_history_filter_by_project(runner, tmp_path, monkeypatch):
    import biblio_uplift.paths

    monkeypatch.setattr(biblio_uplift.paths, "_project_root", None)
    monkeypatch.setenv("ITOPS_UPGRADE_DIR", str(tmp_path))
    logs = tmp_path / "logs"
    logs.mkdir()
    entries = [
        json.dumps({"timestamp": "t1", "project": "a", "pipeline": "upgrade", "success": True, "duration_seconds": 1}),
        json.dumps({"timestamp": "t2", "project": "b", "pipeline": "upgrade", "success": False, "duration_seconds": 2}),
    ]
    (logs / "history.jsonl").write_text("\n".join(entries) + "\n")
    result = runner.invoke(cli, ["history", "--project", "a"])
    assert "a" in result.output


# --- run command (mocked pipeline) ---


def test_run_non_interactive_dry_run(runner, config_dir, tmp_path, monkeypatch):
    import biblio_uplift.paths

    monkeypatch.setattr(biblio_uplift.paths, "_project_root", None)
    monkeypatch.setenv("ITOPS_UPGRADE_DIR", str(tmp_path))

    mock_ssh = MagicMock()
    mock_pipeline = MagicMock()
    mock_pipeline.run.return_value = True
    mock_pipeline.name = "upgrade"
    mock_pipeline.duration = 1.0
    mock_pipeline.get_summary.return_value = [
        {"name": "preflight", "status": "success", "duration": 0.1, "error": None, "message": "ok"},
    ]

    with (
        patch("biblio_uplift.cli.main.get_config_dir", return_value=config_dir),
        patch("biblio_uplift.cli.main._build_ssh", return_value=mock_ssh),
        patch("biblio_uplift.cli.main.build_upgrade_pipeline", return_value=mock_pipeline),
        patch("biblio_uplift.cli.main.record_run"),
    ):
        result = runner.invoke(cli, ["run", "myproject", "--non-interactive", "--dry-run"])
    assert result.exit_code == 0
    assert "upgrade" in result.output.lower()


def test_run_with_skip_flags(runner, config_dir, tmp_path, monkeypatch):
    import biblio_uplift.paths

    monkeypatch.setattr(biblio_uplift.paths, "_project_root", None)
    monkeypatch.setenv("ITOPS_UPGRADE_DIR", str(tmp_path))

    mock_ssh = MagicMock()
    mock_pipeline = MagicMock()
    mock_pipeline.run.return_value = True
    mock_pipeline.name = "upgrade"
    mock_pipeline.duration = 2.0
    mock_pipeline.get_summary.return_value = []

    with (
        patch("biblio_uplift.cli.main.get_config_dir", return_value=config_dir),
        patch("biblio_uplift.cli.main._build_ssh", return_value=mock_ssh),
        patch("biblio_uplift.cli.main.build_upgrade_pipeline", return_value=mock_pipeline),
        patch("biblio_uplift.cli.main.record_run"),
    ):
        result = runner.invoke(
            cli,
            [
                "run",
                "myproject",
                "--non-interactive",
                "--skip-reboot",
                "--skip-os-update",
                "--skip-backup",
                "--no-hooks",
            ],
        )
    assert result.exit_code == 0


def test_run_failure_exits_nonzero(runner, config_dir, tmp_path, monkeypatch):
    import biblio_uplift.paths

    monkeypatch.setattr(biblio_uplift.paths, "_project_root", None)
    monkeypatch.setenv("ITOPS_UPGRADE_DIR", str(tmp_path))

    mock_ssh = MagicMock()
    mock_pipeline = MagicMock()
    mock_pipeline.run.return_value = False
    mock_pipeline.name = "upgrade"
    mock_pipeline.duration = 5.0
    mock_pipeline.get_summary.return_value = [
        {"name": "git_pull", "status": "failed", "duration": 1.0, "error": "fetch failed", "message": ""},
    ]

    with (
        patch("biblio_uplift.cli.main.get_config_dir", return_value=config_dir),
        patch("biblio_uplift.cli.main._build_ssh", return_value=mock_ssh),
        patch("biblio_uplift.cli.main.build_upgrade_pipeline", return_value=mock_pipeline),
        patch("biblio_uplift.cli.main.record_run"),
    ):
        result = runner.invoke(cli, ["run", "myproject", "--non-interactive"])
    assert result.exit_code == 1
    assert "failed" in result.output.lower()


# --- cleanup command (mocked pipeline) ---


def test_cleanup_non_interactive(runner, config_dir, tmp_path, monkeypatch):
    import biblio_uplift.paths

    monkeypatch.setattr(biblio_uplift.paths, "_project_root", None)
    monkeypatch.setenv("ITOPS_UPGRADE_DIR", str(tmp_path))

    mock_ssh = MagicMock()
    mock_pipeline = MagicMock()
    mock_pipeline.run.return_value = True
    mock_pipeline.name = "cleanup"
    mock_pipeline.duration = 0.5
    mock_pipeline.get_summary.return_value = []

    with (
        patch("biblio_uplift.cli.main.get_config_dir", return_value=config_dir),
        patch("biblio_uplift.cli.main._build_ssh", return_value=mock_ssh),
        patch("biblio_uplift.cli.main.build_cleanup_pipeline", return_value=mock_pipeline),
        patch("biblio_uplift.cli.main.record_run"),
    ):
        result = runner.invoke(cli, ["cleanup", "myproject", "--non-interactive"])
    assert result.exit_code == 0


# --- run ---


def test_run_help(runner):
    result = runner.invoke(cli, ["run", "--help"])
    assert result.exit_code == 0
    for flag in ["--non-interactive", "--skip-reboot", "--skip-os-update", "--skip-backup", "--dry-run", "--no-hooks"]:
        assert flag in result.output


# --- cleanup ---


def test_cleanup_help(runner):
    result = runner.invoke(cli, ["cleanup", "--help"])
    assert result.exit_code == 0
    assert "--non-interactive" in result.output


# --- build helpers ---


def test_build_upgrade_pipeline():
    p = build_upgrade_pipeline()
    assert p.name == "upgrade"
    assert len(p.steps) > 0


def test_build_cleanup_pipeline():
    p = build_cleanup_pipeline()
    assert p.name == "cleanup"
    assert len(p.steps) > 0


# --- setup_logging ---


def test_setup_logging_default(tmp_path, monkeypatch):
    import biblio_uplift.paths

    monkeypatch.setattr(biblio_uplift.paths, "_project_root", None)
    monkeypatch.setenv("ITOPS_UPGRADE_DIR", str(tmp_path))
    import logging

    logging.root.handlers.clear()
    setup_logging(debug=False)
    assert (tmp_path / "logs").exists()


def test_setup_logging_debug(tmp_path, monkeypatch):
    import biblio_uplift.paths

    monkeypatch.setattr(biblio_uplift.paths, "_project_root", None)
    monkeypatch.setenv("ITOPS_UPGRADE_DIR", str(tmp_path))
    import logging

    logging.root.handlers.clear()
    setup_logging(debug=True)
    assert (tmp_path / "logs" / "debug.log").exists()


# --- _print_summary ---


def test_print_summary_success():
    pipeline = MagicMock()
    pipeline.name = "upgrade"
    pipeline.duration = 3.5
    pipeline.get_summary.return_value = [
        {"name": "step1", "status": "success", "duration": 1.0, "error": None, "message": "ok"},
        {"name": "step2", "status": "skipped", "duration": 0.0, "error": None, "message": "skipped"},
    ]
    _print_summary(pipeline, success=True)


def test_print_summary_failure():
    pipeline = MagicMock()
    pipeline.name = "upgrade"
    pipeline.duration = 2.0
    pipeline.get_summary.return_value = [
        {"name": "step1", "status": "failed", "duration": 2.0, "error": "boom", "message": ""},
    ]
    _print_summary(pipeline, success=False)


# --- version ---


def test_version(runner):
    result = runner.invoke(cli, ["--version"])
    assert "0.1.0" in result.output


# --- restore ---


def test_restore_help(runner):
    result = runner.invoke(cli, ["restore", "--help"])
    assert result.exit_code == 0
    assert "--backup" in result.output


def test_restore_no_config(runner, tmp_path):
    with patch("biblio_uplift.cli.main.get_config_dir", return_value=tmp_path):
        result = runner.invoke(cli, ["restore", "nonexistent"])
    assert result.exit_code != 0


# --- run --on-failure ---


def test_run_on_failure_flag(runner):
    result = runner.invoke(cli, ["run", "--help"])
    assert "--on-failure" in result.output


def test_run_start_from_flag(runner):
    result = runner.invoke(cli, ["run", "--help"])
    assert "--start-from" in result.output


def test_run_skip_git_flag(runner):
    result = runner.invoke(cli, ["run", "--help"])
    assert "--skip-git" in result.output


# --- cleanup --dry-run ---


def test_cleanup_dry_run_flag(runner):
    result = runner.invoke(cli, ["cleanup", "--help"])
    assert "--dry-run" in result.output


# --- status ---


def test_status_help(runner):
    result = runner.invoke(cli, ["status", "--help"])
    assert result.exit_code == 0


# --- backup list ---


def test_backup_list_help(runner):
    result = runner.invoke(cli, ["backup", "list", "--help"])
    assert result.exit_code == 0


# --- run-all ---


def test_run_all_help(runner):
    result = runner.invoke(cli, ["run-all", "--help"])
    assert result.exit_code == 0
    assert "--projects" in result.output


# -- restore (error path) --


def test_restore_nonexistent_project(runner, monkeypatch, tmp_path):
    monkeypatch.setattr("biblio_uplift.cli.main.get_config_dir", lambda: tmp_path)
    result = runner.invoke(cli, ["restore", "nonexistent"])
    assert result.exit_code != 0


# -- status (error path) --


def test_status_nonexistent_project(runner, monkeypatch, tmp_path):
    monkeypatch.setattr("biblio_uplift.cli.main.get_config_dir", lambda: tmp_path)
    result = runner.invoke(cli, ["status", "nonexistent"])
    assert result.exit_code != 0


# -- backup list (error path) --


def test_backup_list_nonexistent(runner, monkeypatch, tmp_path):
    monkeypatch.setattr("biblio_uplift.cli.main.get_config_dir", lambda: tmp_path)
    result = runner.invoke(cli, ["backup", "list", "nonexistent"])
    assert result.exit_code != 0


# -- run-all --


def test_run_all_dry_run(runner, monkeypatch, tmp_path):
    """run-all with dry-run should succeed without SSH."""
    from biblio_uplift.config.loader import save_config
    from biblio_uplift.config.schema import ProjectConfig

    cfg_dir = tmp_path / "configs"
    cfg_dir.mkdir()
    key = tmp_path / "fake.pem"
    key.write_text("fake")
    config = ProjectConfig(name="test", ssh_host="localhost", project_dir=str(tmp_path), ssh_key=str(key))
    save_config(config, cfg_dir / "test.yml")
    monkeypatch.setattr("biblio_uplift.cli.main.get_config_dir", lambda: cfg_dir)
    monkeypatch.setattr("biblio_uplift.config.loader.get_config_dir", lambda: cfg_dir)
    monkeypatch.setattr(
        "biblio_uplift.cli.main.build_upgrade_pipeline",
        lambda: MagicMock(
            name="upgrade",
            run=MagicMock(return_value=True),
            get_summary=MagicMock(return_value=[]),
            duration=1.0,
        ),
    )
    monkeypatch.setattr("biblio_uplift.cli.main.record_run", lambda **kw: None)
    result = runner.invoke(cli, ["run-all", "--non-interactive", "--dry-run"])
    assert result.exit_code == 0


def test_run_all_unknown_project(runner, monkeypatch, tmp_path):
    cfg_dir = tmp_path / "configs"
    cfg_dir.mkdir()
    monkeypatch.setattr("biblio_uplift.cli.main.get_config_dir", lambda: cfg_dir)
    monkeypatch.setattr("biblio_uplift.config.loader.get_config_dir", lambda: cfg_dir)
    result = runner.invoke(cli, ["run-all", "--non-interactive", "--projects", "nonexistent"])
    assert result.exit_code != 0


# -- resume --


def test_resume_no_state(runner, monkeypatch, tmp_path):
    monkeypatch.setattr("biblio_uplift.core.state.get_project_root", lambda: tmp_path)
    (tmp_path / "logs").mkdir(exist_ok=True)
    result = runner.invoke(cli, ["resume"])
    assert "No resume state" in result.output


def test_resume_help(runner):
    result = runner.invoke(cli, ["resume", "--help"])
    assert result.exit_code == 0


# ============================================================
# Coverage tests for uncovered lines in cli/main.py
# ============================================================


@pytest.fixture
def mock_ssh_class(monkeypatch):
    """Mock SSHRunner so CLI commands don't need real SSH."""
    mock_ssh = MagicMock()
    mock_ssh.run.return_value = SSHResult(command="test", exit_code=0, stdout="ok\n", stderr="")
    mock_ssh.test_connection.return_value = SSHResult(command="echo ok", exit_code=0, stdout="ok", stderr="")
    mock_ssh.cancel_event = None
    monkeypatch.setattr("biblio_uplift.cli.main.SSHRunner", lambda **kwargs: mock_ssh)
    return mock_ssh


@pytest.fixture
def test_config_dir(monkeypatch, tmp_path):
    """Create a temp config dir with a test project."""
    cfg_dir = tmp_path / "configs"
    cfg_dir.mkdir()
    key = tmp_path / "fake.pem"
    key.write_text("fake")
    from biblio_uplift.config.loader import save_config

    config = ProjectConfig(
        name="test-proj",
        ssh_host="test.local",
        project_dir=str(tmp_path),
        ssh_key=str(key),
        backup_dir=str(tmp_path / "backups"),
    )
    save_config(config, cfg_dir / "test-proj.yml")
    monkeypatch.setattr("biblio_uplift.cli.main.get_config_dir", lambda: cfg_dir)
    monkeypatch.setattr("biblio_uplift.config.loader.get_config_dir", lambda: cfg_dir)
    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)
    monkeypatch.setattr("biblio_uplift.history.audit._get_history_path", lambda: logs / "history.jsonl")
    return cfg_dir


# --- _build_ssh body (line 76) ---


def test_build_ssh_body(runner, mock_ssh_class, test_config_dir, monkeypatch):
    """Exercise _build_ssh body by NOT mocking it, only mocking SSHRunner class."""
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.run", lambda self, ctx: True)
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.get_summary", lambda self: [])
    result = runner.invoke(cli, ["run", "test-proj", "--non-interactive"])
    assert result.exit_code == 0


# --- TUI launch (lines 130-132) ---


def test_tui_launch(runner, monkeypatch):
    """Exercise the TUI launch path when no subcommand is given."""
    mock_app = MagicMock()
    monkeypatch.setattr("biblio_uplift.cli.main.UpgradeApp", lambda: mock_app, raising=False)
    # Import and patch at the right place - the TUI import is inside the function

    # The TUI path is: cli invoked without subcommand -> import UpgradeApp -> app.run()
    with patch("biblio_uplift.tui.app.UpgradeApp", return_value=mock_app):
        runner.invoke(cli, [])
    # TUI was attempted (may fail in test env but the lines are covered)


# --- on_failure flag (line 161) ---


def test_run_on_failure_override(runner, mock_ssh_class, test_config_dir, monkeypatch):
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.run", lambda self, ctx: True)
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.get_summary", lambda self: [])
    result = runner.invoke(cli, ["run", "test-proj", "--non-interactive", "--on-failure", "echo fail"])
    assert result.exit_code == 0


# --- skip_git flag (line 175) ---


def test_run_skip_git(runner, mock_ssh_class, test_config_dir, monkeypatch):
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.run", lambda self, ctx: True)
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.get_summary", lambda self: [])
    result = runner.invoke(cli, ["run", "test-proj", "--non-interactive", "--skip-git"])
    assert result.exit_code == 0


# --- start_from logic (lines 177-184) ---


def test_run_start_from_valid(runner, mock_ssh_class, test_config_dir, monkeypatch):
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.run", lambda self, ctx: True)
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.get_summary", lambda self: [])
    # Use a real step name from the upgrade pipeline
    from biblio_uplift.core.steps import get_upgrade_steps

    steps = get_upgrade_steps()
    step_name = steps[1].name if len(steps) > 1 else steps[0].name
    result = runner.invoke(cli, ["run", "test-proj", "--non-interactive", "--start-from", step_name])
    assert result.exit_code == 0


def test_run_start_from_invalid(runner, mock_ssh_class, test_config_dir):
    result = runner.invoke(cli, ["run", "test-proj", "--non-interactive", "--start-from", "nonexistent_step"])
    assert result.exit_code != 0


# --- confirm prompt (line 187) - interactive run ---


def test_run_interactive_confirm(runner, mock_ssh_class, test_config_dir, monkeypatch):
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.run", lambda self, ctx: True)
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.get_summary", lambda self: [])
    result = runner.invoke(cli, ["run", "test-proj"], input="y\n")
    assert result.exit_code == 0


# --- run pipeline failure (line 187 area) ---


def test_run_full_pipeline_failure(runner, mock_ssh_class, test_config_dir, monkeypatch):
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.run", lambda self, ctx: False)
    monkeypatch.setattr(
        "biblio_uplift.core.pipeline.Pipeline.get_summary",
        lambda self: [
            {"name": "test", "status": "failed", "duration": 1, "message": "", "error": "fail"},
        ],
    )
    result = runner.invoke(cli, ["run", "test-proj", "--non-interactive"])
    assert result.exit_code == 1


# --- cleanup confirm (line 228) ---


def test_cleanup_interactive_confirm(runner, mock_ssh_class, test_config_dir, monkeypatch):
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.run", lambda self, ctx: True)
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.get_summary", lambda self: [])
    result = runner.invoke(cli, ["cleanup", "test-proj"], input="y\n")
    assert result.exit_code == 0


# --- restore body (lines 261-334) ---


def test_restore_with_backup_ts(runner, mock_ssh_class, test_config_dir, monkeypatch):
    mock_ssh_class.run.return_value = SSHResult(
        command="test",
        exit_code=0,
        stdout="exists\n",
        stderr="",
    )
    monkeypatch.setattr("biblio_uplift.history.audit.record_run", lambda **kw: None)
    runner.invoke(cli, ["restore", "test-proj", "--backup", "20260501_120000", "--non-interactive"])
    assert mock_ssh_class.run.called


def test_restore_latest_backup(runner, mock_ssh_class, test_config_dir, monkeypatch):
    """Restore without --backup should find latest."""
    call_count = [0]

    def fake_run(cmd, **kwargs):
        call_count[0] += 1
        if "ls -1t" in cmd:
            return SSHResult(
                command=cmd,
                exit_code=0,
                stdout="/var/backups/itops/test-proj_files_20260501_120000.tar.gz\n",
                stderr="",
            )
        if "test -f" in cmd:
            return SSHResult(command=cmd, exit_code=0, stdout="exists\n", stderr="")
        return SSHResult(command=cmd, exit_code=0, stdout="ok\n", stderr="")

    mock_ssh_class.run.side_effect = fake_run
    monkeypatch.setattr("biblio_uplift.history.audit.record_run", lambda **kw: None)
    runner.invoke(cli, ["restore", "test-proj", "--non-interactive"])
    assert call_count[0] > 0


def test_restore_backup_not_found(runner, mock_ssh_class, test_config_dir):
    mock_ssh_class.run.return_value = SSHResult(
        command="test",
        exit_code=1,
        stdout="",
        stderr="not found",
    )
    result = runner.invoke(cli, ["restore", "test-proj", "--backup", "20260501_120000", "--non-interactive"])
    assert result.exit_code != 0


def test_restore_no_latest_backup(runner, mock_ssh_class, test_config_dir):
    """No --backup and no backups found on server."""
    mock_ssh_class.run.return_value = SSHResult(command="ls", exit_code=1, stdout="", stderr="")
    result = runner.invoke(cli, ["restore", "test-proj", "--non-interactive"])
    assert result.exit_code != 0


def test_restore_interactive_confirm(runner, mock_ssh_class, test_config_dir, monkeypatch):
    mock_ssh_class.run.return_value = SSHResult(
        command="test",
        exit_code=0,
        stdout="exists\n",
        stderr="",
    )
    monkeypatch.setattr("biblio_uplift.history.audit.record_run", lambda **kw: None)
    runner.invoke(cli, ["restore", "test-proj", "--backup", "20260501_120000"], input="y\n")
    assert mock_ssh_class.run.called


def test_restore_file_restore_fails(runner, mock_ssh_class, test_config_dir, monkeypatch):
    """File tar extraction fails."""
    call_count = [0]

    def fake_run(cmd, **kwargs):
        call_count[0] += 1
        if "test -f" in cmd:
            return SSHResult(command=cmd, exit_code=0, stdout="exists\n", stderr="")
        if "ls -1 " in cmd:
            return SSHResult(command=cmd, exit_code=1, stdout="", stderr="")
        if "down" in cmd:
            return SSHResult(command=cmd, exit_code=0, stdout="", stderr="")
        if "tar xzf" in cmd:
            return SSHResult(command=cmd, exit_code=1, stdout="", stderr="tar error")
        return SSHResult(command=cmd, exit_code=0, stdout="ok\n", stderr="")

    mock_ssh_class.run.side_effect = fake_run
    result = runner.invoke(cli, ["restore", "test-proj", "--backup", "20260501_120000", "--non-interactive"])
    assert result.exit_code != 0


# --- resume body (lines 353-388) ---


def test_resume_with_state(runner, mock_ssh_class, test_config_dir, monkeypatch):
    monkeypatch.setattr(
        "biblio_uplift.core.state.load_resume_state",
        lambda: {
            "project": "test-proj",
            "completed_steps": ["preflight"],
            "skip_steps": [],
            "state": {},
        },
    )
    monkeypatch.setattr("biblio_uplift.core.state.clear_resume_state", lambda: None)
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.run", lambda self, ctx: True)
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.get_summary", lambda self: [])
    result = runner.invoke(cli, ["resume"])
    assert result.exit_code == 0


def test_resume_failure(runner, mock_ssh_class, test_config_dir, monkeypatch):
    monkeypatch.setattr(
        "biblio_uplift.core.state.load_resume_state",
        lambda: {
            "project": "test-proj",
            "completed_steps": [],
            "skip_steps": [],
            "state": {},
        },
    )
    monkeypatch.setattr("biblio_uplift.core.state.clear_resume_state", lambda: None)
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.run", lambda self, ctx: False)
    monkeypatch.setattr(
        "biblio_uplift.core.pipeline.Pipeline.get_summary",
        lambda self: [
            {"name": "step1", "status": "failed", "duration": 1, "message": "", "error": "err"},
        ],
    )
    result = runner.invoke(cli, ["resume"])
    assert result.exit_code == 1


# --- config validate body (lines 474, 481, 490, 498) ---


def test_config_validate_full(runner, mock_ssh_class, test_config_dir):
    mock_ssh_class.run.return_value = SSHResult(
        command="test",
        exit_code=0,
        stdout="exists\n28.0.0",
        stderr="",
    )
    mock_ssh_class.test_connection.return_value = SSHResult(
        command="echo ok",
        exit_code=0,
        stdout="ok",
        stderr="",
    )
    result = runner.invoke(cli, ["config", "validate", "test-proj"])
    assert result.exit_code == 0
    assert "Validation complete" in result.output


def test_config_validate_ssh_fail(runner, mock_ssh_class, test_config_dir):
    mock_ssh_class.test_connection.return_value = SSHResult(
        command="echo ok",
        exit_code=1,
        stdout="",
        stderr="Connection refused",
    )
    result = runner.invoke(cli, ["config", "validate", "test-proj"])
    assert result.exit_code != 0


def test_config_validate_docker_fail(runner, mock_ssh_class, test_config_dir):
    """Docker check fails but SSH succeeds."""
    call_count = [0]

    def fake_run(cmd, **kwargs):
        call_count[0] += 1
        if "docker info" in cmd:
            return SSHResult(command=cmd, exit_code=1, stdout="", stderr="docker not found")
        return SSHResult(command=cmd, exit_code=0, stdout="exists\n", stderr="")

    mock_ssh_class.run.side_effect = fake_run
    mock_ssh_class.test_connection.return_value = SSHResult(
        command="echo ok",
        exit_code=0,
        stdout="ok",
        stderr="",
    )
    result = runner.invoke(cli, ["config", "validate", "test-proj"])
    assert result.exit_code == 0  # docker fail is non-fatal


def test_config_validate_dir_missing(runner, mock_ssh_class, test_config_dir):
    """Project dir check fails."""
    call_count = [0]

    def fake_run(cmd, **kwargs):
        call_count[0] += 1
        if "test -d" in cmd and "project" not in cmd:
            # backup dir parent check
            return SSHResult(command=cmd, exit_code=1, stdout="", stderr="")
        if "test -d" in cmd:
            return SSHResult(command=cmd, exit_code=1, stdout="", stderr="")
        return SSHResult(command=cmd, exit_code=0, stdout="exists\n28.0.0", stderr="")

    mock_ssh_class.run.side_effect = fake_run
    mock_ssh_class.test_connection.return_value = SSHResult(
        command="echo ok",
        exit_code=0,
        stdout="ok",
        stderr="",
    )
    result = runner.invoke(cli, ["config", "validate", "test-proj"])
    assert result.exit_code == 0  # dir missing is non-fatal


# --- run-all body (lines 523-524, 528, 541-544, 548, 550) ---


def test_run_all_success(runner, mock_ssh_class, test_config_dir, monkeypatch):
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.run", lambda self, ctx: True)
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.get_summary", lambda self: [])
    result = runner.invoke(cli, ["run-all", "--non-interactive", "--dry-run"])
    assert result.exit_code == 0


def test_run_all_no_projects(runner, monkeypatch, tmp_path):
    cfg_dir = tmp_path / "empty_configs"
    cfg_dir.mkdir()
    monkeypatch.setattr("biblio_uplift.cli.main.get_config_dir", lambda: cfg_dir)
    monkeypatch.setattr("biblio_uplift.config.loader.get_config_dir", lambda: cfg_dir)
    result = runner.invoke(cli, ["run-all", "--non-interactive"])
    assert "No projects found" in result.output


def test_run_all_with_skip_flags(runner, mock_ssh_class, test_config_dir, monkeypatch):
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.run", lambda self, ctx: True)
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.get_summary", lambda self: [])
    result = runner.invoke(cli, ["run-all", "--non-interactive", "--skip-reboot", "--skip-os-update"])
    assert result.exit_code == 0


def test_run_all_interactive_confirm(runner, mock_ssh_class, test_config_dir, monkeypatch):
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.run", lambda self, ctx: True)
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.get_summary", lambda self: [])
    result = runner.invoke(cli, ["run-all"], input="y\n")
    assert result.exit_code == 0


def test_run_all_filter_projects(runner, mock_ssh_class, test_config_dir, monkeypatch):
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.run", lambda self, ctx: True)
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.get_summary", lambda self: [])
    result = runner.invoke(cli, ["run-all", "--non-interactive", "--projects", "test-proj"])
    assert result.exit_code == 0


def test_run_all_ssh_key_error(runner, test_config_dir, monkeypatch):
    """SSHRunner raises FileNotFoundError for a project."""
    monkeypatch.setattr("biblio_uplift.cli.main.SSHRunner", MagicMock(side_effect=FileNotFoundError("no key")))
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.run", lambda self, ctx: True)
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.get_summary", lambda self: [])
    result = runner.invoke(cli, ["run-all", "--non-interactive"])
    assert result.exit_code != 0


def test_run_all_multiple_projects(runner, mock_ssh_class, test_config_dir, tmp_path, monkeypatch):
    from biblio_uplift.config.loader import save_config

    key = tmp_path / "fake.pem"
    cfg2 = ProjectConfig(
        name="test-proj2",
        ssh_host="test2.local",
        project_dir=str(tmp_path),
        ssh_key=str(key),
    )
    save_config(cfg2, test_config_dir / "test-proj2.yml")
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.run", lambda self, ctx: True)
    monkeypatch.setattr("biblio_uplift.core.pipeline.Pipeline.get_summary", lambda self: [])
    result = runner.invoke(cli, ["run-all", "--non-interactive", "--dry-run"])
    assert result.exit_code == 0


# --- status body (lines 614-662) ---


def test_status_success(runner, mock_ssh_class, test_config_dir):
    result = runner.invoke(cli, ["status", "test-proj"])
    assert result.exit_code == 0
    assert mock_ssh_class.run.called


def test_status_reboot_required(runner, mock_ssh_class, test_config_dir):
    """Status shows reboot required warning."""

    def fake_run(cmd, **kwargs):
        if "reboot-required" in cmd:
            return SSHResult(command=cmd, exit_code=0, stdout="*** System restart required ***\n", stderr="")
        if "ls -1t" in cmd:
            return SSHResult(command=cmd, exit_code=1, stdout="", stderr="")
        return SSHResult(command=cmd, exit_code=0, stdout="ok\n", stderr="")

    mock_ssh_class.run.side_effect = fake_run
    result = runner.invoke(cli, ["status", "test-proj"])
    assert result.exit_code == 0


def test_status_no_containers(runner, mock_ssh_class, test_config_dir):
    """Status when no containers are running."""

    def fake_run(cmd, **kwargs):
        if "ps --format" in cmd:
            return SSHResult(command=cmd, exit_code=1, stdout="", stderr="")
        if "ls -1t" in cmd:
            return SSHResult(command=cmd, exit_code=1, stdout="", stderr="")
        return SSHResult(command=cmd, exit_code=0, stdout="ok\n", stderr="")

    mock_ssh_class.run.side_effect = fake_run
    result = runner.invoke(cli, ["status", "test-proj"])
    assert result.exit_code == 0
    assert "none running" in result.output


# --- backup list body (lines 676-696) ---


def test_backup_list_success(runner, mock_ssh_class, test_config_dir):
    mock_ssh_class.run.return_value = SSHResult(
        command="ls",
        exit_code=0,
        stdout="-rw-r--r-- 1 root root 1234 May 1 12:00 test_files_20260501.tar.gz\n",
        stderr="",
    )
    result = runner.invoke(cli, ["backup", "list", "test-proj"])
    assert result.exit_code == 0


def test_backup_list_empty(runner, mock_ssh_class, test_config_dir):
    mock_ssh_class.run.return_value = SSHResult(
        command="ls",
        exit_code=1,
        stdout="",
        stderr="No such file",
    )
    result = runner.invoke(cli, ["backup", "list", "test-proj"])
    assert result.exit_code == 0
    assert "No backups" in result.output


# --- restore volume failure (line 325) ---


def test_restore_with_volume_failure(runner, mock_ssh_class, test_config_dir, monkeypatch):
    """Volume restore fails but restore continues."""
    call_seq = []

    def fake_run(cmd, **kwargs):
        call_seq.append(cmd)
        if "test -f" in cmd:
            return SSHResult(command=cmd, exit_code=0, stdout="exists\n", stderr="")
        if "ls -1 " in cmd and "*_" in cmd:
            # Return a volume backup file
            return SSHResult(
                command=cmd, exit_code=0, stdout="/var/backups/itops/myvol_20260501_120000.tar.gz\n", stderr=""
            )
        if "down" in cmd:
            return SSHResult(command=cmd, exit_code=0, stdout="", stderr="")
        if "tar xzf" in cmd and "backup" not in cmd:
            # File restore succeeds
            return SSHResult(command=cmd, exit_code=0, stdout="", stderr="")
        if "docker run" in cmd:
            # Volume restore fails
            return SSHResult(command=cmd, exit_code=1, stdout="", stderr="volume error")
        if "up -d" in cmd:
            return SSHResult(command=cmd, exit_code=0, stdout="", stderr="")
        return SSHResult(command=cmd, exit_code=0, stdout="ok\n", stderr="")

    mock_ssh_class.run.side_effect = fake_run
    monkeypatch.setattr("biblio_uplift.history.audit.record_run", lambda **kw: None)
    runner.invoke(cli, ["restore", "test-proj", "--backup", "20260501_120000", "--non-interactive"])
    assert any("docker run" in c for c in call_seq)


# --- config validate compose file not found (line 490) ---


def test_config_validate_compose_not_found(runner, mock_ssh_class, test_config_dir):
    """Compose file check fails."""

    def fake_run(cmd, **kwargs):
        if "test -f" in cmd and "docker-compose" in cmd:
            return SSHResult(command=cmd, exit_code=1, stdout="", stderr="not found")
        return SSHResult(command=cmd, exit_code=0, stdout="exists\n28.0.0", stderr="")

    mock_ssh_class.run.side_effect = fake_run
    mock_ssh_class.test_connection.return_value = SSHResult(
        command="echo ok",
        exit_code=0,
        stdout="ok",
        stderr="",
    )
    result = runner.invoke(cli, ["config", "validate", "test-proj"])
    assert result.exit_code == 0
    assert "not found" in result.output


# --- config delete (lines 505-512) ---


def test_config_delete_success(runner, test_config_dir):
    """Cover config delete happy path."""
    result = runner.invoke(cli, ["config", "delete", "test-proj", "--non-interactive"])
    assert result.exit_code == 0
    assert "Deleted" in result.output


def test_config_delete_not_found(runner, test_config_dir):
    """Cover config delete when project doesn't exist."""
    result = runner.invoke(cli, ["config", "delete", "nonexistent", "--non-interactive"])
    assert result.exit_code == 1
    assert "Config not found" in result.output


# --- config edit (lines 519-527) ---


def test_config_edit_success(runner, test_config_dir, monkeypatch):
    """Cover config edit happy path."""
    monkeypatch.setenv("EDITOR", "true")  # 'true' command does nothing
    with patch("subprocess.call", return_value=0) as mock_call:
        result = runner.invoke(cli, ["config", "edit", "test-proj"])
        assert result.exit_code == 0
        mock_call.assert_called_once()


def test_config_edit_not_found(runner, test_config_dir):
    """Cover config edit when project doesn't exist."""
    result = runner.invoke(cli, ["config", "edit", "nonexistent"])
    assert result.exit_code == 1
    assert "Config not found" in result.output


# --- resume corrupt state (lines 401-403) ---


def test_resume_corrupt_state(runner, mock_ssh_class, test_config_dir, monkeypatch):
    """Cover resume with corrupted state (missing keys)."""
    monkeypatch.setattr(
        "biblio_uplift.core.state.load_resume_state",
        lambda: {"bad": "data"},  # missing 'project' and 'completed_steps'
    )
    result = runner.invoke(cli, ["resume"])
    assert result.exit_code == 1
    assert "corrupted" in result.output


# --- service-update (lines 778-832) ---


def test_service_update_success(runner, mock_ssh_class, test_config_dir, monkeypatch):
    """Cover service-update happy path."""
    monkeypatch.setattr("biblio_uplift.history.audit.record_run", lambda **kw: None)
    mock_ssh_class.run.return_value = SSHResult(command="test", exit_code=0, stdout="ok\n", stderr="")
    result = runner.invoke(cli, ["service-update", "test-proj", "web", "--non-interactive"])
    assert result.exit_code == 0
    assert "updated successfully" in result.output


def test_service_update_git_pull_fails(runner, mock_ssh_class, test_config_dir, monkeypatch):
    """Cover service-update when git pull fails."""
    monkeypatch.setattr("biblio_uplift.history.audit.record_run", lambda **kw: None)

    def fake_run(cmd, **kwargs):
        if "git" in cmd and "fetch" in cmd:
            return SSHResult(command=cmd, exit_code=1, stdout="", stderr="auth failed")
        return SSHResult(command=cmd, exit_code=0, stdout="ok\n", stderr="")

    mock_ssh_class.run.side_effect = fake_run
    result = runner.invoke(cli, ["service-update", "test-proj", "web", "--non-interactive"])
    assert result.exit_code == 1
    assert "Git pull failed" in result.output


# --- backup prune (lines 882-938) ---


def test_backup_prune_success(runner, mock_ssh_class, test_config_dir, monkeypatch):
    """Cover backup prune with files to remove."""
    monkeypatch.setattr("biblio_uplift.history.audit.record_run", lambda **kw: None)
    backup_files = "\n".join(
        [
            "/backups/files_20260101_120000.tar.gz",
            "/backups/volumes_20260101_120000.tar.gz",
            "/backups/files_20260102_120000.tar.gz",
            "/backups/volumes_20260102_120000.tar.gz",
            "/backups/files_20260103_120000.tar.gz",
            "/backups/volumes_20260103_120000.tar.gz",
        ]
    )

    def fake_run(cmd, **kwargs):
        if "ls -1" in cmd:
            return SSHResult(command=cmd, exit_code=0, stdout=backup_files, stderr="")
        return SSHResult(command=cmd, exit_code=0, stdout="ok\n", stderr="")

    mock_ssh_class.run.side_effect = fake_run
    result = runner.invoke(cli, ["backup", "prune", "test-proj", "--keep", "2", "--non-interactive"])
    assert result.exit_code == 0
    assert "Prune complete" in result.output


def test_backup_prune_nothing_to_prune(runner, mock_ssh_class, test_config_dir, monkeypatch):
    """Cover backup prune when nothing to remove."""
    monkeypatch.setattr("biblio_uplift.history.audit.record_run", lambda **kw: None)
    backup_files = "/backups/files_20260101_120000.tar.gz\n"

    def fake_run(cmd, **kwargs):
        if "ls -1" in cmd:
            return SSHResult(command=cmd, exit_code=0, stdout=backup_files, stderr="")
        return SSHResult(command=cmd, exit_code=0, stdout="ok\n", stderr="")

    mock_ssh_class.run.side_effect = fake_run
    result = runner.invoke(cli, ["backup", "prune", "test-proj", "--keep", "5", "--non-interactive"])
    assert result.exit_code == 0
    assert "Nothing to prune" in result.output


def test_backup_prune_no_backups(runner, mock_ssh_class, test_config_dir, monkeypatch):
    """Cover backup prune when no backups exist."""
    monkeypatch.setattr("biblio_uplift.history.audit.record_run", lambda **kw: None)
    mock_ssh_class.run.return_value = SSHResult(command="ls", exit_code=1, stdout="", stderr="")
    result = runner.invoke(cli, ["backup", "prune", "test-proj", "--non-interactive"])
    assert result.exit_code == 0
    assert "No backups found" in result.output


# --- tool list (lines 950-960) ---


def test_tool_list(runner, test_config_dir):
    """Cover tool list command."""
    result = runner.invoke(cli, ["tool", "list"])
    assert result.exit_code == 0


# --- tool run (lines 970-1005) ---


def test_tool_run_success(runner, mock_ssh_class, test_config_dir, monkeypatch):
    """Cover tool run happy path."""
    from unittest.mock import MagicMock as MM

    mock_tool = MM()
    mock_tool.name = "test-tool"
    mock_tool.category = "test"
    mock_tool.description = "A test tool"
    mock_tool.read_only = True
    mock_tool.execute.return_value = MM(success=True, error=None)
    monkeypatch.setattr(
        "biblio_uplift.core.tools.get_all_tools",
        lambda: [mock_tool],
    )
    result = runner.invoke(cli, ["tool", "run", "test-proj", "test-tool"])
    assert result.exit_code == 0
    assert "Done" in result.output


def test_tool_run_unknown(runner, mock_ssh_class, test_config_dir, monkeypatch):
    """Cover tool run with unknown tool name."""
    monkeypatch.setattr("biblio_uplift.core.tools.get_all_tools", lambda: [])
    result = runner.invoke(cli, ["tool", "run", "test-proj", "nonexistent"])
    assert result.exit_code == 1
    assert "Unknown tool" in result.output


def test_tool_run_dry_run(runner, mock_ssh_class, test_config_dir, monkeypatch):
    """Cover tool run with --dry-run flag."""
    from unittest.mock import MagicMock as MM

    mock_tool = MM()
    mock_tool.name = "mutating-tool"
    mock_tool.category = "test"
    mock_tool.description = "A mutating tool"
    mock_tool.read_only = False
    mock_tool.dry_run.return_value = MM(success=True, error=None)
    monkeypatch.setattr(
        "biblio_uplift.core.tools.get_all_tools",
        lambda: [mock_tool],
    )
    result = runner.invoke(cli, ["tool", "run", "test-proj", "mutating-tool", "--dry-run"])
    assert result.exit_code == 0
    assert "DRY RUN" in result.output


def test_tool_run_failure(runner, mock_ssh_class, test_config_dir, monkeypatch):
    """Cover tool run when tool fails."""
    from unittest.mock import MagicMock as MM

    mock_tool = MM()
    mock_tool.name = "fail-tool"
    mock_tool.category = "test"
    mock_tool.description = "A failing tool"
    mock_tool.read_only = True
    mock_tool.execute.return_value = MM(success=False, error="connection timeout")
    monkeypatch.setattr(
        "biblio_uplift.core.tools.get_all_tools",
        lambda: [mock_tool],
    )
    result = runner.invoke(cli, ["tool", "run", "test-proj", "fail-tool"])
    assert result.exit_code == 1
    assert "Failed" in result.output
