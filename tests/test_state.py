"""Tests for the resume state module."""

from biblio_uplift.core.state import clear_resume_state, load_resume_state, save_resume_state


def test_save_and_load(monkeypatch, tmp_path):
    monkeypatch.setattr("biblio_uplift.core.state.get_project_root", lambda: tmp_path)
    (tmp_path / "logs").mkdir(exist_ok=True)
    save_resume_state("test-proj", ["preflight", "backup_files"], {"reboot"}, {"key": "val"})
    state = load_resume_state()
    assert state is not None
    assert state["project"] == "test-proj"
    assert "preflight" in state["completed_steps"]
    assert "reboot" in state["skip_steps"]
    assert state["state"]["key"] == "val"


def test_load_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("biblio_uplift.core.state.get_project_root", lambda: tmp_path)
    (tmp_path / "logs").mkdir(exist_ok=True)
    assert load_resume_state() is None


def test_clear(monkeypatch, tmp_path):
    monkeypatch.setattr("biblio_uplift.core.state.get_project_root", lambda: tmp_path)
    (tmp_path / "logs").mkdir(exist_ok=True)
    save_resume_state("test", [], set(), {})
    assert load_resume_state() is not None
    clear_resume_state()
    assert load_resume_state() is None


def test_load_corrupt_json(monkeypatch, tmp_path):
    monkeypatch.setattr("biblio_uplift.core.state.get_project_root", lambda: tmp_path)
    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)
    (logs / "resume-state.json").write_text("not json")
    assert load_resume_state() is None
