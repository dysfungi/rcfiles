# Activate mise in interactive zsh via the .zshrc interactive glob: provides
# tool shims + a prompt hook that re-syncs PATH/env per directory. Intentional
# two-file split with env.zsh: .zshenv delivers [env] to non-interactive
# `zsh -c` shells too; the overlap is idempotent (mise diffs via __MISE_DIFF).
# https://mise.jdx.dev/installing-mise.html#zsh
command -v mise >/dev/null 2>&1 && eval "$(mise activate zsh)"
