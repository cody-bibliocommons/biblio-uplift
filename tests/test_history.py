import json
from unittest.mock import patch

from biblio_uplift.history.audit import _rotate_history, read_history, record_run


def _patch_history_path(tmp_path):
    p = tmp_path / "history.jsonl"
    return patch("biblio_uplift.history.audit._get_history_path", return_value=p)


class TestRecordRun:
    def test_creates_file_with_valid_json(self, tmp_path):
        with _patch_history_path(tmp_path):
            record_run("proj", "upgrade", [{"name": "s1", "status": "success"}], True, 12.3, user="tester")
        p = tmp_path / "history.jsonl"
        assert p.exists()
        entry = json.loads(p.read_text().strip())
        assert entry["project"] == "proj"
        assert entry["pipeline"] == "upgrade"
        assert entry["success"] is True
        assert entry["duration_seconds"] == 12.3
        assert entry["user"] == "tester"
        assert "timestamp" in entry


class TestReadHistory:
    def test_returns_entries(self, tmp_path):
        with _patch_history_path(tmp_path):
            record_run("a", "p", [], True, 1.0)
            record_run("b", "p", [], False, 2.0)
            entries = read_history()
        assert len(entries) == 2

    def test_filters_by_project(self, tmp_path):
        with _patch_history_path(tmp_path):
            record_run("a", "p", [], True, 1.0)
            record_run("b", "p", [], True, 1.0)
            record_run("a", "p", [], True, 1.0)
            entries = read_history(project="a")
        assert len(entries) == 2
        assert all(e["project"] == "a" for e in entries)

    def test_last_limit(self, tmp_path):
        with _patch_history_path(tmp_path):
            for i in range(5):
                record_run(f"p{i}", "up", [], True, 1.0)
            entries = read_history(last=2)
        assert len(entries) == 2

    def test_missing_file(self, tmp_path):
        with _patch_history_path(tmp_path):
            assert read_history() == []


class TestRotateHistory:
    def test_keeps_last_n(self, tmp_path):
        p = tmp_path / "history.jsonl"
        # Write 10 entries
        lines = [json.dumps({"project": f"p{i}"}) for i in range(10)]
        p.write_text("\n".join(lines) + "\n")
        with _patch_history_path(tmp_path):
            _rotate_history(max_entries=3)
        remaining = [json.loads(line) for line in p.read_text().strip().splitlines()]
        assert len(remaining) == 3
        # Should keep the last 3
        assert remaining[0]["project"] == "p7"
        assert remaining[2]["project"] == "p9"

    def test_no_rotation_needed(self, tmp_path):
        p = tmp_path / "history.jsonl"
        lines = [json.dumps({"project": f"p{i}"}) for i in range(3)]
        p.write_text("\n".join(lines) + "\n")
        with _patch_history_path(tmp_path):
            _rotate_history(max_entries=10)
        remaining = p.read_text().strip().splitlines()
        assert len(remaining) == 3
