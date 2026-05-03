from __future__ import annotations

import logging
import select
import socket
import subprocess  # nosec B404 - required for SSH command execution
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SSHResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration: float = 0.0

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class SSHRunner:
    """Execute commands on a remote host via SSH."""

    def __init__(
        self,
        host: str,
        user: str,
        key_path: str | Path,
        sudo: bool = True,
        connect_timeout: int = 10,
        port: int = 22,
    ):
        self.host = host
        self.user = user
        self.key_path = Path(key_path).expanduser()
        if not self.key_path.exists():
            raise FileNotFoundError(f"SSH key not found: {self.key_path}")
        logger.debug(
            "SSH key %s will be used with BatchMode=yes (passphrase-protected keys require ssh-agent)",
            self.key_path,
        )
        self.cancel_event: threading.Event | None = None
        self.sudo = sudo
        self.connect_timeout = connect_timeout
        self.port = port

    def _build_ssh_cmd(self, command: str) -> list[str]:
        """Build the ssh command list."""
        remote_cmd = f"sudo {command}" if self.sudo else command
        return [
            "ssh",
            "-i",
            str(self.key_path),
            "-p",
            str(self.port),
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={self.connect_timeout}",
            f"{self.user}@{self.host}",
            remote_cmd,
        ]

    def run(
        self,
        command: str,
        timeout: int = 300,
        on_output: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> SSHResult:
        """Run a command on the remote host.

        Args:
            command: Shell command to execute remotely.
            timeout: Max seconds to wait.
            on_output: Optional callback for real-time stdout lines (for TUI log panel).
            cancel_event: Optional threading.Event; if set, the command is terminated.
        """
        cancel_event = self.cancel_event or cancel_event
        ssh_cmd = self._build_ssh_cmd(command)
        logger.debug("SSH: %s", " ".join(ssh_cmd))

        start = time.monotonic()
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        try:
            proc = subprocess.Popen(  # nosec B603 - SSH command built from validated inputs
                ssh_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            if proc.stdout is None or proc.stderr is None:
                raise RuntimeError("Failed to open subprocess pipes")

            def _read_stderr():
                if proc.stderr is not None:
                    stderr_lines.extend(proc.stderr.read().splitlines())

            stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
            stderr_thread.start()

            # Stream stdout line by line, checking for cancellation
            while True:
                if cancel_event and cancel_event.is_set():
                    proc.terminate()
                    proc.wait(timeout=5)
                    duration = time.monotonic() - start
                    return SSHResult(
                        command=command,
                        exit_code=-2,
                        stdout="\n".join(stdout_lines),
                        stderr="Cancelled by user",
                        duration=duration,
                    )
                # Use select to check if stdout has data (1s timeout)
                ready, _, _ = select.select([proc.stdout], [], [], 1.0)
                if ready:
                    line = proc.stdout.readline()
                    if not line:
                        break  # EOF
                    line = line.rstrip("\n")
                    stdout_lines.append(line)
                    if on_output:
                        on_output(line)
                elif proc.poll() is not None:
                    # Process finished, read remaining
                    for line in proc.stdout:
                        line = line.rstrip("\n")
                        stdout_lines.append(line)
                        if on_output:
                            on_output(line)
                    break

            proc.wait(timeout=timeout)
            stderr_thread.join(timeout=5)

        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            duration = time.monotonic() - start
            return SSHResult(
                command=command,
                exit_code=-1,
                stdout="\n".join(stdout_lines),
                stderr=f"Command timed out after {timeout}s",
                duration=duration,
            )
        except Exception as e:
            duration = time.monotonic() - start
            return SSHResult(
                command=command,
                exit_code=-1,
                stdout="\n".join(stdout_lines),
                stderr=str(e),
                duration=duration,
            )

        duration = time.monotonic() - start
        result = SSHResult(
            command=command,
            exit_code=proc.returncode,
            stdout="\n".join(stdout_lines),
            stderr="\n".join(stderr_lines),
            duration=duration,
        )

        if result.ok:
            logger.debug("SSH OK (%.1fs): %s", duration, command)
        else:
            logger.warning(
                "SSH FAIL (exit=%d, %.1fs): %s\nstderr: %s",
                result.exit_code,
                duration,
                command,
                result.stderr,
            )

        return result

    def test_connection(self) -> SSHResult:
        """Test SSH connectivity."""
        return self.run("echo ok", timeout=15)

    def wait_for_reboot(self, timeout: int = 300, poll_interval: int = 5) -> bool:
        """Wait for host to come back after reboot.

        Returns True if host is reachable again within timeout.
        """
        logger.info("Waiting for %s to come back after reboot...", self.host)
        time.sleep(5)  # Give the server time to start shutting down

        # Wait for SSH to go down
        down_deadline = time.monotonic() + 30
        while time.monotonic() < down_deadline:
            if not self._is_port_open():
                break
            time.sleep(2)

        # Now wait for SSH to come back
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(poll_interval)
            if self._is_port_open():
                # Port is open, try actual SSH
                time.sleep(3)  # give sshd a moment to fully start
                result = self.test_connection()
                if result.ok:
                    logger.info("%s is back up.", self.host)
                    return True

        logger.error("%s did not come back within %ds.", self.host, timeout)
        return False

    def _is_port_open(self, port: int | None = None) -> bool:
        """Check if a TCP port is open on the remote host."""
        port = port or self.port
        try:
            with socket.create_connection((self.host, port), timeout=3):
                return True
        except (OSError, ConnectionRefusedError):
            return False
