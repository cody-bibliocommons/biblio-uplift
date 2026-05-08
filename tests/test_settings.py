"""Tests for biblio_uplift.settings module."""

from __future__ import annotations

from biblio_uplift.settings import DEFAULTS, load_settings, normalize_git_url, save_settings


class TestNormalizeGitUrl:
    def test_git_clone_prefix(self):
        assert normalize_git_url("git clone git@github.com:org/repo.git") == "git@github.com:org/repo.git"

    def test_ssh_clone_prefix(self):
        assert normalize_git_url("ssh clone git@github.com:org/repo.git") == "git@github.com:org/repo.git"

    def test_bare_host_org_repo(self):
        assert normalize_git_url("bitbucket.org/org/repo") == "git@bitbucket.org:org/repo.git"

    def test_bare_host_org_repo_with_git_suffix(self):
        assert normalize_git_url("bitbucket.org/org/repo.git") == "git@bitbucket.org:org/repo.git"

    def test_ssh_format_passthrough(self):
        assert normalize_git_url("git@github.com:org/repo.git") == "git@github.com:org/repo.git"

    def test_https_format_passthrough(self):
        assert normalize_git_url("https://github.com/org/repo.git") == "https://github.com/org/repo.git"


class TestLoadSaveSettings:
    def test_defaults_on_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("biblio_uplift.settings.get_settings_path", lambda: tmp_path / "missing.json")
        settings = load_settings()
        assert settings == DEFAULTS

    def test_roundtrip(self, tmp_path, monkeypatch):
        path = tmp_path / "settings.json"
        monkeypatch.setattr("biblio_uplift.settings.get_settings_path", lambda: path)

        custom = {**DEFAULTS, "theme": "light", "analytics_retention_days": 30}
        save_settings(custom)

        loaded = load_settings()
        assert loaded["theme"] == "light"
        assert loaded["analytics_retention_days"] == 30
