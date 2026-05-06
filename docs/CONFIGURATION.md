# Configuration Reference

Project configs are YAML files stored in `configs/`. Each file defines one remote server and its Docker Compose project.

## SSH Settings

| Field | Default | Description |
|-------|---------|-------------|
| `ssh_host` | required | Remote server hostname or IP |
| `ssh_user` | `ansible` | SSH username |
| `ssh_key` | `~/.ssh/integration.pem` | Path to SSH private key (no passphrase, or use ssh-agent) |
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
name: itops-vaultwarden
ssh_host: ops-liv-vaultwarden01.bcommons.net
ssh_user: ansible
ssh_key: ~/.ssh/integration.pem
ssh_port: 22
sudo: true

project_dir: /opt/docker/itops-vaultwarden
compose_files:
  - docker-compose.yml
compose_command: docker compose
# compose_profile: hostname
git_branch: main

backup_dir: /var/backups/itops/itops-vaultwarden
backup_retention: 5
volumes:
  - vaultwarden_data
  - vaultwarden_vault
extra_backup_paths:
  - /opt/docker/itops-vaultwarden/haproxy

healthcheck_urls:
  - https://ops-liv-vaultwarden01.bcommons.net
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
