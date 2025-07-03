#!/usr/bin/env bash
set -euo pipefail

if [[ "$0" != *"${ONLY_SCRIPTS:-}"* ]]; then
  echo >&2 "INFO: Only running scripts with '${ONLY_SCRIPTS}'; Skipping $0"
  exit 0
else
  echo >&2 "INFO: Starting $0"
fi

# https://lazy.folke.io/usage
nvim --headless "+MasonUpdate" "+MasonToolsInstallSync" "+MasonToolsUpdateSync" "+Lazy! sync" "+qa"

echo >&2 "INFO: Ending $0"
echo >&2
