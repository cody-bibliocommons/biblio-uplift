# Settings

The Settings page (TUI panel and CLI) manages app-level configuration stored in `~/.config/biblio-uplift/settings.json`.

## Config Repo Sync

biblio-uplift can sync project configs from a remote git repository. This lets teams share a central config repo and keep local configs up to date.

### How it works

1. On sync (manual via `biblio-uplift sync` or automatic if `config_sync_on_launch` is true), the app clones or pulls the config repo.
2. The repo is cloned to `~/.local/share/biblio-uplift/config-repo/`.
3. YAML files from the repo's `configs/` directory are copied into the local configs directory.
4. SSH authentication uses the key specified in `config_repo_ssh_key`.

### URL normalization

The config repo URL is normalized to SSH format. These are equivalent:

- `git@github.com:org/repo.git`
- `ssh://git@github.com/org/repo.git`
- `https://github.com/org/repo` (converted to SSH internally)

### Setting up a config repo

1. Create a git repo with a `configs/` directory containing your project YAML files.
2. Add a deploy key (read-only SSH key) to the repo.
3. Place the private key on your machine (e.g. `~/.ssh/config-repo-key`).
4. Configure biblio-uplift:

```bash
biblio-uplift settings set config_repo_url git@github.com:org/uplift-configs.git
biblio-uplift settings set config_repo_ssh_key ~/.ssh/config-repo-key
biblio-uplift settings set config_repo_branch main
biblio-uplift settings set config_sync_on_launch true
```

## Editor Detection

The "Open in Editor" button on the Config Edit page and `config edit` CLI command use this priority to find an editor:

1. `editor` setting in `settings.json`
2. `$EDITOR` environment variable
3. `$VISUAL` environment variable
4. Auto-detect from installed editors on `$PATH`

### Available editors

The Settings page dropdown and auto-detection check for:

- VS Code (`code`)
- Vim (`vim`)
- Neovim (`nvim`)
- Nano (`nano`)
- Emacs (`emacs`)
- Micro (`micro`)
- Helix (`hx`)
- Sublime Text (`subl`)
- Kate (`kate`)

Set explicitly via CLI:

```bash
biblio-uplift settings set editor nvim
```

When launched from the TUI, the terminal is suspended (Textual driver paused) while the editor runs, then resumed on exit.

## CLI Equivalents

All settings can be managed without the TUI:

```bash
# View all settings
biblio-uplift settings show

# Set individual values
biblio-uplift settings set config_repo_url git@github.com:org/configs.git
biblio-uplift settings set config_repo_ssh_key ~/.ssh/deploy-key
biblio-uplift settings set config_repo_branch main
biblio-uplift settings set config_sync_on_launch true
biblio-uplift settings set default_ssh_key ~/.ssh/id_ed25519
biblio-uplift settings set theme dark
biblio-uplift settings set analytics_retention_days 30
biblio-uplift settings set default_notification_cmd "curl -X POST https://hooks.slack.com/..."
biblio-uplift settings set editor vim

# Trigger a manual sync
biblio-uplift sync
```

## All Settings Keys

| Key | Default | Description |
|-----|---------|-------------|
| `config_repo_url` | `null` | Git SSH URL for config repo |
| `config_repo_ssh_key` | `~/.ssh/id_ed25519` | SSH key for config repo access |
| `config_repo_branch` | `main` | Branch to sync |
| `config_sync_on_launch` | `false` | Auto-sync on app start |
| `default_ssh_key` | `~/.ssh/id_ed25519` | Default SSH key for new project configs |
| `theme` | `dark` | TUI theme (`dark` or `light`) |
| `analytics_retention_days` | `30` | Days of data shown in analytics |
| `default_notification_cmd` | `null` | Default failure notification command |
| `editor` | `null` | Preferred editor binary name or path |
