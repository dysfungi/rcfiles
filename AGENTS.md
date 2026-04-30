# AGENTS.md

## Code Style & Quality

- Prefer Chezmoi-native file management/templates over scripts that mutate config files.
- Keep shared files (eg, INSTRUCTIONS.md) render-only in .chezmoitemplates, then render tool-specific files instead of installing as a custom dotfile (eg, `.chezmoitemplates/agents/AGENTS.md.tmpl` is better than `~/.config/agents/AGENTS.md`).
- Avoid global env/token side effects; scope credentials by host/tool when possible.
- For script execution order in Chezmoi, rely on explicit numeric ordering conventions, not environment folder grouping alone.
