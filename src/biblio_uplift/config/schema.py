import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class CleanupConfig(BaseModel):
    prune_images: bool = True
    prune_volumes: bool = False  # opt-in: unused volumes (excludes labeled 'keep')
    prune_containers: bool = True
    prune_build_cache: bool = True
    log_retention_days: int = 30
    log_paths: list[str] = Field(default_factory=list)


class ProjectConfig(BaseModel):
    name: str
    ssh_host: str
    ssh_user: str = "ansible"
    ssh_key: Path = Path("~/.ssh/integration.pem")
    sudo: bool = True

    project_dir: Path
    compose_files: list[str] = Field(default_factory=lambda: ["docker-compose.yml"])
    compose_profile: str | None = None  # "hostname" = resolve on remote, or literal
    compose_command: str = "docker compose"

    @field_validator("compose_command")
    @classmethod
    def validate_compose_command(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_./ -]+$", v):
            raise ValueError(f"compose_command contains invalid characters: {v}")
        return v

    backup_dir: Path = Path("/var/backups/itops")
    backup_retention: int = Field(default=5, ge=1)
    volumes: list[str] = Field(default_factory=list)
    extra_backup_paths: list[str] = Field(default_factory=list)

    healthcheck_urls: list[str] = Field(default_factory=list)
    healthcheck_timeout: int = 120

    skip_os_update: bool = False
    skip_reboot: bool = False

    reboot_timeout: int = 300
    apt_timeout: int = 600

    pre_upgrade_hooks: list[str] = Field(default_factory=list)
    post_upgrade_hooks: list[str] = Field(default_factory=list)

    on_failure_cmd: str | None = None
    on_success_cmd: str | None = None

    ssh_port: int = 22

    git_branch: str | None = None
    maintenance_window: str | None = None  # e.g. "02:00-06:00" or None for anytime

    cleanup: CleanupConfig = Field(default_factory=CleanupConfig)
