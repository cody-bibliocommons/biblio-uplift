"""Tests for the SQLite-based audit history module."""

from __future__ import annotations

import json

import pytest


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    """Point audit module at a temp directory."""
    monkeypatch.setenv("BIBLIO_UPLIFT_DATA_DIR", str(tmp_path))
    yield tmp_path


def test_schema_creation(_isolate_db):
    """Schema is created on first connection."""
    from biblio_uplift.history.audit import _get_connection

    conn = _get_connection()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "runs" in tables
    assert "step_timings" in tables
    assert "tool_executions" in tables
    assert "schema_version" in tables

    version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
    assert version == 1


def test_record_run_and_read_history():
    """Round-trip: record a run and read it back."""
    from biblio_uplift.history.audit import read_history, record_run

    steps = [
        {"name": "backup", "status": "success", "duration": 2.5},
        {"name": "upgrade", "status": "failed", "duration": 10.1, "exit_code": 1, "stderr_snippet": "oops"},
    ]
    run_id = record_run(
        project="test-proj",
        pipeline="full-upgrade",
        steps=steps,
        success=False,
        duration=12.6,
        user="tester",
        dry_run=True,
        options={"verbose": True},
    )
    assert isinstance(run_id, int)
    assert run_id > 0

    history = read_history(project="test-proj", last=10)
    assert len(history) == 1
    entry = history[0]
    assert entry["project"] == "test-proj"
    assert entry["pipeline"] == "full-upgrade"
    assert entry["user"] == "tester"
    assert entry["success"] is False
    assert entry["dry_run"] is True
    assert entry["duration_seconds"] == 12.6
    assert entry["options"] == {"verbose": True}
    assert len(entry["steps"]) == 2
    assert entry["steps"][0]["name"] == "backup"
    assert entry["steps"][1]["exit_code"] == 1
    assert entry["steps"][1]["stderr_snippet"] == "oops"


def test_read_history_limit():
    """read_history respects the last parameter."""
    from biblio_uplift.history.audit import read_history, record_run

    for i in range(5):
        record_run(project="proj", pipeline="p", steps=[], success=True, duration=1.0)

    assert len(read_history(last=3)) == 3
    assert len(read_history(last=10)) == 5


def test_read_history_project_filter():
    """read_history filters by project."""
    from biblio_uplift.history.audit import read_history, record_run

    record_run(project="alpha", pipeline="p", steps=[], success=True, duration=1.0)
    record_run(project="beta", pipeline="p", steps=[], success=True, duration=1.0)

    assert len(read_history(project="alpha")) == 1
    assert len(read_history(project="beta")) == 1
    assert len(read_history()) == 2


def test_record_tool_execution():
    """record_tool_execution inserts correctly."""
    from biblio_uplift.history.audit import _get_connection, record_tool_execution

    record_tool_execution(
        project="proj",
        tool_name="disk-check",
        success=True,
        duration=0.5,
        dry_run=False,
        error="",
    )
    record_tool_execution(
        project="proj",
        tool_name="restart",
        success=False,
        duration=3.2,
        dry_run=True,
        error="timeout",
    )

    conn = _get_connection()
    rows = conn.execute("SELECT * FROM tool_executions ORDER BY id").fetchall()
    assert len(rows) == 2
    assert rows[0]["tool_name"] == "disk-check"
    assert rows[0]["success"] == 1
    assert rows[1]["error"] == "timeout"
    assert rows[1]["dry_run"] == 1


