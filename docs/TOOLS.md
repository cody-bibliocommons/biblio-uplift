# Tools Reference

## Security

| Tool | Description | Type |
|------|-------------|------|
| pending-security-updates | Check for pending security patches | Read-only |
| open-ports-audit | List listening ports and processes | Read-only |
| ssh-config-review | Review SSH daemon configuration | Read-only |

## System

| Tool | Description | Type |
|------|-------------|------|
| journald-config | Set journal max size (backs up config) | Mutating |
| force-logrotate | Force log rotation | Mutating |
| fix-permissions | Fix project dir ownership/permissions | Mutating |

## Docker

| Tool | Description | Type |
|------|-------------|------|
| container-logs | View last 50 lines per container | Read-only |
| compose-pull-check | Check for image updates | Read-only |
| restart-containers | Restart all compose services | Mutating |
| freeipa-logs | Clean FreeIPA container logs | Mutating |
| update-service | Pull repo + rebuild/recreate a service (or all) | Mutating |
| compose-version | Check Docker Compose version and install method; upgrade manual binary to package-managed | Mutating |

## Network

| Tool | Description | Type |
|------|-------------|------|
| dns-resolution | Test DNS for key hostnames | Read-only |
| ntp-sync | Check NTP synchronization | Read-only |
| certificate-expiry | Check SSL cert expiry dates | Read-only |

## Users & Access

| Tool | Description | Type |
|------|-------------|------|
| sudo-users | List sudo users and NOPASSWD status | Read-only |
| authorized-keys | Review SSH keys per user | Read-only |
| group-membership | Show docker/sudo group members | Read-only |
