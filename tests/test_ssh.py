import subprocess
import threading
from unittest.mock import MagicMock, patch

import pytest

from biblio_uplift.core.ssh import SSHResult, SSHRunner


class TestSSHResult:
    def test_ok_true(self):
        r = SSHResult(command="x", exit_code=0, stdout="", stderr="")
        assert r.ok is True

    def test_ok_false(self):
        r = SSHResult(command="x", exit_code=1, stdout="", stderr="err")
        assert r.ok is False


class TestSSHRunnerInit:
    def test_missing_key_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="SSH key not found"):
            SSHRunner(host="h", user="u", key_path=tmp_path / "nope.pem")

    def test_valid_key(self, tmp_path):
        key = tmp_path / "ok.pem"
        key.write_text("k")
        runner = SSHRunner(host="h", user="u", key_path=key)
        assert runner.host == "h"
        assert runner.sudo is True


class TestBuildSSHCmd:
    @pytest.fixture
    def runner(self, tmp_path):
        key = tmp_path / "k.pem"
        key.write_text("k")
        return SSHRunner(host="h", user="u", key_path=key, sudo=True)

    def test_sudo_true(self, runner):
        cmd = runner._build_ssh_cmd("ls /root")
        assert cmd[-1] == "sudo ls /root"
        assert "u@h" in cmd

    def test_sudo_false(self, tmp_path):
        key = tmp_path / "k.pem"
        key.write_text("k")
        runner = SSHRunner(host="h", user="u", key_path=key, sudo=False)
        cmd = runner._build_ssh_cmd("ls /root", use_sudo=False)
        assert cmd[-1] == "ls /root"


class TestSSHRunnerRun:
    @pytest.fixture
    def runner(self, tmp_path):
        key = tmp_path / "k.pem"
        key.write_text("k")
        return SSHRunner(host="h", user="u", key_path=key)

    def _mock_popen(self, stdout="ok\n", stderr="", returncode=0):
        proc = MagicMock()
        proc.stdout = MagicMock()
        proc.stdout.__iter__ = MagicMock(return_value=iter([]))
        proc.stdout.readline.side_effect = [stdout, ""]
        proc.stdout.fileno = MagicMock(return_value=0)
        proc.stderr = MagicMock()
        proc.stderr.read.return_value = stderr
        proc.returncode = returncode
        proc.poll.return_value = returncode
        proc.wait.return_value = returncode
        return proc

    @patch("biblio_uplift.core.ssh.select.select")
    @patch("biblio_uplift.core.ssh.subprocess.Popen")
    def test_run_success(self, mock_popen_cls, mock_select, runner):
        proc = self._mock_popen(stdout="hello\n", returncode=0)
        mock_popen_cls.return_value = proc
        # First select returns ready, readline returns line; second returns ready, readline returns "" (EOF)
        mock_select.side_effect = [([proc.stdout], [], []), ([proc.stdout], [], [])]
        proc.stdout.readline.side_effect = ["hello\n", ""]

        result = runner.run("echo hello")
        assert result.ok
        assert result.exit_code == 0
        assert "hello" in result.stdout

    @patch("biblio_uplift.core.ssh.select.select")
    @patch("biblio_uplift.core.ssh.subprocess.Popen")
    def test_run_failure(self, mock_popen_cls, mock_select, runner):
        proc = self._mock_popen(stdout="", stderr="bad", returncode=1)
        mock_popen_cls.return_value = proc
        mock_select.side_effect = [([proc.stdout], [], [])]
        proc.stdout.readline.return_value = ""

        result = runner.run("fail")
        assert not result.ok
        assert result.exit_code == 1

    @patch("biblio_uplift.core.ssh.select.select")
    @patch("biblio_uplift.core.ssh.subprocess.Popen")
    def test_run_timeout(self, mock_popen_cls, mock_select, runner):
        proc = self._mock_popen(returncode=0)
        mock_popen_cls.return_value = proc
        mock_select.return_value = ([proc.stdout], [], [])
        proc.stdout.readline.return_value = ""
        # First wait(timeout=) raises TimeoutExpired; second wait() in except block succeeds
        proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="x", timeout=1), None]

        result = runner.run("slow", timeout=1)
        assert result.exit_code == -1
        assert "timed out" in result.stderr.lower()
        proc.kill.assert_called_once()

    @patch("biblio_uplift.core.ssh.select.select")
    @patch("biblio_uplift.core.ssh.subprocess.Popen")
    def test_run_on_output_callback(self, mock_popen_cls, mock_select, runner):
        proc = self._mock_popen(stdout="line1\n", returncode=0)
        mock_popen_cls.return_value = proc
        mock_select.side_effect = [([proc.stdout], [], []), ([proc.stdout], [], [])]
        proc.stdout.readline.side_effect = ["line1\n", ""]

        lines = []
        result = runner.run("echo line1", on_output=lines.append)
        assert result.ok
        assert "line1" in lines

    @patch("biblio_uplift.core.ssh.select.select")
    @patch("biblio_uplift.core.ssh.subprocess.Popen")
    def test_run_cancel_event(self, mock_popen_cls, mock_select, runner):
        proc = self._mock_popen(returncode=0)
        mock_popen_cls.return_value = proc
        cancel = threading.Event()
        cancel.set()  # Already cancelled
        # select returns empty (1s timeout), then cancel is checked
        mock_select.return_value = ([], [], [])

        result = runner.run("long", cancel_event=cancel)
        assert result.exit_code == -2
        assert "cancelled" in result.stderr.lower()
        proc.terminate.assert_called_once()

    @patch("biblio_uplift.core.ssh.select.select")
    @patch("biblio_uplift.core.ssh.subprocess.Popen")
    def test_run_exception(self, mock_popen_cls, mock_select, runner):
        mock_popen_cls.side_effect = OSError("connection refused")
        result = runner.run("anything")
        assert result.exit_code == -1
        assert "connection refused" in result.stderr


