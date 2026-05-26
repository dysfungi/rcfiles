# AGENTS.md

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
- When adding, removing, or renaming script stages, bootstrap steps, or platform architecture (package management layers, machine detection variables), update the corresponding README sections in the same commit.

## Programming & Engineering

### Bash Scripting Conventions

- **Scoped Environment Variables:** When setting environment variables that are only needed for a subset of commands within a Bash function, use `local -x VAR_NAME="value"` instead of global `export VAR_NAME="value"`. This limits the scope of the variable to the function and its child processes, preventing unintended side effects on subsequent commands.
- **Isolate Git Operations:** When manipulating files and tracking them with `git` in the same logical operation (e.g., backups), decompose the `git` commands into a separate helper function (e.g., `_commit_backup`). Apply `local -x GIT_DIR` and `local -x GIT_WORK_TREE` _only_ within this helper function to strictly scope the git environment variables and avoid polluting the environment of non-git commands.

## Platform Conventions

- Prefer OS-specific files (`.darwin.sh`, `.linux.sh`, `.windows.ps1`) over in-script platform branching (`if/case` on `uname`, distro checks, etc.). Let `.chezmoiignore.tmpl` handle platform filtering.
- Use consistent platform suffix naming: `.darwin.*`, `.linux.*`, `.windows.*`, `.unix-like.*` (genuinely cross-Unix only), `.shared.*` (all platforms).

## Package Management

- Package definitions live in `.chezmoidata/packages.yaml` — do not hardcode package lists in scripts (except bootstrap-critical deps in `.bootstrap.*.sh`/`.bootstrap.*.ps1`).
- Package entry schema and ordering convention is documented in the `.chezmoidata/packages.yaml` header comment.
- Package sync scripts must: backup before and after to `.backups/<tool>.<user>.<host>` (no `.log` extension; period-separated; `whoami` and `hostname` as-is), git-commit each snapshot. The git diff history in `.backups/` is the audit trail.
- Declarative removal (uninstalling packages not in the declared list) is not universally implemented — confirm per-script before assuming it applies.
- In chezmoi Go templates, use `index $pkg "key"` (not `$pkg.key`) to safely access optional fields in `.chezmoidata` maps. Dot-notation panics with `map has no entry for key` when the key is absent; `index` returns nil (falsy) for missing keys.

## Commit Semantics

- **One logical change per commit** — each commit must touch only the files directly required for that single change. When a task spans multiple files with independent concerns (eg, fixing `aliases.xsh` and `prompt.xsh` are separate fixes), commit them separately. Resist the urge to bundle "all the Windows fixes" into one commit.

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

## Also See

- [CLAUDE.md](./CLAUDE.md) — bootstrapping instructions for new machines.
- [README.md](./README.md)
