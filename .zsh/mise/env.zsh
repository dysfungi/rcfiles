# Deliver mise [env] vars (incl. ~/.config/mise/conf.d/secrets.toml) to ALL
# zsh shells — including non-interactive `zsh -c` — via the .zshenv env.zsh
# glob. Intentional two-file split with mise.zsh: interactive shells also run
# `mise activate` for tool shims + prompt hook; the overlap is idempotent
# (mise diffs applied changes via __MISE_DIFF).
# https://mise.jdx.dev/environments/
command -v mise >/dev/null 2>&1 && eval "$(mise env -s zsh)"
