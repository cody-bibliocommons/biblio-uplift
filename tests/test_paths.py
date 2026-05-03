import biblio_uplift.paths as paths_mod


class TestGetProjectRoot:
    def setup_method(self):
        # Reset cached value between tests
        paths_mod._project_root = None

    def test_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ITOPS_UPGRADE_DIR", str(tmp_path))
        assert paths_mod.get_project_root() == tmp_path

    def test_finds_git_dir(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ITOPS_UPGRADE_DIR", raising=False)
        # Place a .git dir in a parent of the module file
        fake_root = tmp_path / "project"
        fake_root.mkdir()
        (fake_root / ".git").mkdir()
        # Patch __file__ so the walk-up finds our fake root
        monkeypatch.setattr(paths_mod, "__file__", str(fake_root / "pkg" / "mod.py"))
        (fake_root / "pkg").mkdir()
        paths_mod._project_root = None
        assert paths_mod.get_project_root() == fake_root

    def test_fallback_to_cwd(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ITOPS_UPGRADE_DIR", raising=False)
        # Point __file__ somewhere with no .git or configs/ within 5 levels
        nowhere = tmp_path / "a" / "b" / "c" / "d" / "e" / "f" / "g"
        nowhere.mkdir(parents=True)
        monkeypatch.setattr(paths_mod, "__file__", str(nowhere / "mod.py"))
        monkeypatch.chdir(tmp_path)
        paths_mod._project_root = None
        assert paths_mod.get_project_root() == tmp_path
