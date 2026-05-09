# Configuration Reference

Project configs are YAML files stored in `configs/`. Each file defines one remote server and its Docker Compose project.

## SSH Settings

| Field | Default | Description |
|-------|---------|-------------|
| `ssh_host` | required | Remote server hostname or IP |
| `ssh_user` | `ansible` | SSH username |
| `ssh_key` | `~/.ssh/id_ed25519` | Path to SSH private key (no passphrase, or use ssh-agent) |
| `ssh_port` | `22` | SSH port |
| `sudo` | `true` | Prefix remote commands with sudo |

## Project Settings

| Field | Default | Description |
|-------|---------|-------------|
| `name` | required | Project identifier (matches filename without `.yml`) |
| `project_dir` | required | Absolute path to Docker Compose project on the remote server |
| `compose_command` | `docker compose` | Compose binary/command |
| `compose_files` | `["docker-compose.yml"]` | Compose file(s) to use |
| `compose_profile` | `null` | Compose profile. Set to `hostname` to use `$(hostname -s)` on the remote |
| `git_branch` | `main` | Git branch to pull during upgrades |

## Backup Settings

| Field | Default | Description |
|-------|---------|-------------|
| `backup_dir` | `/var/backups/itops` | Where to store backups on the remote (must be absolute path) |
| `backup_retention` | `5` | Number of backup sets to keep |
| `volumes` | `[]` | Docker volume names to back up |
| `extra_backup_paths` | `[]` | Additional paths to include in file backup |
| `backup_exclude_patterns` | `[".env", "*.pem", ...]` | Glob patterns excluded from backup archives |

## Cleanup Settings

Nested under the `cleanup:` key:

| Field | Default | Description |
|-------|---------|-------------|
| `prune_images` | `true` | Prune dangling Docker images |
| `prune_volumes` | `true` | Prune unused Docker volumes |
| `prune_containers` | `true` | Prune stopped containers |
| `prune_build_cache` | `true` | Prune Docker build cache |
| `aggressive_prune` | `false` | Remove *all* unused images (not just dangling). Use with caution on shared hosts. |
| `log_retention_days` | `30` | Days to keep logs before truncation |
| `log_paths` | `[]` | Log files to truncate during cleanup |
| `cleanup_commands` | `[]` | Additional shell commands to run during cleanup |

## Healthcheck

| Field | Default | Description |
|-------|---------|-------------|
| `healthcheck_urls` | `[]` | HTTP(S) URLs to check after container startup |
| `healthcheck_timeout` | `120` | Seconds to wait for containers to become healthy |

## Maintenance Window

| Field | Default | Description |
|-------|---------|-------------|
| `maintenance_window` | `null` | Allowed time window (e.g. `"Sun 02:00-06:00"`). Runs outside this window are blocked. |

## Failure Handling

| Field | Default | Description |
|-------|---------|-------------|
| `on_failure_cmd` | `null` | Shell command to run on pipeline failure (e.g. Slack webhook) |
| `on_success_cmd` | `null` | Shell command to run on pipeline success |

## Complete Example

```yaml
name: my-vaultwarden
ssh_host: server.example.com
ssh_user: deploy
ssh_key: ~/.ssh/id_ed25519
ssh_port: 22
sudo: true

project_dir: /opt/docker/my-vaultwarden
compose_files:
  - docker-compose.yml
compose_command: docker compose
# compose_profile: hostname
git_branch: main

backup_dir: /var/backups/itops/my-vaultwarden
backup_retention: 5
volumes:
  - vaultwarden_data
  - vaultwarden_vault
extra_backup_paths:
  - /opt/docker/my-vaultwarden/haproxy

healthcheck_urls:
  - https://server.example.com
healthcheck_timeout: 120

skip_os_update: false
skip_reboot: false
reboot_timeout: 300
apt_timeout: 600

maintenance_window: "Sun 02:00-06:00"
on_failure_cmd: "curl -X POST https://hooks.slack.com/services/YOUR/WEBHOOK -d '{\"text\": \"Upgrade failed\"}'"
on_success_cmd: null

pre_upgrade_hooks: []
post_upgrade_hooks: []

cleanup:
  prune_images: true
  prune_volumes: true
  prune_containers: true
  prune_build_cache: true
  aggressive_prune: false
  log_retention_days: 30
  log_paths:
    - /var/log/syslog
    - /var/log/auth.log
  cleanup_commands: []
```

## App Settings

App-level settings (separate from project configs) are stored in `~/.config/biblio-uplift/settings.json`. These control application behavior rather than individual project upgrades.

| Key | Default | Description |
|-----|---------|-------------|
| `config_repo_url` | `null` | Git SSH URL for config repo (e.g. `git@github.com:org/configs.git`) |
| `config_repo_ssh_key` | `~/.ssh/id_ed25519` | SSH key used to clone/pull the config repo |
| `config_repo_branch` | `main` | Branch to checkout from config repo |
| `config_sync_on_launch` | `false` | Automatically sync config repo when the app starts |
| `default_ssh_key` | `~/.ssh/id_ed25519` | Default SSH key for new project configs |
| `theme` | `dark` | TUI theme (`dark` or `light`) |
| `analytics_retention_days` | `30` | Days of history to include in analytics |
| `default_notification_cmd` | `null` | Default shell command for failure notifications |
| `editor` | `null` | Preferred editor for config editing. Falls back to `$EDITOR`, `$VISUAL`, then auto-detect |

Manage via CLI:

```bash
biblio-uplift settings show
biblio-uplift settings set config_repo_url git@github.com:org/configs.git
biblio-uplift settings set config_sync_on_launch true
```

See [SETTINGS.md](SETTINGS.md) for details on config repo sync and editor detection.
