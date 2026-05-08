from unittest.mock import MagicMock

import pytest

from biblio_uplift.config.schema import ProjectConfig
from biblio_uplift.core.pipeline import PipelineContext
from biblio_uplift.core.ssh import SSHResult


@pytest.fixture(autouse=True)
def _reset_audit_connection():
    """Reset the audit module's thread-local DB connection between tests."""
    import biblio_uplift.history.audit as audit

    if hasattr(audit._local, "conn"):
        audit._local.conn.close()
        del audit._local.conn
    yield
    if hasattr(audit._local, "conn"):
        audit._local.conn.close()
        del audit._local.conn


@pytest.fixture
def mock_ssh():
    ssh = MagicMock()
    ssh.run.return_value = SSHResult(command="test", exit_code=0, stdout="ok\n", stderr="")
    ssh.test_connection.return_value = SSHResult(command="echo ok", exit_code=0, stdout="ok", stderr="")
    ssh.cancel_event = None
    return ssh


@pytest.fixture
def mock_config(tmp_path):
    key = tmp_path / "fake.pem"
    key.write_text("fake")
    return ProjectConfig(
        name="test-project",
        ssh_host="test.example.com",
        project_dir=str(tmp_path),
        ssh_key=str(key),
        backup_dir=str(tmp_path / "backups"),
        volumes=["test_vol"],
        healthcheck_urls=["https://test.example.com"],
        healthcheck_timeout=5,
        extra_backup_paths=[str(tmp_path / "extra")],
    )


@pytest.fixture
def mock_ctx(mock_ssh, mock_config):
    output_lines = []
    return PipelineContext(
        config=mock_config,
        ssh=mock_ssh,
        on_output=output_lines.append,
    )
