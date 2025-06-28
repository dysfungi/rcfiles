#!/usr/bin/env bash
set -euo pipefail

# https://lazy.folke.io/usage
nvim --headless "+MasonUpdate" "+MasonToolsInstallSync" "+MasonToolsUpdateSync" "+Lazy! sync" "+qa"
