# Changelog

## [0.2.0] - 2026-05-09

### Added
- SQLite history database (replaces JSONL) with runs, step_timings, tool_executions tables
- Analytics: `biblio-uplift analytics` command and dashboard integration (success rate, avg duration, slowest steps, tool stats)
- Settings page (TUI + CLI) with config repo sync, editor detection, theme
- Config repo sync via SSH (clone/pull with configurable key and branch)
- Editor detection with dropdown (VS Code, Vim, Neovim, Nano, etc.)
- "Open in Editor" button on Config Edit page with TUI suspend/resume
- `biblio-uplift init` command for new installs
- `biblio-uplift sync` command for manual config repo sync
- `biblio-uplift settings show/set` commands
- XDG-compliant paths (~/.config/biblio-uplift/, ~/.local/share/biblio-uplift/)
- Package manager abstraction (apt/dnf/yum/apk)
- Auto-detect git host from remote URL
- GitHub Actions CI + PyPI OIDC trusted publish workflow
- MIT license

### Changed
- SSH key default changed from integration.pem to ~/.ssh/id_ed25519
- Ruff lint: empty global ignore list, all suppressions per-file with justification
- Dashboard shows 30-day analytics (failure rate, avg duration per project)
- Tool executions now recorded in SQLite audit trail
- click.edit() replaces subprocess for editor launching
- contextlib.suppress replaces try/except/pass
- tempfile.gettempdir() replaces hardcoded /tmp

### Fixed
- All compound shell commands properly wrapped in bash -c for sudo
- ComposePullCheckTool fallback no longer does real pull
- FreeIpaLogsTool: shlex.quote container names
- Detached HEAD guard in git operations

## [0.1.0] - 2026-05-06

### Added
- Initial release: 13-step upgrade pipeline with rollback
- 9 TUI panels (Dashboard, Upgrade, Cleanup, Server Status, Backups, Config Editor, History, Tools, About)
- 18 tools across 5 categories
- CLI parity for all TUI features
- Bitbucket Pipelines CI (ruff, mypy, bandit, pip-audit, pytest)
