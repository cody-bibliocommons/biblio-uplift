"""Tests for history audit module (SQLite backend)."""

from __future__ import annotations

import pytest

from biblio_uplift.history.audit import read_history, record_run


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    monkeypatch.setenv("BIBLIO_UPLIFT_DATA_DIR", str(tmp_path))


class TestRecordRun:
    def test_creates_db_with_valid_data(self):
        run_id = record_run(
            "proj", "upgrade", [{"name": "s1", "status": "success", "duration": 1.0}], True, 12.3, user="tester"
        )
        assert isinstance(run_id, int)
        entries = read_history()
        assert len(entries) == 1
        entry = entries[0]
        assert entry["project"] == "proj"
        assert entry["pipeline"] == "upgrade"
        assert entry["success"] is True
        assert entry["duration_seconds"] == 12.3
        assert entry["user"] == "tester"
        assert "timestamp" in entry


class TestReadHistory:
    def test_returns_entries(self):
        record_run("a", "p", [], True, 1.0)
        record_run("b", "p", [], False, 2.0)
        entries = read_history()
        assert len(entries) == 2

    def test_filters_by_project(self):
        record_run("a", "p", [], True, 1.0)
        record_run("b", "p", [], True, 1.0)
        record_run("a", "p", [], True, 1.0)
        entries = read_history(project="a")
        assert len(entries) == 2
        assert all(e["project"] == "a" for e in entries)

    def test_last_limit(self):
        for i in range(5):
            record_run(f"p{i}", "up", [], True, 1.0)
        entries = read_history(last=2)
        assert len(entries) == 2

    def test_empty_db(self):
        assert read_history() == []
