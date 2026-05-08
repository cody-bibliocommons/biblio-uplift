"""User settings management for biblio-uplift."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from biblio_uplift.paths import get_settings_path

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, object] = {
    "config_repo_url": "",
    "config_repo_ssh_key": "~/.ssh/id_ed25519",
    "config_repo_branch": "main",
    "config_sync_on_launch": False,
    "default_ssh_key": "~/.ssh/id_ed25519",
    "theme": "dark",
    "analytics_retention_days": 90,
    "default_notification_cmd": "",
    "editor": "",
}


def load_settings() -> dict[str, object]:
    """Load settings from disk, falling back to defaults for missing keys."""
    path = get_settings_path()
    data: dict[str, object] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read settings file, using defaults")
    return {**DEFAULTS, **data}


def save_settings(settings: dict[str, object]) -> None:
    """Persist settings to disk."""
    path = get_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n")


EDITOR_OPTIONS = [
    ("code --wait", "VS Code"),
    ("vim", "Vim"),
    ("nvim", "Neovim"),
    ("nano", "Nano"),
    ("vi", "Vi"),
    ("micro", "Micro"),
    ("helix", "Helix"),
    ("emacs", "Emacs"),
]


def get_available_editors() -> list[tuple[str, str]]:
    """Return list of (command, display_name) for installed editors."""
    available = []
    for cmd, name in EDITOR_OPTIONS:
        binary = cmd.split()[0]
        if shutil.which(binary):
            available.append((cmd, name))
    return available


def detect_editor(settings: dict | None = None) -> str:
    """Return the configured editor, $EDITOR, or detect from installed programs."""
    if settings is None:
        settings = load_settings()

    # 1. Explicit setting
    if settings.get("editor"):
        return settings["editor"]

    # 2. Environment variable
    env_editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if env_editor:
        return env_editor

    # 3. Detect from EDITOR_OPTIONS
    for cmd, _ in EDITOR_OPTIONS:
        binary = cmd.split()[0]
        if shutil.which(binary):
            return cmd

    return "vi"


def normalize_git_url(url: str) -> str:
    """Normalize various git URL formats to a canonical form.

    Handles:
    - 'git clone <url>' prefix
    - 'ssh clone <url>' prefix (non-standard but seen in copy-paste)
    - bare 'host/org/repo' -> 'git@host:org/repo.git'
    - SSH format 'git@host:org/repo.git' (pass-through)
    - HTTPS format 'https://host/org/repo.git' (pass-through)
    """
    url = url.strip()

    # Strip 'git clone ' or 'ssh clone ' prefix
    url = re.sub(r"^(git|ssh)\s+clone\s+", "", url)

    # Already SSH format
    if re.match(r"^git@.+:.+/.+", url):
        return url

    # Already HTTPS
    if re.match(r"^https?://", url):
        return url

    # Bare host/org/repo pattern (no protocol, no git@)
    bare_match = re.match(r"^([^/:@]+)/([^/]+)/([^/]+)$", url)
    if bare_match:
        host, org, repo = bare_match.groups()
        if not repo.endswith(".git"):
            repo += ".git"
        return f"git@{host}:{org}/{repo}"

    return url


def is_https_url(url: str) -> bool:
    """Return True if the URL uses HTTPS protocol."""
    return url.strip().startswith("https://")


def sync_config_repo(settings: dict[str, object] | None = None) -> str:
    """Clone or pull the config repo. Returns status message."""
    if settings is None:
        settings = load_settings()

    repo_url = str(settings.get("config_repo_url", ""))
    if not repo_url:
        return "No config_repo_url configured"

    repo_url = normalize_git_url(repo_url)
    branch = str(settings.get("config_repo_branch", "main"))
    ssh_key = str(settings.get("config_repo_ssh_key", "~/.ssh/id_ed25519"))
    ssh_key_path = Path(ssh_key).expanduser()

    config_dir = Path.home() / ".config" / "biblio-uplift" / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)

    env_extra = {}
    if not is_https_url(repo_url) and ssh_key_path.exists():
        env_extra["GIT_SSH_COMMAND"] = f"ssh -i {ssh_key_path} -o StrictHostKeyChecking=accept-new"

    try:
        if (config_dir / ".git").is_dir():
            # Pull
            result = subprocess.run(
                ["git", "-C", str(config_dir), "pull", "--ff-only", "origin", branch],
                capture_output=True,
                text=True,
                timeout=60,
                env={**__import__("os").environ, **env_extra},
            )
        else:
            # Clone
            result = subprocess.run(
                ["git", "clone", "-b", branch, repo_url, str(config_dir)],
                capture_output=True,
                text=True,
                timeout=60,
                env={**__import__("os").environ, **env_extra},
            )

        if result.returncode == 0:
            return "Sync OK"
        return f"Sync failed: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return "Sync timed out"
    except OSError as e:
        return f"Sync error: {e}"
