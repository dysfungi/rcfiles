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

# Step 2: ensure treesitter parsers are compiled to site/parser/.
# nvim-treesitter (main branch) changed its install dir from inside the plugin
# (lazy/nvim-treesitter/parser/) to ~/.local/share/nvim/site/parser/. Stale
# binaries from a pre-migration install survive in the plugin dir (git-untracked,
# so `Lazy! sync` leaves them). Lazy only re-runs the build step when the plugin
# commit changes — if site/parser/ was cleared after a successful build, parsers
# won't be re-compiled until the next plugin update, causing query/parser drift:
#
#   "Invalid node type 'tab'" — vim/highlights.scm expects `tab` but the stale
#   parser binary (2025-03-29) predates the node; the fresh parser in site/parser/
#   supports it.
#
# `Lazy! build nvim-treesitter` re-runs the build function from init.lua (the
# same parser list, same install() call) with force=true at the Lazy task level,
# while install_lang still skips parsers already present in site/parser/ — making
# this a fast no-op on a healthy machine and a self-healing step when site/parser/
# is missing. Idempotent: safe to run on every chezmoi apply.
nvim --headless "+Lazy! build nvim-treesitter" "+qa"

# Step 3: update Mason registry and install/sync configured tools
nvim --headless "+MasonUpdate" "+MasonToolsInstallSync" "+MasonToolsUpdateSync" "+qa"

echo >&2 "INFO: Ending $0"
echo >&2
