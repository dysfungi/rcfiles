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

- `is_my_machine` / `is_work_machine` / `is_riot_machine` — ownership
- `is_darwin` / `is_linux` / `is_windows` / `is_unix_like` / `is_bsd` — platform
- Credentials flow through 1Password service account mode

### Secrets

- **Render-time only:** templates resolve 1Password items via `onepasswordRead()` during `chezmoi apply`; nothing reads 1Password at shell startup.
- **Secret env vars** land in `~/.config/mise/conf.d/secrets.toml` (mode 0600) as a static `[env]` table — no exec templates, so mise can never abort on env resolution.
- **Shells** pick them up through mise: zsh evals `mise env -s zsh` (`.zshenv`) and `mise activate zsh` (`.zshrc`); bash evals `mise env -s bash`; PowerShell evals `mise env -s pwsh`; xonsh evals `mise hook-env -s xonsh` (`dot_config/xonsh/exact_rc.d/20-environment.xsh`).
- **Bootstrap:** `OP_SERVICE_ACCOUNT_TOKEN` must be exported before `chezmoi init` — `.chezmoi.toml.tmpl` fails loudly when it is absent (no prompt).
- **Unattended updates** get the token via `mise x` (see Automatic Updates).

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
| `90/` | Specialized setup                   | Terminfo compilation, Riot machine tooling (P4, LoL), daily auto-update cron    |
| `99/` | Backup snapshots                    | Git-commit snapshots of symlinked files to `.backups/`                          |

Script naming encodes platform targeting: `.unix-like.sh`, `.darwin.sh`, `.windows.ps1`, `.shared.sh`. The `.chezmoiignore.tmpl` filters scripts by platform at apply time.

### Automatic Updates

Each machine runs `mise x -- chezmoi update --init --verbose` daily via a cron job registered by the stage-90 install script. `crontab` is the single interface on both macOS and Linux; the daemon implementation differs (macOS: built-in, Arch/WSL: `cronie`).

**Components:**

| File                               | Role                                                                                                                                                                                                                                                                             |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `~/.local/bin/chezmoi-update-cron` | Runner invoked by cron. Sets PATH, exports `SUDO_ASKPASS`, takes a lock, runs `mise x -- chezmoi update` (mise injects `OP_SERVICE_ACCOUNT_TOKEN` from `~/.config/mise/conf.d/secrets.toml`), logs to `~/.local/state/chezmoi/update-cron.log`. Fails loudly if mise is missing. |
| `~/.local/bin/chezmoi-askpass`     | `SUDO_ASKPASS` helper. Reads the sudo password from 1Password: `op://Private/sudo/password` (personal) or `op://Riot/sudo/password` (Riot).                                                                                                                                      |
| `~/.local/bin/chezmoi-sudo`        | `sudo` wrapper. Falls back: cached creds → interactive prompt → `sudo -A` (1Password) → WARN+skip (exit 0). Never blocks.                                                                                                                                                        |

**One-time setup (per machine):**

1. Create the 1Password sudo-password item:

   ```sh
   op item create --category Login --title "sudo" --vault Private password="<your-user-password>"
   ```

   (Riot machines: vault `Riot`, title `sudo`.)

2. **macOS only:** Grant `cron` Full Disk Access in _System Settings → Privacy & Security → Full Disk Access_ — add `/usr/sbin/cron`. Without this, cron silently fails on protected paths.

3. Run `chezmoi apply` once interactively to register the cron job.

**Caveats:**

- Plain cron does not catch up missed runs (e.g. laptop was sleeping). The midday schedule mitigates this for laptops that are awake during the day.
- New Homebrew casks that require privileged install should be applied interactively (`chezmoi apply`); `brew bundle`'s internal `sudo` calls bypass `chezmoi-sudo` and may be skipped unattended.
- Skipped privileged steps emit a `WARN` to the log and are deferred to the next interactive apply — they never fail silently.

### Key Subsystems

- **Xonsh** — primary shell (`dot_config/xonsh/`)
- **Zsh** — fallback shell, modular configs in `.zsh/`
- **Neovim** — `dot_config/exact_nvim/`, Lazy plugin manager, Mason for LSP/formatters
- **Git** — aliases and config in `dot_config/git/`
- **AI tools** — `dot_claude/`, `dot_codex/`, `dot_gemini/`, `dot_pi/agent/` (`~/.pi/agent/`), each rendered from shared `AGENTS.md` template
- **Wezterm** — terminal emulator, cross-platform config in `dot_wezterm.lua`
- **Homebrew** — `dot_config/homebrew/Brewfile.tmpl`
- **Mise** — `dot_config/exact_mise/` + `.mise.toml`
- **WSL** — `dot_wslconfig` → `%USERPROFILE%\.wslconfig` (Windows-only; gated in `.chezmoiignore.tmpl`). Sets `networkingMode=mirrored` so `localhost` inside WSL reaches Windows-host services (e.g. the in-editor Unreal MCP server); requires Windows 11 22H2+ and `wsl --shutdown` to take effect.

## Setting Up a New Machine

Bootstrapping requires installing a couple things manually, so follow the platform-specific instructions and then follow [setup new machine][chez-new-machine].

### Unix-like

Use one of the [Chezmoi one-line install methods](https://www.chezmoi.io/install/#one-line-binary-install) unless Homebrew is already installed.

`chezmoi init` requires the 1Password service-account token in the environment — the config template fails loudly without it:

```sh
read -rs OP_SERVICE_ACCOUNT_TOKEN && export OP_SERVICE_ACCOUNT_TOKEN
chezmoi init <repo>
unset OP_SERVICE_ACCOUNT_TOKEN
```

After the first `chezmoi apply`, subsequent runs get the token from `~/.config/mise/conf.d/secrets.toml` via `mise x -- chezmoi ...` (see Secrets).

### Windows

Open Powershell and run:

```ps1
winget install twpayne.chezmoi AgileBits.1Password
```

`chezmoi init` requires the 1Password service-account token in the environment — the config template fails loudly without it. Set it in the PowerShell session before running `chezmoi init`:

```ps1
$env:OP_SERVICE_ACCOUNT_TOKEN = Read-Host "OP_SERVICE_ACCOUNT_TOKEN"
chezmoi init <repo>
Remove-Item Env:OP_SERVICE_ACCOUNT_TOKEN
```

## Also See

- [AGENTS.md](./AGENTS.md)
- [CLAUDE.md](./CLAUDE.md)

[chez-new-machine]: https://www.chezmoi.io/user-guide/daily-operations/#install-chezmoi-and-your-dotfiles-on-a-new-machine-with-a-single-command
