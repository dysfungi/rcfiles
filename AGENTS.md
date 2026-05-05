# AGENTS.md

## Code Style & Quality

- Prefer Chezmoi-native file management/templates over scripts that mutate config files.
- Keep shared files (eg, INSTRUCTIONS.md) render-only in .chezmoitemplates, then render tool-specific files instead of installing as a custom dotfile (eg, `.chezmoitemplates/agents/AGENTS.md.tmpl` is better than `~/.config/agents/AGENTS.md`).
- Avoid global env/token side effects; scope credentials by host/tool when possible.
- For script execution order in Chezmoi, rely on explicit numeric ordering conventions, not environment folder grouping alone.

## Commit Semantics

- In this chezmoi repo, prefer conventional commit types to describe changes to the repo's managed desired state, not the downstream effect on the machine by default.
- For package-manager inventory changes (eg, Brewfile additions, removals, taps, or version-management entries), prefer `chore(...)` unless the change fixes broken repo behavior or adds a new repo-managed capability.
- Use `fix(...)` when correcting broken repo behavior (eg, bad template logic, broken install flow, invalid config, or a package declaration that fails to apply as intended).
- Use `feat(...)` only when the repo gains a new user-facing managed capability, workflow, or generated surface area, not merely because a package gets installed.
- If a repo-managed behavior is intentionally removed in a materially disruptive way and you want semantic emphasis, prefer `chore(...)!` with a `BREAKING CHANGE:` note rather than reclassifying it as `feat`.
- Let the scope name the subsystem being managed (eg, `homebrew`, `git`, `zsh`) while the type continues to describe the repo-maintenance intent.
