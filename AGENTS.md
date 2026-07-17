# AGENTS.md / CLAUDE.md / GEMINI.md

This file is the single source of truth for AI coding agents in this repo. `CLAUDE.md` and `GEMINI.md` are symlinks to this file.

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
mise x -- pre-commit run --all-files
```

Run a single hook:

```sh
mise x -- pre-commit run shellcheck --all-files
```

Run regression tests:

```sh
mise run test
```

The `mise x --` prefix is required for `pre-commit` because it is mise-managed (pre-commit via `mise: pre-commit`). Tests run via `mise run test`, which uses `uv run` to resolve the declared `test` dependency group (pytest + pyyaml) from `pyproject.toml`.

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

| Stage | Purpose                                                               |
| ----- | --------------------------------------------------------------------- |
| `00/` | Sudoers setup                                                         |
| `10/` | Core/system deps: package manager and tool manager installers + syncs |
| `20/` | Dev deps: language runtimes and toolchains (mise install, setup-opam) |
| `30/` | Shell registration: xonsh in /etc/shells, set as default              |
| `40/` | App-level deps: Python packages via xpip/UV                           |
| `50/` | Self-managed symlinked file sync (pre-apply)                          |
| `65/` | Log rotation                                                          |
| `70/` | Editor plugin sync (Neovim/Mason)                                     |
| `90/` | Specialized setup (terminfo, Riot machine P4/LoL tooling)             |
| `99/` | Git-commit backup snapshots of symlinked files                        |

### Machine Detection

`.chezmoi.toml.tmpl` sets boolean template variables consumed everywhere:

- `is_my_machine` — username is `dmf`
- `is_riot_machine` — username is `dfrank` or RIOTGAMES domain
- `is_work_machine` — any non-personal machine
- OS booleans: `is_darwin`, `is_linux`, `is_windows`, `is_unix_like`, `is_bsd`

Credentials flow through 1Password (`onepasswordRead()`) at render time. `OP_SERVICE_ACCOUNT_TOKEN` must be exported before `chezmoi init` (the config template fails loudly without it); afterwards mise injects it from the rendered `~/.config/mise/conf.d/secrets.toml` (0600), so run chezmoi via `mise x -- chezmoi ...`.

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
- **AI tools**: `dot_claude/`, `dot_codex/`, `dot_gemini/`, `dot_pi/agent/`, `dot_omp/agent/` — omp is a side-by-side trial with reduced parity; deferred work is tracked in `todo.txt`
- **Homebrew**: `dot_config/homebrew/Brewfile.tmpl`
- **Mise**: polyglot tool version manager, `dot_config/exact_mise/` + `.mise.toml`

## Chezmoi Workflow

- When working in this repo, always consider whether new config/settings files belong under chezmoi management. If a dotfile is created or modified outside the chezmoi source tree, add it to the source tree before finishing the task.

- After editing any managed dotfile in this repo, **always run `chezmoi apply <target-path>` immediately** — do not wait to be asked. The live files are stale until applied, making testing impossible.

- When running `chezmoi apply` for specific files, pass **target paths** (e.g. `~/.config/nvim/init.lua`), not source-relative paths (e.g. `dot_config/exact_nvim/init.lua`). Chezmoi maps source names to target names; passing source paths returns a "not managed" error.

## Code Style & Quality

- Prefer Chezmoi-native file management/templates over scripts that mutate config files.
- Keep shared files (eg, INSTRUCTIONS.md) render-only in .chezmoitemplates, then render tool-specific files instead of installing as a custom dotfile (eg, `.chezmoitemplates/agents/AGENTS.md.tmpl` is better than `~/.config/agents/AGENTS.md`).
- Avoid global env/token side effects; scope credentials by host/tool when possible.
- For script execution order in Chezmoi, rely on explicit numeric ordering conventions, not environment folder grouping alone.
- All chezmoi scripts must log start/end to stderr: sh scripts use `echo >&2 "INFO: Starting $0"` / `echo >&2 "INFO: Ending $0"`; PowerShell scripts use `Write-Host "INFO: Starting $PSCommandPath"` / `Write-Host "INFO: Ending $PSCommandPath"`.
- **Vim filetype modeline for `.tmpl` files**: By default, no modeline is needed — `vim.filetype.add` in the Neovim config auto-reconstructs the chezmoi target basename (stripping attribute prefixes and `dot_` → `.`) and returns a compound `gotmpl.<lang>` type, so `{{ }}` directives highlight correctly and host-language Vim syntax applies automatically. **Only add a modeline when the filename lies about the body** (e.g. a `.json.tmpl` whose script body is Python, not JSON). In that case, use `# vim: ft=gotmpl.<lang>` on line 2 (after the shebang if present), and **only** in files where the comment won't leak into rendered output — `modify_*` scripts are safe (comment lives in the script, not its stdout); direct-render configs (`.toml.tmpl`, `.yml.tmpl`, etc.) and files without comment syntax (`.json.tmpl`, secrets, symlink targets) must rely on the centralized rule. Example: `# vim: ft=gotmpl.python` in `modify_config.json.tmpl` whose body is a Python script.
- When adding, removing, or renaming script stages, bootstrap steps, or platform architecture (package management layers, machine detection variables), update the corresponding README sections in the same commit.
- **Legitimate pre-commit excludes** in this repo are structural incompatibilities only (binary-like JSON, vendored files). The general hooks-are-the-contract rule (fix the source; never skip a hook or add `# noqa` / `# fmt: skip` / `exclude:` workarounds without explicit approval) lives in the `my-linting` skill.

