import biblio_uplift.paths as paths_mod


class TestGetConfigDir:
    def test_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BIBLIO_UPLIFT_CONFIG_DIR", str(tmp_path))
        assert paths_mod.get_config_dir() == tmp_path

    def test_cwd_fallback(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BIBLIO_UPLIFT_CONFIG_DIR", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
        configs = tmp_path / "configs"
        configs.mkdir()
        monkeypatch.chdir(tmp_path)
        assert paths_mod.get_config_dir() == configs

    def test_xdg_config_dir(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BIBLIO_UPLIFT_CONFIG_DIR", raising=False)
        fakehome = tmp_path / "fakehome"
        xdg_configs = fakehome / ".config" / "biblio-uplift" / "configs"
        xdg_configs.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(fakehome))
        assert paths_mod.get_config_dir() == xdg_configs

    def test_raises_when_nothing_found(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BIBLIO_UPLIFT_CONFIG_DIR", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
        monkeypatch.chdir(tmp_path)
        import pytest

        with pytest.raises(FileNotFoundError):
            paths_mod.get_config_dir()


class TestGetDataDir:
    def test_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BIBLIO_UPLIFT_DATA_DIR", str(tmp_path))
        assert paths_mod.get_data_dir() == tmp_path

    def test_default(self, monkeypatch):
        monkeypatch.delenv("BIBLIO_UPLIFT_DATA_DIR", raising=False)
        from pathlib import Path

        expected = Path.home() / ".local" / "share" / "biblio-uplift"
        assert paths_mod.get_data_dir() == expected


class TestGetExamplesDir:
    def test_returns_examples_subdir(self):
        from pathlib import Path

        result = paths_mod.get_examples_dir()
        assert result == Path(paths_mod.__file__).parent / "examples"
