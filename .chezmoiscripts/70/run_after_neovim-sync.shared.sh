#!/usr/bin/env bash
set -euo pipefail

echo >&2 "INFO: Starting $0"

# https://lazy.folke.io/usage
nvim --headless "+MasonUpdate" "+MasonToolsInstallSync" "+MasonToolsUpdateSync" "+Lazy! sync" "+qa"

echo >&2 "INFO: Ending $0"
echo >&2
