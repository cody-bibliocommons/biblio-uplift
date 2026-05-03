from __future__ import annotations

import os
from pathlib import Path

_project_root: Path | None = None


def get_project_root() -> Path:
    """Find the project root directory."""
    global _project_root
    if _project_root is not None:
        return _project_root

    # 1. Environment variable override
    env = os.environ.get("ITOPS_UPGRADE_DIR")
    if env:
        _project_root = Path(env)
        return _project_root

    # 2. Walk up from this file looking for .git or configs/
    current = Path(__file__).resolve().parent
    for _ in range(5):
        if (current / "configs").is_dir() or (current / ".git").is_dir():
            _project_root = current
            return _project_root
        current = current.parent

    # 3. Fallback to cwd
    _project_root = Path.cwd()
    return _project_root
