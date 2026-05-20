# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo Purpose

Chezmoi-managed dotfiles for both personal machines (`dmf` user) and Riot Games work machines (`dfrank` / RIOTGAMES domain). A single source tree handles multi-OS, multi-machine configurations through templating and conditional logic.

## Commands

Apply all dotfiles to the current machine:

```sh
chezmoi apply
```

Preview changes before applying:

```sh
chezmoi diff
```

Run only a subset (e.g., re-run scripts after editing):

```sh
chezmoi apply --include scripts
```

Lint/format via pre-commit (runs shellcheck, shfmt, ruff, stylua, prettier, etc.):

```sh
pre-commit run --all-files
```

Run a single hook:

```sh
pre-commit run shellcheck --all-files
```

## Architecture

### File Naming Conventions

Chezmoi interprets file/directory name prefixes before placing them in `$HOME`:

| Prefix                       | Meaning                                                            |
| ---------------------------- | ------------------------------------------------------------------ |
| `dot_`                       | Becomes `.` in home dir                                            |
| `exact_`                     | Syncs deletions (removes untracked files in dir)                   |
| `private_`                   | Sets restrictive permissions; file content encrypted via 1Password |
| `run_once_before_`           | Script runs once ever, before applying files                       |
| `run_once_after_`            | Script runs once ever, after applying files                        |
| `run_onchange_*`             | Script runs when its content (or `.tmpl` inputs) changes           |
| `run_before_` / `run_after_` | Script runs every `chezmoi apply`                                  |
| `.tmpl` suffix               | Go template, rendered at apply time                                |

Platform filtering in script names: `.unix-like.sh`, `.darwin.sh`, `.windows.ps1` (matched by `.chezmoiignore.tmpl`).

### Script Execution Order

Scripts under `.chezmoiscripts/` are staged by numeric subdirectory:

| Stage | Purpose                                                   |
| ----- | --------------------------------------------------------- |
| `00/` | Sudoers setup                                             |
| `10/` | Core/system deps: package manager and tool manager installers + syncs |
| `20/` | Dev deps: language runtimes and toolchains (mise install, setup-opam) |
| `30/` | Shell registration: xonsh in /etc/shells, set as default  |
| `40/` | App-level deps: Python packages via xpip/UV              |
| `50/` | Self-managed symlinked file sync (pre-apply)              |
| `65/` | Log rotation                                              |
| `70/` | Editor plugin sync (Neovim/Mason)                         |
| `90/` | Specialized setup (terminfo, Riot machine P4/LoL tooling) |
| `99/` | Git-commit backup snapshots of symlinked files            |

### Machine Detection

`.chezmoi.toml.tmpl` sets boolean template variables consumed everywhere:

- `isMyMachine` — username is `dmf`
- `isRiotMachine` — username is `dfrank` or RIOTGAMES domain
- `isWorkMachine` — any non-personal machine
- OS booleans: `isDarwin`, `isLinux`, `isWindows`, `isUnixLike`, `isBsd`

Credentials flow through 1Password (`onepasswordRead()`). The `OP_SERVICE_ACCOUNT_TOKEN` is read from the environment or `~/.secrets/OP_SERVICE_ACCOUNT_TOKEN`.

### Templating

Shared templates live in `.chezmoitemplates/` and are included via `{{ includeTemplate "..." . }}`. The canonical example is `.chezmoitemplates/agents/AGENTS.md.tmpl`, which is rendered into each AI tool's config dir rather than installed as a standalone dotfile.

Machine-specific data (MCP servers, project paths) is in `.chezmoidata/`.

### Backup Strategy

`.backups/` is git-tracked and auto-committed by stage 99 scripts. Snapshots are named `<tool>.<user>@<hostname>.log` (e.g., `Brewfile.dfrank@MLF67N6G9N5W.log`) and captured **before and after** install/upgrade runs for audit trail.

### Key Subsystems

- **Xonsh** (primary shell): `dot_config/xonsh/`
- **Zsh** (fallback): modular configs in `.zsh/` (riot, gcloud, ocaml, etc.)
- **Neovim**: `dot_config/exact_nvim/` — Lazy plugin manager, Mason for LSP/formatters
- **Git**: aliases and config in `dot_config/git/`
- **AI tools**: `dot_claude/`, `dot_codex/`, `dot_gemini/` — each rendered from shared AGENTS.md template
- **Homebrew**: `dot_config/homebrew/Brewfile.tmpl`
- **Mise**: polyglot tool version manager, `dot_config/exact_mise/` + `.mise.toml`

## Also See

- [AGENTS.md](./AGENTS.md) — commit semantics and chezmoi-specific code style rules for this repo.
- [CLAUDE.md](./CLAUDE.md) — bootstrapping instructions for new machines.