def test_get_analytics_with_data():
    """get_analytics returns correct aggregations."""
    from biblio_uplift.history.audit import get_analytics, record_run, record_tool_execution

    # Seed runs
    record_run(
        project="proj-a",
        pipeline="p",
        steps=[
            {"name": "step1", "status": "success", "duration": 5.0},
            {"name": "step2", "status": "failed", "duration": 2.0},
        ],
        success=False,
        duration=7.0,
    )
    record_run(
        project="proj-a",
        pipeline="p",
        steps=[
            {"name": "step1", "status": "success", "duration": 3.0},
        ],
        success=True,
        duration=3.0,
    )
    record_run(project="proj-b", pipeline="p", steps=[], success=True, duration=1.0)

    # Seed tool executions
    record_tool_execution(project="proj-a", tool_name="check", success=True, duration=0.1)
    record_tool_execution(project="proj-a", tool_name="check", success=False, duration=0.2, error="fail")

    analytics = get_analytics(days=30)
    assert analytics["total_runs"] == 3
    assert analytics["success_rate"] == pytest.approx(66.7, abs=0.1)
    assert analytics["avg_duration"] == pytest.approx(3.67, abs=0.1)
    assert len(analytics["failure_rate_by_project"]) == 2
    assert any(p["project"] == "proj-a" and p["failures"] == 1 for p in analytics["failure_rate_by_project"])
    assert len(analytics["slowest_steps"]) > 0
    assert analytics["common_failure_steps"][0]["step_name"] == "step2"
    assert analytics["common_failure_steps"][0]["count"] == 1
    assert len(analytics["tool_stats"]) == 1
    assert analytics["tool_stats"][0]["tool_name"] == "check"
    assert analytics["tool_stats"][0]["uses"] == 2
    assert analytics["tool_stats"][0]["success_rate"] == 50.0


def test_get_analytics_project_filter():
    """get_analytics filters by project."""
    from biblio_uplift.history.audit import get_analytics, record_run

    record_run(project="alpha", pipeline="p", steps=[], success=True, duration=1.0)
    record_run(project="beta", pipeline="p", steps=[], success=False, duration=2.0)

    a = get_analytics(project="alpha")
    assert a["total_runs"] == 1
    assert a["success_rate"] == 100.0


def test_get_analytics_empty_db():
    """get_analytics handles empty database gracefully."""
    from biblio_uplift.history.audit import get_analytics

    analytics = get_analytics()
    assert analytics["total_runs"] == 0
    assert analytics["success_rate"] == 0.0
    assert analytics["avg_duration"] == 0.0
    assert analytics["runs_per_week"] == 0.0
    assert analytics["failure_rate_by_project"] == []
    assert analytics["slowest_steps"] == []
    assert analytics["common_failure_steps"] == []
    assert analytics["tool_stats"] == []


def test_read_history_empty_db():
    """read_history returns empty list on fresh DB."""
    from biblio_uplift.history.audit import read_history

    assert read_history() == []
    assert read_history(project="nonexistent") == []


def test_migration_from_jsonl(_isolate_db):
    """Migrates existing history.jsonl into SQLite."""
    import biblio_uplift.history.audit as audit

    # Reset connection to start fresh
    if hasattr(audit._local, "conn"):
        audit._local.conn.close()
        del audit._local.conn

    tmp_path = _isolate_db
    jsonl_path = tmp_path / "history.jsonl"
    entries = [
        {
            "timestamp": "2025-01-01T00:00:00+00:00",
            "project": "migrated-proj",
            "pipeline": "upgrade",
            "user": "admin",
            "success": True,
            "dry_run": False,
            "duration_seconds": 45.2,
            "options": {"flag": "value"},
            "steps": [
                {"name": "backup", "status": "success", "duration": 10.0},
                {"name": "apply", "status": "success", "duration": 35.2},
            ],
        },
        {
            "timestamp": "2025-01-02T00:00:00+00:00",
            "project": "migrated-proj",
            "pipeline": "rollback",
            "user": "admin",
            "success": False,
            "dry_run": True,
            "duration_seconds": 5.0,
            "options": {},
            "steps": [],
        },
    ]
    with open(jsonl_path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    # Trigger connection which should migrate
    from biblio_uplift.history.audit import read_history

    history = read_history()

    assert len(history) == 2
    assert history[0]["project"] == "migrated-proj"
    assert history[0]["pipeline"] == "upgrade"
    assert len(history[0]["steps"]) == 2
    assert history[1]["success"] is False

    # JSONL should be renamed
    assert not jsonl_path.exists()
    assert (tmp_path / "history.jsonl.migrated").exists()
