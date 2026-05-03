![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Tests](https://img.shields.io/badge/tests-259%20passed-brightgreen)
![Coverage](https://img.shields.io/badge/coverage-99%25-brightgreen)
![Security](https://img.shields.io/badge/security-bandit%20%7C%20pip--audit%20%7C%20gitleaks-green)
![License](https://img.shields.io/badge/license-internal-lightgrey)
![Version](https://img.shields.io/badge/version-0.1.0-blue)

# biblio-uplift

TUI and CLI tool for upgrading Docker Compose-based services on remote servers via SSH.

## Install

```bash
pip install .
```

## Quick Start

```bash
# Launch the interactive TUI
biblio-uplift

# Run an upgrade from the CLI
biblio-uplift run itops-vaultwarden

# Run non-interactively (for cron/automation)
biblio-uplift run itops-vaultwarden --non-interactive

# Dry run (simulate without executing)
biblio-uplift run itops-vaultwarden --dry-run

# Run cleanup (prune docker resources, old logs)
biblio-uplift cleanup itops-vaultwarden

# View history
biblio-uplift history --last 10
```

## Configuration

Project configs live in `configs/` as YAML files. Each config defines a remote server and its Docker Compose project.

```bash
# List configured projects
biblio-uplift config list

# Show a project's config
biblio-uplift config show itops-vaultwarden
```

### Config Fields

| Field | Default | Description |
|-------|---------|-------------|
| `name` | required | Project identifier |
| `ssh_host` | required | Remote server hostname |
| `ssh_user` | `ansible` | SSH username |
| `ssh_key` | `~/.ssh/integration.pem` | Path to SSH private key (must not have a passphrase, or use ssh-agent) |
| `sudo` | `true` | Prefix remote commands with sudo |
| `project_dir` | required | Path to the Docker Compose project on the remote server |
| `compose_files` | `["docker-compose.yml"]` | Compose file(s) to use |
| `compose_profile` | `null` | Compose profile. Set to `hostname` to use `$(hostname -s)` on the remote |
| `compose_command` | `docker compose` | Compose binary |
| `backup_dir` | `/var/backups/itops` | Where to store backups on the remote server (local disk, not NFS) |
| `backup_retention` | `5` | Number of backups to keep |
| `volumes` | `[]` | Docker volume names to back up |
| `extra_backup_paths` | `[]` | Additional paths to include in file backup |
| `healthcheck_urls` | `[]` | HTTP(S) URLs to check after startup |
| `healthcheck_timeout` | `120` | Seconds to wait for containers to become healthy |
| `skip_os_update` | `false` | Skip OS package updates by default |
| `skip_reboot` | `false` | Skip reboot by default |
| `pre_upgrade_hooks` | `[]` | Shell commands to run before upgrade (executed as root via sudo) |
| `post_upgrade_hooks` | `[]` | Shell commands to run after upgrade |

### Hooks

Pre/post upgrade hooks are arbitrary shell commands executed on the remote server. They run as root (via sudo). Use them for things like:

```yaml
pre_upgrade_hooks:
  - "systemctl stop bitbucket-runner"
  - "/opt/scripts/notify-slack.sh 'Starting upgrade'"
post_upgrade_hooks:
  - "systemctl start bitbucket-runner"
  - "/opt/scripts/notify-slack.sh 'Upgrade complete'"
```

## Upgrade Pipeline

The upgrade runs these steps in order:

1. **Preflight** — SSH connectivity, disk space check, backup size estimation
1. **Pre-hooks** — Custom pre-upgrade commands
1. **Backup files** — Tar project dir + extra paths
1. **Backup volumes** — Export Docker volumes via alpine container
1. **Backup cleanup** — Remove old backups beyond retention count
1. **Docker down** — `docker compose down`
1. **Git pull** — Pull latest from Bitbucket
1. **Docker pull** — Pull latest images
1. **OS update** — `apt-get update && upgrade && autoremove --purge`
1. **Reboot** — Reboot and wait for SSH to come back
1. **Docker up** — `docker compose up -d`
1. **Health check** — Wait for containers healthy + HTTP checks
1. **Post-hooks** — Custom post-upgrade commands

On failure, completed steps are rolled back in reverse order (docker down → docker up, git pull → git checkout previous commit).

## Cleanup Pipeline

1. **Preflight** — SSH connectivity check
1. **Docker cleanup** — Prune stopped containers, dangling images, unused volumes, build cache
1. **Log cleanup** — Truncate configured log files, vacuum journald

## CLI Flags

```
biblio-uplift [--debug] COMMAND

Global:
  --debug              Write verbose logs to logs/debug.log

run:
  --non-interactive    Skip confirmation prompts
  --skip-reboot        Skip the reboot step
  --skip-os-update     Skip OS package updates
  --skip-backup        Skip all backup steps
  --dry-run            Simulate without executing
  --no-hooks           Skip pre/post hooks

cleanup:
  --non-interactive    Skip confirmation prompts

history:
  --project NAME       Filter by project
  --last N             Show last N entries (default: 20)
```

## Audit History

Every run is logged to `logs/history.jsonl` with timestamp, project, steps, outcomes, and duration. View with:

```bash
biblio-uplift history
biblio-uplift history --project itops-identity --last 5
```

## Concurrent Run Protection

A file lock (`/tmp/biblio-uplift-<project>.lock`) prevents multiple upgrades of the same project from running simultaneously.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Pipeline failed or error |

## Cron / Unattended Use

```bash
# Weekly upgrade of vaultwarden, Sundays at 3am
0 3 * * 0 cd /path/to/biblio-uplift && biblio-uplift run itops-vaultwarden --non-interactive --on-failure "curl -X POST https://hooks.slack.com/services/YOUR/WEBHOOK -d '{\"text\": \"Vaultwarden upgrade failed\"}' " >> logs/cron.log 2>&1
```

For unattended runs:

- Always use `--non-interactive` to skip confirmation prompts
- Set `on_failure_cmd` in config or use `--on-failure` for failure alerts
- Set `maintenance_window` in config to prevent accidental runs outside hours
- Monitor exit codes and `logs/history.jsonl` for audit trail

## Development

```bash
pip install -e .
biblio-uplift --debug run itops-vaultwarden --dry-run
```

Set `ITOPS_UPGRADE_DIR` to override the project root directory detection.
