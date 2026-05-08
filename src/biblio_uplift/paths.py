from __future__ import annotations

import os
from pathlib import Path


def get_config_dir() -> Path:
    """Resolve config directory.

    Resolution order:
    1. $BIBLIO_UPLIFT_CONFIG_DIR
    2. ~/.config/biblio-uplift/configs/ (if exists)
    3. CWD/configs/ (dev/repo fallback)
    4. Error
    """
    env = os.environ.get("BIBLIO_UPLIFT_CONFIG_DIR")
    if env:
        return Path(env).expanduser()

    xdg = Path.home() / ".config" / "biblio-uplift" / "configs"
    if xdg.is_dir():
        return xdg

    cwd_configs = Path.cwd() / "configs"
    if cwd_configs.is_dir():
        return cwd_configs

    raise FileNotFoundError("No config directory found. Run 'biblio-uplift init' or set $BIBLIO_UPLIFT_CONFIG_DIR")


def get_data_dir() -> Path:
    """Resolve data directory (logs, history, state).

    Resolution order:
    1. $BIBLIO_UPLIFT_DATA_DIR
    2. ~/.local/share/biblio-uplift/
    """
    env = os.environ.get("BIBLIO_UPLIFT_DATA_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".local" / "share" / "biblio-uplift"


def get_examples_dir() -> Path:
    """Return path to bundled example configs (inside the installed package)."""
    return Path(__file__).parent / "examples"
