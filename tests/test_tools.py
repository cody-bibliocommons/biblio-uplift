from unittest.mock import MagicMock

from biblio_uplift.core.ssh import SSHResult
from biblio_uplift.core.tools import ToolResult, get_all_tools


def _mock_ssh():
    ssh = MagicMock()
    ssh.run.return_value = SSHResult(command="test", exit_code=0, stdout="ok\n", stderr="")
    return ssh


def _mock_config():
    config = MagicMock()
    config.project_dir = "/opt/docker/test"
    config.compose_command = "docker compose"
    config.compose_files = ["docker-compose.yml"]
    config.compose_profile = None
    config.healthcheck_urls = ["https://example.com/health"]
    return config


def test_get_all_tools():
    tools = get_all_tools()
    assert len(tools) == 16
    names = [t.name for t in tools]
    assert "pending-security-updates" in names
    assert "journald-config" in names
    assert "container-logs" in names
    assert "dns-resolution" in names
    assert "sudo-users" in names


def test_tool_categories():
    tools = get_all_tools()
    categories = {t.category for t in tools}
    assert "security" in categories
    assert "system" in categories
    assert "docker" in categories
    assert "Network" in categories
    assert "Users & Access" in categories


def test_read_only_tools():
    tools = get_all_tools()
    read_only = [t for t in tools if t.read_only]
    mutating = [t for t in tools if not t.read_only]
    assert len(read_only) == 11  # 3 security + container-logs + compose-pull-check + 3 network + 3 users
    assert len(mutating) == 5  # journald, logrotate, fix-permissions, restart, freeipa-logs


def test_tool_execute_with_mock_ssh():
    tools = get_all_tools()
    for tool in tools:
        ssh = _mock_ssh()
        config = _mock_config()
        output = []
        result = tool.execute(ssh, config, output.append)
        assert isinstance(result, ToolResult)
        assert result.success is True


def test_mutating_tool_dry_run():
    tools = get_all_tools()
    for tool in tools:
        if not tool.read_only:
            ssh = _mock_ssh()
            config = _mock_config()
            output = []
            result = tool.dry_run(ssh, config, output.append)
            assert isinstance(result, ToolResult)


def test_tool_execute_failure():
    tools = get_all_tools()
    tool = next(t for t in tools if t.name == "open-ports-audit")
    ssh = _mock_ssh()
    ssh.run.return_value = SSHResult(command="ss", exit_code=1, stdout="", stderr="error")
    config = _mock_config()
    result = tool.execute(ssh, config, lambda x: None)
    assert result.success is False


def test_all_tools_have_metadata():
    for tool in get_all_tools():
        assert tool.name, f"Tool missing name: {tool}"
        assert tool.category, f"Tool missing category: {tool}"
        assert tool.description, f"Tool missing description: {tool}"
