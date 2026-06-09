# My Dot and RC Files

[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)

## Architecture

Chezmoi-managed dotfiles for both personal machines (`dmf` user) and Riot Games work machines (`dfrank` / RIOTGAMES domain). A single source tree handles multi-OS, multi-machine configurations through templating and conditional logic.

### Bootstrap Flow

`chezmoi apply` has three distinct phases, and the dependency direction between them is non-negotiable:

```
Phase 1 — Bootstrap (runs BEFORE chezmoi apply, via [hooks.read-source-state.pre])
  .bootstrap.*.sh / .bootstrap.*.ps1
  Installs: 1Password CLI, Git, mise, uv, WSL (Windows)
  WHY: These must exist before Phase 2, because modify_* scripts run during
       file sync and cannot be deferred to a later chezmoiscript stage.

Phase 2 — File sync (chezmoi apply core)
  • Renders .tmpl files → writes managed files to $HOME
  • Executes modify_* scripts (e.g. private_dot_parsec/modify_config.json.tmpl)
  • modify_* scripts run here, not in Phase 3 — tools they need must be in Phase 1.

Phase 3 — chezmoiscripts (run_after_ / run_once_after_ / run_onchange_after_)
  Stage 10: Platform package manager sync (Homebrew, pacman, winget)
  Stage 20: Tool manager sync (mise install, xpip, opam, pre-commit)
  Stage 40+: Everything else (shell, editor plugins, backups)
  WHY stages 10–20 are NOT sufficient for modify_* deps: file sync (Phase 2)
  runs BEFORE any run_after_ script, so tools installed here aren't yet on PATH
  when modify_* scripts execute.
```

**Consequence:** Any tool required by a `modify_*` script is a bootstrap dependency. It must be installed in `.bootstrap.*` (Phase 1) and declared with `bootstrap: true` in `.chezmoidata/packages.yaml`. Moving install scripts to `run_before_` does not help — `run_before_` scripts in `.chezmoiscripts/` still run after file sync, not before it.

### Package Management Strategy

| Layer                    | Unix-like  | Windows    | Purpose                                                                                                                                                             |
| ------------------------ | ---------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Core deps**            | Homebrew   | winget     | Platform-native package manager for OS-level tools (Git, Neovim, ripgrep, tmux, etc.)                                                                               |
| **Multi-platform tools** | mise       | mise       | Polyglot version manager for dev tools (Python, Node, jq, uv, ruff, etc.); mise itself is bootstrap-installed via the platform package manager (brew/pacman/winget) |
| **Python tools**         | xpip/UV    | xpip/UV    | Isolated Python CLI installs (xonsh, pre-commit)                                                                                                                    |
| **Editor plugins**       | Mason/Lazy | Mason/Lazy | Neovim LSPs, formatters, and plugins                                                                                                                                |

### Machine Detection

`.chezmoi.toml.tmpl` sets boolean variables consumed by all templates:

- `isMyMachine` / `isWorkMachine` / `isRiotMachine` — ownership
- `isDarwin` / `isLinux` / `isWindows` / `isUnixLike` / `isBsd` — platform
- Credentials flow through 1Password service account mode

### Script Stages

Scripts under `.chezmoiscripts/` run in numeric directory order during `chezmoi apply`:

| Stage | Purpose                             | Examples                                                                        |
| ----- | ----------------------------------- | ------------------------------------------------------------------------------- |
| `00/` | Sudoers setup                       | `configure-sudoers`                                                             |
| `10/` | Package managers + WSL provisioning | Homebrew install/sync, winget packages, WSL Arch Linux setup, font registration |
| `20/` | Tool managers                       | mise sync, xpip/UV sync, opam, pre-commit, xonsh, Neovim symlink                |
| `40/` | Self-managed symlinked file sync    | Copy externally-managed symlinked files pre-apply                               |
| `65/` | Log rotation                        | Rotate chezmoi/tool logs                                                        |
| `70/` | Editor plugin sync                  | Neovim Mason/Lazy plugin installs                                               |
| `90/` | Specialized setup                   | Terminfo compilation, Riot machine tooling (P4, LoL)                            |
| `99/` | Backup snapshots                    | Git-commit snapshots of symlinked files to `.backups/`                          |

Script naming encodes platform targeting: `.unix-like.sh`, `.darwin.sh`, `.windows.ps1`, `.shared.sh`. The `.chezmoiignore.tmpl` filters scripts by platform at apply time.

### Key Subsystems

- **Xonsh** — primary shell (`dot_config/xonsh/`)
- **Zsh** — fallback shell, modular configs in `.zsh/`
- **Neovim** — `dot_config/exact_nvim/`, Lazy plugin manager, Mason for LSP/formatters
- **Git** — aliases and config in `dot_config/git/`
- **AI tools** — `dot_claude/`, `dot_codex/`, `dot_gemini/`, each rendered from shared `AGENTS.md` template
- **Wezterm** — terminal emulator, cross-platform config in `dot_wezterm.lua`
- **Homebrew** — `dot_config/homebrew/Brewfile.tmpl`
- **Mise** — `dot_config/exact_mise/` + `.mise.toml`
- **WSL** — `dot_wslconfig` → `%USERPROFILE%\.wslconfig` (Windows-only; gated in `.chezmoiignore.tmpl`). Sets `networkingMode=mirrored` so `localhost` inside WSL reaches Windows-host services (e.g. the in-editor Unreal MCP server); requires Windows 11 22H2+ and `wsl --shutdown` to take effect.

## Setting Up a New Machine

Bootstrapping requires installing a couple things manually, so follow the platform-specific instructions and then follow [setup new machine][chez-new-machine].

### Unix-like

Use one of the [Chezmoi one-line install methods](https://www.chezmoi.io/install/#one-line-binary-install) unless Homebrew is already installed.

### Windows

Open Powershell and run:

```ps1
winget install twpayne.chezmoi AgileBits.1Password
```

For first-time bootstrapping with 1Password service mode, set the token in the
PowerShell session before running `chezmoi init`:

```ps1
$env:OP_SERVICE_ACCOUNT_TOKEN = Read-Host "OP_SERVICE_ACCOUNT_TOKEN"
chezmoi init <repo>
Remove-Item Env:OP_SERVICE_ACCOUNT_TOKEN
```

Or write the token once to `~/.secrets/OP_SERVICE_ACCOUNT_TOKEN`:

```ps1
$token = Read-Host "OP_SERVICE_ACCOUNT_TOKEN"
$secretDir = Join-Path $HOME ".secrets"
New-Item -ItemType Directory -Path $secretDir -Force | Out-Null
Set-Content -LiteralPath (Join-Path $secretDir "OP_SERVICE_ACCOUNT_TOKEN") -NoNewline -Value $token
```

## Also See

- [AGENTS.md](./AGENTS.md)
- [CLAUDE.md](./CLAUDE.md)

[chez-new-machine]: https://www.chezmoi.io/user-guide/daily-operations/#install-chezmoi-and-your-dotfiles-on-a-new-machine-with-a-single-command
