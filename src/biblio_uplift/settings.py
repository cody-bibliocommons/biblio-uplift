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
    "config_repo_path": "configs",
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


def detect_editor(settings: dict[str, object] | None = None) -> str:
    """Return the configured editor, $EDITOR, or detect from installed programs."""
    if settings is None:
        settings = load_settings()

    # 1. Explicit setting
    if settings.get("editor"):
        return str(settings["editor"])

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
    """Clone or pull the config repo, then copy configs to the config dir."""
    if settings is None:
        settings = load_settings()

    url = str(settings.get("config_repo_url", "")).strip()
    if not url:
        return "No config_repo_url configured"

    url = normalize_git_url(url)
    branch = str(settings.get("config_repo_branch", "main"))
    key_path = Path(str(settings.get("config_repo_ssh_key", "~/.ssh/id_ed25519"))).expanduser()
    repo_path = str(settings.get("config_repo_path") or "configs").strip()

    # Clone/pull into a cache directory (separate from config dir)
    from biblio_uplift.paths import get_data_dir

    cache_dir = get_data_dir() / "config-repo"
    cache_dir.mkdir(parents=True, exist_ok=True)

    env_ssh = f"ssh -i {key_path} -o StrictHostKeyChecking=accept-new"
    env = {**os.environ, "GIT_SSH_COMMAND": env_ssh}

    try:
        if (cache_dir / ".git").is_dir():
            subprocess.run(
                ["git", "-C", str(cache_dir), "pull", "origin", branch],
                env=env,
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
        else:
            subprocess.run(
                ["git", "clone", "-b", branch, url, str(cache_dir)],
                env=env,
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
            )
    except subprocess.CalledProcessError as e:
        logger.error("Config repo sync failed: %s", e.stderr)
        return f"Sync failed: {e.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return "Sync timed out"

    # Copy configs from repo subdirectory to config dir
    source = cache_dir / repo_path if repo_path else cache_dir
    if not source.is_dir():
        return f"Path '{repo_path}' not found in repo"

    try:
        from biblio_uplift.paths import get_config_dir

        dest = get_config_dir()
    except FileNotFoundError:
        dest = Path.home() / ".config" / "biblio-uplift" / "configs"
    dest.mkdir(parents=True, exist_ok=True)

    count = 0
    for yml in source.glob("*.yml"):
        shutil.copy2(yml, dest / yml.name)
        count += 1

    return f"Synced {count} configs from {branch}/{repo_path}"
