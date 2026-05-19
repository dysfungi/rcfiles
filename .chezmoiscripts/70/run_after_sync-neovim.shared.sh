#!/usr/bin/env bash
set -euo pipefail

echo >&2 "INFO: Starting $0"

# Non-interactive bash doesn't source .bashrc, so mise shims aren't in PATH.
# --shims mode adds the shims dir without installing hooks (safe for scripts).
if command -v mise >/dev/null 2>&1; then
  eval "$(mise activate bash --shims)"
fi

# Bootstrap: seed an empty lazy-lock.json if the symlink target doesn't exist.
# On a fresh machine the per-host file (.symlinked/…/lazy-lock.<user>.<host>.json)
# hasn't been created yet, so the symlink is dangling and Lazy.nvim aborts.
lazy_lock="${HOME}/.config/nvim/lazy-lock.json"
if [ ! -f "$lazy_lock" ]; then
  lock_target="$(readlink "$lazy_lock" 2>/dev/null || true)"
  if [ -n "$lock_target" ]; then
    mkdir -p "$(dirname "$lock_target")"
    printf '{}' >"$lock_target"
  else
    printf '{}' >"$lazy_lock"
  fi
fi

# Step 1: install/sync all plugins first — Mason is a plugin and must exist
# before its commands are available.
# https://lazy.folke.io/usage
nvim --headless "+Lazy! sync" "+qa"

# Step 2: update Mason registry and install/sync configured tools
nvim --headless "+MasonUpdate" "+MasonToolsInstallSync" "+MasonToolsUpdateSync" "+qa"

echo >&2 "INFO: Ending $0"
echo >&2
