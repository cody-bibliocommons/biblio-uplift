from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_local = threading.local()
_SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    project TEXT NOT NULL,
    pipeline TEXT NOT NULL,
    user TEXT NOT NULL,
    success INTEGER NOT NULL,
    dry_run INTEGER NOT NULL DEFAULT 0,
    duration_seconds REAL NOT NULL,
    options TEXT DEFAULT '{}',
    error_message TEXT DEFAULT '',
    git_hash_before TEXT DEFAULT '',
    git_hash_after TEXT DEFAULT '',
    disk_avail_mb INTEGER DEFAULT NULL,
    backup_size_bytes INTEGER DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project);
CREATE INDEX IF NOT EXISTS idx_runs_timestamp ON runs(timestamp);

CREATE TABLE IF NOT EXISTS step_timings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    step_name TEXT NOT NULL,
    status TEXT NOT NULL,
    duration_seconds REAL NOT NULL DEFAULT 0,
    exit_code INTEGER DEFAULT NULL,
    stderr_snippet TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_steps_run_id ON step_timings(run_id);

CREATE TABLE IF NOT EXISTS tool_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    project TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    success INTEGER NOT NULL,
    dry_run INTEGER NOT NULL DEFAULT 0,
    duration_seconds REAL NOT NULL DEFAULT 0,
    error TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_tools_project ON tool_executions(project);

CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
"""


def _get_db_path() -> Path:
    from biblio_uplift.paths import get_data_dir

    return get_data_dir() / "history.db"


def _get_connection() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn

    db_path = _get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row

    # Create schema if needed
    version = None
    try:
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        if row:
            version = row[0]
    except sqlite3.OperationalError:
        pass

    if version is None:
        conn.executescript(_SCHEMA_SQL)
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (_SCHEMA_VERSION,))
        conn.commit()
        _migrate_jsonl(conn)

    _local.conn = conn
    return conn


def _migrate_jsonl(conn: sqlite3.Connection) -> None:
    from biblio_uplift.paths import get_data_dir

    jsonl_path = get_data_dir() / "history.jsonl"
    if not jsonl_path.exists():
        return

    logger.info("Migrating %s to SQLite", jsonl_path)
    count = 0
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            cur = conn.execute(
                """INSERT INTO runs (timestamp, project, pipeline, user, success, dry_run,
                   duration_seconds, options)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.get("timestamp", ""),
                    entry.get("project", ""),
                    entry.get("pipeline", ""),
                    entry.get("user", "unknown"),
                    int(entry.get("success", False)),
                    int(entry.get("dry_run", False)),
                    entry.get("duration_seconds", 0),
                    json.dumps(entry.get("options", {})),
                ),
            )
            run_id = cur.lastrowid
            if run_id is None: raise RuntimeError("lastrowid was None after INSERT")
            for step in entry.get("steps", []):
                conn.execute(
                    """INSERT INTO step_timings (run_id, step_name, status, duration_seconds,
                       exit_code, stderr_snippet)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        run_id,
                        step.get("name", ""),
                        step.get("status", ""),
                        step.get("duration", 0),
                        step.get("exit_code"),
                        step.get("stderr_snippet", ""),
                    ),
                )
            count += 1

    conn.commit()
    jsonl_path.rename(jsonl_path.with_suffix(".jsonl.migrated"))
    logger.info("Migrated %d entries from JSONL to SQLite", count)


def record_run(
    project: str,
    pipeline: str,
    steps: list[dict[str, Any]],
    success: bool,
    duration: float,
    user: str | None = None,
    dry_run: bool = False,
    options: dict[str, Any] | None = None,
) -> int:
    """Record a pipeline run. Returns the run_id."""
    conn = _get_connection()
    cur = conn.execute(
        """INSERT INTO runs (timestamp, project, pipeline, user, success, dry_run,
           duration_seconds, options)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now(timezone.utc).isoformat(),
            project,
            pipeline,
            user or os.environ.get("USER", "unknown"),
            int(success),
            int(dry_run),
            round(duration, 1),
            json.dumps(options or {}),
        ),
    )
    run_id = cur.lastrowid
    if run_id is None: raise RuntimeError("lastrowid was None after INSERT")
    for step in steps:
        conn.execute(
            """INSERT INTO step_timings (run_id, step_name, status, duration_seconds,
               exit_code, stderr_snippet)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                step.get("name", ""),
                step.get("status", ""),
                step.get("duration", 0),
                step.get("exit_code"),
                step.get("stderr_snippet", ""),
            ),
        )
    conn.commit()
    logger.info("Recorded run %d for %s", run_id, project)
    return run_id


def record_tool_execution(
    project: str,
    tool_name: str,
    success: bool,
    duration: float,
    dry_run: bool = False,
    error: str = "",
) -> None:
    """Record a tool execution."""
    conn = _get_connection()
    conn.execute(
        """INSERT INTO tool_executions (timestamp, project, tool_name, success, dry_run,
           duration_seconds, error)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now(timezone.utc).isoformat(),
            project,
            tool_name,
            int(success),
            int(dry_run),
            round(duration, 3),
            error,
        ),
    )
    conn.commit()


