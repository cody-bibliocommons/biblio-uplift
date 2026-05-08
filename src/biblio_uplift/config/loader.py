import logging
from pathlib import Path

import yaml

from .schema import ProjectConfig

logger = logging.getLogger(__name__)


def load_config(path: Path) -> ProjectConfig:
    """Read YAML file and validate with Pydantic."""
    data = yaml.safe_load(path.read_text())
    return ProjectConfig(**data)


def save_config(config: ProjectConfig, path: Path) -> None:
    """Dump ProjectConfig to YAML file."""
    data = config.model_dump(mode="json")
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


def list_configs(config_dir: Path) -> list[ProjectConfig]:
    """Load all .yml files from a directory."""
    configs: list[ProjectConfig] = []
    for p in sorted(config_dir.glob("*.yml")):
        try:
            configs.append(load_config(p))
        except Exception as e:
            logger.warning("Skipping invalid config %s: %s", p.name, e)
    return configs


def get_config_dir() -> Path:
    """Return the configs directory."""
    from biblio_uplift.paths import get_config_dir as _get_config_dir

    return _get_config_dir()