## Programming & Engineering

### Bash Scripting Conventions

- **Scoped Environment Variables:** When setting environment variables that are only needed for a subset of commands within a Bash function, use `local -x VAR_NAME="value"` instead of global `export VAR_NAME="value"`. This limits the scope of the variable to the function and its child processes, preventing unintended side effects on subsequent commands.
- **Isolate Git Operations:** When manipulating files and tracking them with `git` in the same logical operation (e.g., backups), decompose the `git` commands into a separate helper function (e.g., `_commit_backup`). Apply `local -x GIT_DIR` and `local -x GIT_WORK_TREE` _only_ within this helper function to strictly scope the git environment variables and avoid polluting the environment of non-git commands.

## Testing

- Pytest harness lives at `.tests/` (shared `conftest.py` at the root + tests organized by domain/scope underneath). Run from the repo root via `mise run test`, which invokes `uv run --group test` to resolve the declared `test` dependency group (pytest + pyyaml) from `pyproject.toml`.
- The fast gate uses duration classification: `--fast` deselects tests with stored full-protocol duration ≥0.2s. Unknown or new tests default to slow (fail-safe). The clean runtime distribution has a 0.1–0.2s gap between in-process tests and process-launching tests, making 0.2s a robust boundary.
- Regenerate the committed `.test_durations` with `mise run "test:durations"` on a clean, unloaded machine whenever adding or changing tests. The generator conservatively max-merges samples; loaded-machine data can only over-quarantine.
- The fast pre-commit gate runs `--fail-slow 0.5` as a drift guard. It catches selected tests that exceed 0.5s, but an existing test drifting from <0.2s to 0.2–0.5s is not caught until duration regeneration. `@pytest.mark.slow` remains the manual force-slow override.
- **Iteration discipline:** while fixing tests, run only the relevant file or node ID (`mise x -- uv run --group test pytest path/to/test_x.py::test_name`), not the full suite. Reserve full-suite runs for the final pre-commit gate. Use `mise x -- pre-commit run --files <touched>` during iteration; the `pytest (fast)` hook still runs the whole fast set because it has `pass_filenames: false`. Real subprocess harnesses (Pi, Node, Git, xonsh, tmux PTYs) are contention-sensitive, so scoped iteration matters most there. On a timeout, diagnose contention with `uptime` and `ps aux` before assuming a regression; never kill unrelated processes without authorization.
- **Layout — organize by domain/scope.** Mirror the repo's subsystem boundaries: `.tests/<subsystem>/test_<subject>.py`. Examples:
  - `.tests/chezmoiscripts/test_run_after_sync_mise.py` — tests for `.chezmoiscripts/20/run_after_sync-mise.unix-like.sh`
  - `.tests/claude-hooks/test_bash_worktree_guard.py` — tests for `.claude/hooks/bash_worktree_guard.py`
  - `.tests/hooks/test_validate_chezmoi_templates.py` — tests for `.hooks/validate-chezmoi-templates.py`

  One file per script-or-hook under test; multiple test functions per file when a single artifact has multiple behaviors. New tests go in domain dirs from now on; pre-existing flat files stay until naturally touched.

