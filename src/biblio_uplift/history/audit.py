from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _get_history_path() -> Path:
    """Get the history file path."""
    from biblio_uplift.paths import get_project_root

    path = get_project_root() / "logs" / "history.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def record_run(
    project: str,
    pipeline: str,
    steps: list[dict[str, Any]],
    success: bool,
    duration: float,
    user: str | None = None,
) -> None:
    """Append a run record to the history file."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "project": project,
        "pipeline": pipeline,
        "user": user or os.environ.get("USER", "unknown"),
        "success": success,
        "duration_seconds": round(duration, 1),
        "steps": steps,
    }

    path = _get_history_path()
    with open(path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(entry) + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)

    logger.info("Recorded run for %s in %s", project, path)
    try:
        _rotate_history()
    except Exception as e:
        logger.warning("History rotation failed: %s", e)


def _rotate_history(max_entries: int = 500) -> None:
    path = _get_history_path()
    if not path.exists():
        return
    lock_path = path.with_suffix(".lock")
    try:
        lock_fd = open(lock_path, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return  # Another process is rotating, skip
    try:
        lines = path.read_text().splitlines()
        if len(lines) > max_entries:
            fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as tf:
                    tf.write("\n".join(lines[-max_entries:]) + "\n")
                os.replace(tmp, path)
            except Exception:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
                raise
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def read_history(
    project: str | None = None,
    last: int = 20,
) -> list[dict[str, Any]]:
    """Read recent history entries."""
    path = _get_history_path()
    if not path.exists():
        return []

    entries: list[dict[str, Any]] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if project and entry.get("project") != project:
                    continue
                entries.append(entry)
            except json.JSONDecodeError:
                continue

    return entries[-last:]
