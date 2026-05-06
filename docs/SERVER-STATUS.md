# Server Status Panel

The Server Status panel provides a health overview of a remote server. Available in both the TUI (interactive panel) and CLI (`biblio-uplift status PROJECT`).

## Basic Checks (always shown)

| Check | Description |
|-------|-------------|
| Uptime | How long the server has been running |
| Reboot required | Whether `/var/run/reboot-required` indicates a pending reboot |
| Disk | Filesystem usage for the project directory |
| Git | Latest commit on the project repo |
| Docker version | Docker Engine server version |
| Containers | Running containers with health status (color-coded) |
| Recent backups | Last 5 backup archives in the backup directory |
| Memory | Output of `free -h` (RAM and swap) |
| Top processes | Top 5 processes by CPU usage |
| Container resources | Per-container CPU, memory, and network I/O (`docker stats`) |
| Disk breakdown | Usage of `/var/log`, `/var/cache`, `/tmp`, and the project directory |
| Docker disk | `docker system df` output plus overlay2 on-disk size |

## Advanced Toggle

The TUI panel has an **Advanced** checkbox. When enabled, additional diagnostics are collected:

| Check | Description |
|-------|-------------|
| Failed systemd units | Any units in failed state |
| Pending updates | Count of upgradable apt packages |
| Kernel version | Running kernel vs. latest installed kernel |
| Docker networks | All Docker networks with driver and scope |
| Docker volumes | All Docker volumes |
| Zombie processes | Count of defunct/zombie processes |
| Inode usage | Inode usage on the root filesystem |
| Last logins | Last 5 login entries from `last` |

## CLI Usage

```bash
# Basic status check (no advanced diagnostics)
biblio-uplift status itops-vaultwarden
```

The CLI `status` command runs the basic checks only. Use the TUI for advanced diagnostics.
