"""Pipeline state persistence for resume after reboot."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from biblio_uplift.paths import get_data_dir

logger = logging.getLogger(__name__)

STATE_FILE = "resume-state.json"


def get_state_path() -> Path:
    return get_data_dir() / STATE_FILE


def save_resume_state(
    project: str,
    completed_steps: list[str],
    skip_steps: set[str],
    state: dict[str, Any],
) -> None:
    """Save pipeline state before reboot so it can be resumed."""
    data = {
        "project": project,
        "completed_steps": completed_steps,
        "skip_steps": list(skip_steps),
        "state": state,
    }
    path = get_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    logger.info("Saved resume state to %s", path)


def load_resume_state() -> dict[str, Any] | None:
    """Load saved resume state, or None if no state file exists."""
    path = get_state_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        # Validate required keys
        if not isinstance(data, dict) or "project" not in data or "completed_steps" not in data:
            logger.warning("Resume state missing required keys, ignoring")
            return None
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read resume state: %s", e)
        return None


def clear_resume_state() -> None:
    """Remove the resume state file."""
    path = get_state_path()
    if path.exists():
        path.unlink()
        logger.info("Cleared resume state")
