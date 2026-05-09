# Architecture

## Overview

biblio-uplift is a Python TUI/CLI tool for managing Docker Compose services on remote servers via SSH.

## Directory Structure

```
src/biblio_uplift/
├── cli/main.py          # Click CLI entry point (all commands)
├── config/              # Pydantic config schema + YAML loader
├── core/
│   ├── pipeline.py      # Pipeline engine (step runner, rollback, locking)
│   ├── ssh.py           # SSH command runner (subprocess-based)
│   ├── state.py         # Resume state persistence
│   ├── steps/           # Pipeline steps (backup, docker, git, system, etc.)
│   └── tools/           # Standalone tools (security, system, docker, network, users)
├── history/audit.py     # SQLite audit log (runs, step_timings, tool_executions)
├── paths.py             # XDG path resolution
├── settings.py          # App settings (settings.json read/write, config repo sync)
└── tui/
    ├── app.py           # Textual App with sidebar + ContentSwitcher
    ├── screens/         # 10 panel widgets
    └── widgets/         # Sidebar widget
```

## Key Design Decisions

1. **SSH-based remote execution** — no agents on target servers
2. **Pipeline pattern** — ordered steps with rollback on failure
3. **Per-command sudo** — `ssh.run(cmd, sudo=False)` for git operations
4. **bash -c wrapper** — for cd, globs, and multi-command pipelines
5. **Textual TUI** — sidebar + ContentSwitcher, @on decorators for button events
6. **Worker threads** — @work(thread=True) for SSH operations, call_from_thread for UI updates
7. **File locking** — fcntl.flock prevents concurrent runs
8. **SQLite history** — structured audit trail with runs, step_timings, and tool_executions tables (replaces JSONL)
9. **settings.json** — app-level configuration (config repo URL, editor, theme, analytics retention) stored at `~/.config/biblio-uplift/settings.json`

## Data Flow

```
User → CLI/TUI → Pipeline → Steps → SSHRunner → Remote Server
                                         ↓
                                    History/Logs
```

## Configuration

YAML configs validated by Pydantic. Stored in `~/.config/biblio-uplift/configs/` or `$BIBLIO_UPLIFT_CONFIG_DIR`.

## Cleanup Behavior

The `aggressive_prune` config option (under `cleanup:`) controls whether `docker image prune` removes only dangling images (default) or all unused images (`-a`). Useful for servers where disk is tight but risky if images are shared across projects.

## Server Status Panel

The Server Status panel has an **Advanced** toggle (checkbox). Basic checks always run (uptime, disk, containers, etc.). When Advanced is enabled, additional diagnostics are collected: failed systemd units, pending updates, kernel version, docker networks/volumes, zombie processes, inode usage, and last logins.

## Tool Parameters

Some tools accept a `target_service` parameter to scope their action to a single service rather than all. The `UpdateServiceTool` uses this pattern: if `target_service` is set and matches a running service, only that service is pulled/recreated. Otherwise all services are updated.

## CI/CD

- **GitHub Actions** — lint (ruff), type check (mypy), security (bandit, pip-audit), tests (pytest) on push/PR
- **PyPI publish** — OIDC trusted publisher workflow on tagged releases
- **GitHub mirror** — primary repo is Bitbucket; GitHub mirror is synced for CI and public distribution