class TestSSHRunnerTestConnection:
    @patch("biblio_uplift.core.ssh.select.select")
    @patch("biblio_uplift.core.ssh.subprocess.Popen")
    def test_test_connection(self, mock_popen_cls, mock_select, tmp_path):
        key = tmp_path / "k.pem"
        key.write_text("k")
        runner = SSHRunner(host="h", user="u", key_path=key)

        proc = MagicMock()
        proc.stdout = MagicMock()
        proc.stdout.fileno = MagicMock(return_value=0)
        proc.stdout.readline.side_effect = ["ok\n", ""]
        proc.stderr = MagicMock()
        proc.stderr.read.return_value = ""
        proc.returncode = 0
        proc.poll.return_value = 0
        proc.wait.return_value = 0
        mock_popen_cls.return_value = proc
        mock_select.side_effect = [([proc.stdout], [], []), ([proc.stdout], [], [])]

        result = runner.test_connection()
        assert result.ok
        # Verify the command passed to run was "echo ok"
        built_cmd = mock_popen_cls.call_args[0][0]
        assert built_cmd[-1] == "sudo echo ok"


class TestIsPortOpen:
    def test_port_open(self, tmp_path):
        key = tmp_path / "k.pem"
        key.write_text("k")
        runner = SSHRunner(host="h", user="u", key_path=key)
        with patch("biblio_uplift.core.ssh.socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = MagicMock()
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            assert runner._is_port_open(22) is True

    def test_port_closed(self, tmp_path):
        key = tmp_path / "k.pem"
        key.write_text("k")
        runner = SSHRunner(host="h", user="u", key_path=key)
        with patch("biblio_uplift.core.ssh.socket.create_connection", side_effect=OSError):
            assert runner._is_port_open(22) is False


class TestCustomPort:
    def test_build_ssh_cmd_with_custom_port(self, tmp_path):
        key = tmp_path / "k.pem"
        key.write_text("k")
        runner = SSHRunner(host="h", user="u", key_path=key, port=2222)
        cmd = runner._build_ssh_cmd("ls")
        assert "-p" in cmd
        assert "2222" in cmd

    def test_is_port_open_uses_configured_port(self, tmp_path):
        key = tmp_path / "k.pem"
        key.write_text("k")
        runner = SSHRunner(host="h", user="u", key_path=key, port=2222)
        with patch("biblio_uplift.core.ssh.socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = MagicMock()
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            runner._is_port_open()
            mock_conn.assert_called_with(("h", 2222), timeout=3)