- Convention: parametrized tables with descriptive `ids=` per case. See `.tests/test_bash_worktree_guard.py` for the canonical shape — parametrized truth tables serve as the executable spec.
- For shell scripts and non-Python artifacts, write subprocess-driven integration tests that invoke the artifact as a real user would. Build a tmp env (HOME tree, fake PATH stubs, tmp git repos for CHEZMOI\_\* vars). Do not refactor production code purely to expose internals for unit testing — the harness adapts to production shape, not vice versa.
- Avoid testing anti-patterns (config/catalog value mirrors, template-rendering assertions, live-config-coupled tests, etc.) — see the `my-testing` skill for the full list, exceptions, and trade-offs. In this repo, template render-validation belongs to the `validate-chezmoi-templates` pre-commit linter and `chezmoi apply`; never assert rendered template content in pytest. Pytest is for behavior of scripts, hooks, and tools (rendering a template as setup for exercising its script body is fine).
- When adding new functionality with a regression class, add the test file in the same commit.

## Platform Conventions

- Prefer OS-specific files (`.darwin.sh`, `.linux.sh`, `.windows.ps1`) over in-script platform branching (`if/case` on `uname`, distro checks, etc.). Let `.chezmoiignore.tmpl` handle platform filtering.
- Use consistent platform suffix naming: `.darwin.*`, `.linux.*`, `.windows.*`, `.unix-like.*` (genuinely cross-Unix only), `.shared.*` (all platforms).

## Package Management

- Package definitions live in `.chezmoidata/packages.yaml` — do not hardcode package lists in scripts (except bootstrap-critical deps in `.bootstrap.*.sh`/`.bootstrap.*.ps1`).
- **Bootstrap dependency rule:** Any tool required by a `modify_*` script is a bootstrap dependency and must be installed in all three `.bootstrap.*` scripts (not in chezmoiscript stages). Reason: `modify_*` scripts execute during the file-sync phase (Phase 2), which runs _before_ any `run_after_` chezmoiscript (Phase 3). A tool not present in Phase 1 will cause `chezmoi apply` to fail on a fresh machine. Mark these in `packages.yaml` with `bootstrap: true`. See README.md Bootstrap Flow for the full phase diagram.
- Package entry schema and ordering convention is documented in the `.chezmoidata/packages.yaml` header comment.
- Package sync scripts must: backup before and after to `.backups/<tool>.<user>.<host>` (no `.log` extension; period-separated; `whoami` and `hostname` as-is), git-commit each snapshot. The git diff history in `.backups/` is the audit trail.
- Declarative removal (uninstalling packages not in the declared list) is not universally implemented — confirm per-script before assuming it applies.
- In chezmoi Go templates, use `index $pkg "key"` (not `$pkg.key`) to safely access optional fields in `.chezmoidata` maps. Dot-notation panics with `map has no entry for key` when the key is absent; `index` returns nil (falsy) for missing keys.

## Commit Semantics