def read_history(
    project: str | None = None,
    last: int = 20,
) -> list[dict[str, Any]]:
    """Read recent history entries, matching the old JSONL format."""
    conn = _get_connection()
    if project:
        rows = conn.execute(
            "SELECT * FROM runs WHERE project = ? ORDER BY id DESC LIMIT ?",
            (project, last),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (last,)).fetchall()

    results = []
    for row in reversed(rows):
        steps = conn.execute(
            "SELECT step_name, status, duration_seconds, exit_code, stderr_snippet "
            "FROM step_timings WHERE run_id = ? ORDER BY id",
            (row["id"],),
        ).fetchall()
        results.append(
            {
                "timestamp": row["timestamp"],
                "project": row["project"],
                "pipeline": row["pipeline"],
                "user": row["user"],
                "success": bool(row["success"]),
                "dry_run": bool(row["dry_run"]),
                "duration_seconds": row["duration_seconds"],
                "options": json.loads(row["options"] or "{}"),
                "steps": [
                    {
                        "name": s["step_name"],
                        "status": s["status"],
                        "duration": s["duration_seconds"],
                        "exit_code": s["exit_code"],
                        "stderr_snippet": s["stderr_snippet"],
                    }
                    for s in steps
                ],
            }
        )
    return results


def get_analytics(
    project: str | None = None,
    days: int = 30,
) -> dict[str, Any]:
    """Return aggregated analytics."""
    conn = _get_connection()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    clauses = ["timestamp >= ?"]
    params: list[Any] = [cutoff]
    if project:
        clauses.append("project = ?")
        params.append(project)
    where = " AND ".join(clauses)

    # Basic stats
    query = (
        "SELECT COUNT(*) as total, SUM(success) as successes, AVG(duration_seconds) as avg_dur FROM runs WHERE " + where
    )
    row = conn.execute(query, params).fetchone()

    total = row["total"] or 0
    successes = row["successes"] or 0
    avg_dur = row["avg_dur"] or 0.0
    success_rate = (successes / total * 100) if total > 0 else 0.0
    runs_per_week = total / max(days / 7, 1)

    # Failure rate by project
    query = (
        "SELECT project, COUNT(*) as total, SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) as failures "
        "FROM runs WHERE " + where + " GROUP BY project"
    )
    failure_rows = conn.execute(query, params).fetchall()
    failure_rate_by_project = [
        {
            "project": r["project"],
            "total": r["total"],
            "failures": r["failures"],
            "pct": round(r["failures"] / r["total"] * 100, 1) if r["total"] > 0 else 0,
        }
        for r in failure_rows
    ]

    # Slowest steps
    query = (
        "SELECT st.step_name, AVG(st.duration_seconds) as avg_seconds "
        "FROM step_timings st JOIN runs r ON st.run_id = r.id "
        "WHERE r." + where + " "
        "GROUP BY st.step_name ORDER BY avg_seconds DESC LIMIT 10"
    )
    slowest = conn.execute(query, params).fetchall()
    slowest_steps = [{"step_name": r["step_name"], "avg_seconds": round(r["avg_seconds"], 2)} for r in slowest]

    # Common failure steps
    query = (
        "SELECT st.step_name, COUNT(*) as count "
        "FROM step_timings st JOIN runs r ON st.run_id = r.id "
        "WHERE r." + where + " AND st.status = 'failed' "
        "GROUP BY st.step_name ORDER BY count DESC LIMIT 10"
    )
    common_failures = conn.execute(query, params).fetchall()
    common_failure_steps = [{"step_name": r["step_name"], "count": r["count"]} for r in common_failures]

    # Tool stats
    tool_clauses = ["timestamp >= ?"]
    tool_params: list[Any] = [cutoff]
    if project:
        tool_clauses.append("project = ?")
        tool_params.append(project)
    tool_where = " AND ".join(tool_clauses)
    query = (
        "SELECT tool_name, COUNT(*) as uses, SUM(success) as successes "
        "FROM tool_executions WHERE " + tool_where + " "
        "GROUP BY tool_name ORDER BY uses DESC"
    )
    tool_rows = conn.execute(query, tool_params).fetchall()
    tool_stats = [
        {
            "tool_name": r["tool_name"],
            "uses": r["uses"],
            "success_rate": round(r["successes"] / r["uses"] * 100, 1) if r["uses"] > 0 else 0,
        }
        for r in tool_rows
    ]

    return {
        "total_runs": total,
        "success_rate": round(success_rate, 1),
        "avg_duration": round(avg_dur, 2),
        "runs_per_week": round(runs_per_week, 1),
        "failure_rate_by_project": failure_rate_by_project,
        "slowest_steps": slowest_steps,
        "common_failure_steps": common_failure_steps,
        "tool_stats": tool_stats,
    }
