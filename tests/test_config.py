from pathlib import Path

import pytest
import yaml

from biblio_uplift.config.loader import get_config_dir, list_configs, load_config, save_config
from biblio_uplift.config.schema import CleanupConfig, ProjectConfig

# --- ProjectConfig ---


class TestProjectConfig:
    def test_defaults(self):
        c = ProjectConfig(name="p", ssh_host="h", project_dir="/tmp/x")
        assert c.ssh_user == "ansible"
        assert c.ssh_key == Path("~/.ssh/integration.pem")
        assert c.sudo is True
        assert c.compose_files == ["docker-compose.yml"]
        assert c.compose_profile is None
        assert c.compose_command == "docker compose"
        assert c.backup_dir == Path("/var/backups/itops")
        assert c.backup_retention == 5
        assert c.volumes == []
        assert c.extra_backup_paths == []
        assert c.healthcheck_urls == []
        assert c.healthcheck_timeout == 120
        assert c.skip_os_update is False
        assert c.skip_reboot is False
        assert c.pre_upgrade_hooks == []
        assert c.post_upgrade_hooks == []
        assert isinstance(c.cleanup, CleanupConfig)

    def test_all_fields(self):
        c = ProjectConfig(
            name="full",
            ssh_host="10.0.0.1",
            ssh_user="root",
            ssh_key="/keys/id",
            sudo=False,
            project_dir="/opt/app",
            compose_files=["a.yml", "b.yml"],
            compose_profile="prod",
            compose_command="docker-compose",
            backup_dir="/bak",
            backup_retention=3,
            volumes=["vol1"],
            extra_backup_paths=["/etc/app"],
            healthcheck_urls=["http://localhost"],
            healthcheck_timeout=60,
            skip_os_update=True,
            skip_reboot=True,
            pre_upgrade_hooks=["echo pre"],
            post_upgrade_hooks=["echo post"],
            cleanup=CleanupConfig(prune_images=False),
        )
        assert c.name == "full"
        assert c.ssh_user == "root"
        assert c.compose_profile == "prod"
        assert c.backup_retention == 3
        assert c.skip_os_update is True
        assert c.cleanup.prune_images is False


class TestCleanupConfig:
    def test_defaults(self):
        c = CleanupConfig()
        assert c.prune_images is True
        assert c.prune_volumes is False
        assert c.prune_containers is True
        assert c.prune_build_cache is True
        assert c.log_retention_days == 30
        assert c.log_paths == []


class TestComposeCommandValidator:
    @pytest.mark.parametrize(
        "bad",
        [
            "cmd; rm -rf /",
            "cmd | cat",
            "cmd & bg",
            "cmd $VAR",
            "cmd `whoami`",
            "cmd\nrm",
        ],
    )
    def test_rejects_unsafe(self, bad):
        with pytest.raises(ValueError, match="invalid characters"):
            ProjectConfig(name="p", ssh_host="h", project_dir="/tmp", compose_command=bad)

    @pytest.mark.parametrize("good", ["docker compose", "docker-compose"])
    def test_accepts_valid(self, good):
        c = ProjectConfig(name="p", ssh_host="h", project_dir="/tmp", compose_command=good)
        assert c.compose_command == good


# --- loader ---


def _write_yaml(path, data):
    path.write_text(yaml.dump(data, default_flow_style=False))


def _minimal_data(**overrides):
    d = {"name": "t", "ssh_host": "h", "project_dir": "/tmp"}
    d.update(overrides)
    return d


class TestLoadConfig:
    def test_valid(self, tmp_path):
        p = tmp_path / "c.yml"
        _write_yaml(p, _minimal_data())
        c = load_config(p)
        assert c.name == "t"

    def test_invalid_raises(self, tmp_path):
        p = tmp_path / "bad.yml"
        p.write_text("not: valid: yaml: [")
        with pytest.raises(Exception):
            load_config(p)

    def test_missing_field_raises(self, tmp_path):
        p = tmp_path / "bad.yml"
        _write_yaml(p, {"name": "x"})  # missing ssh_host, project_dir
        with pytest.raises(Exception):
            load_config(p)


class TestSaveConfig:
    def test_round_trip(self, tmp_path):
        orig = ProjectConfig(name="rt", ssh_host="h", project_dir="/opt/x", volumes=["v1"])
        p = tmp_path / "out.yml"
        save_config(orig, p)
        loaded = load_config(p)
        assert loaded.name == orig.name
        assert loaded.volumes == orig.volumes
        assert loaded.ssh_host == orig.ssh_host


class TestListConfigs:
    def test_loads_valid_skips_invalid(self, tmp_path):
        _write_yaml(tmp_path / "a.yml", _minimal_data(name="a"))
        _write_yaml(tmp_path / "b.yml", _minimal_data(name="b"))
        (tmp_path / "bad.yml").write_text("garbage: [")
        configs = list_configs(tmp_path)
        names = [c.name for c in configs]
        assert "a" in names
        assert "b" in names
        assert len(configs) == 2

    def test_empty_dir(self, tmp_path):
        assert list_configs(tmp_path) == []


class TestGetConfigDir:
    def test_returns_path(self):
        result = get_config_dir()
        assert isinstance(result, Path)
        assert result.name == "configs"


# --- New field defaults ---


class TestNewFieldDefaults:
    def test_on_failure_cmd_default_none(self):
        config = ProjectConfig(name="t", ssh_host="h", project_dir="/tmp")
        assert config.on_failure_cmd is None

    def test_reboot_timeout_default(self):
        config = ProjectConfig(name="t", ssh_host="h", project_dir="/tmp")
        assert config.reboot_timeout == 300

    def test_apt_timeout_default(self):
        config = ProjectConfig(name="t", ssh_host="h", project_dir="/tmp")
        assert config.apt_timeout == 600

    def test_prune_volumes_default_false(self):
        assert CleanupConfig().prune_volumes is False

    def test_ssh_port_default(self):
        config = ProjectConfig(name="t", ssh_host="h", project_dir="/tmp")
        assert config.ssh_port == 22

    def test_git_branch_default_none(self):
        config = ProjectConfig(name="t", ssh_host="h", project_dir="/tmp")
        assert config.git_branch is None

    def test_maintenance_window_default_none(self):
        config = ProjectConfig(name="t", ssh_host="h", project_dir="/tmp")
        assert config.maintenance_window is None

    def test_on_success_cmd_default_none(self):
        config = ProjectConfig(name="t", ssh_host="h", project_dir="/tmp")
        assert config.on_success_cmd is None