- In this chezmoi repo, prefer conventional commit types to describe changes to the repo's managed desired state, not the downstream effect on the machine by default.
- For package-manager inventory changes (eg, Brewfile additions, removals, taps, or version-management entries), prefer `chore(...)` unless the change fixes broken repo behavior or adds a new repo-managed capability.
- Use `fix(...)` when correcting broken repo behavior (eg, bad template logic, broken install flow, invalid config, or a package declaration that fails to apply as intended).
- Use `feat(...)` only when the repo gains a new user-facing managed capability, workflow, or generated surface area, not merely because a package gets installed.
- If a repo-managed behavior is intentionally removed in a materially disruptive way and you want semantic emphasis, prefer `chore(...)!` with a `BREAKING CHANGE:` note rather than reclassifying it as `feat`.
- Let the scope name the subsystem being managed (eg, `homebrew`, `git`, `zsh`) while the type continues to describe the repo-maintenance intent.

## todo.txt

Maintain `todo.txt` and `done.txt` at the repo root in [todo.txt format](https://github.com/todotxt/todo.txt-cli/wiki/User-Documentation).
Both files are ignored by chezmoi (never deployed). Keep them in sync with active agent plans and task lists.

**Prioritization** — use todo.txt priority markers:

| Priority | Meaning                                     | Examples                                    |
| -------- | ------------------------------------------- | ------------------------------------------- |
| `(A)`    | Blocking — broken repo behavior             | chezmoi apply failures, broken templates    |
| `(B)`    | Important — gaps or deferred fixes          | missing platform support, known workarounds |
| `(C)`    | Maintenance — refactors, cleanup, tech debt | scattered PATH exports, dead code           |
| _(none)_ | Nice-to-have — exploratory, low urgency     | new tooling ideas                           |

**Sync rules:**

- When adding a task to the session task tracker (eg, TaskCreate), add a corresponding `todo.txt` entry if the work is durable/deferred (not completed this session).
- When completing a deferred item from `todo.txt` during a session, move it to `done.txt` with an `x YYYY-MM-DD` prefix (the todo.txt CLI archive convention). Do not delete completed tasks.
- When a new plan is written, check `todo.txt` for related existing entries and reference or close them.

## Bash Command Worktree Guard (Claude Code)

Claude Code-specific: a `PreToolUse` hook (`bash_worktree_guard.py`) blocks mutating Bash commands on the main worktree. Pi enforces the same policy via its `worktree-guard.ts` extension with the same denylist. Blocked categories:

| Category         | Blocked                                                                                | Allowed                            |
| ---------------- | -------------------------------------------------------------------------------------- | ---------------------------------- |
| git stash        | `git stash`, `git stash push/pop/apply/save`                                           | `git stash list`, `git stash show` |
| git history      | `git commit`, `git merge`, `git rebase`, `git cherry-pick`, `git am`, `git apply`      | —                                  |
| git working-tree | `git add`, `git checkout`, `git restore`, `git reset`, `git rm`, `git mv`, `git clean` | all other subcommands              |
| In-place edit    | `sed -i` (any flag combination)                                                        | `sed` without `-i`                 |
| Shell redirects  | `>`, `>>` (stdout)                                                                     | `2>`, `>&` (stderr/fd)             |
| File write       | `tee`                                                                                  | —                                  |
| File ops         | `rm`, `mv`, `cp`                                                                       | —                                  |

The guard uses the same worktree detection and exemption mechanism as the Write/Edit hook (compare `git rev-parse --git-dir` vs `--git-common-dir`; honor `.claude/worktree-exempt.$CLAUDE_CODE_SESSION_ID`). All commands are allowed when inside a linked worktree or when exempted.

This is best-effort, not a sandbox — obfuscated mutations (e.g., `python3 -c "open(...).write(...)"`) bypass it. Always follow the Multi-instance worktrees protocol in your agent instructions.

## Also See

- [README.md](./README.md)
