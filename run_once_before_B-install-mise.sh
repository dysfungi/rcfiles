#!/usr/bin/env bash
set -euo pipefail

if [[ "$0" != *"${ONLY_SCRIPTS:-}"* ]]; then
  echo >&2 "INFO: Only running scripts with '${ONLY_SCRIPTS:-}'; Skipping $0"
  exit 0
else
  echo >&2 "INFO: Starting $0"
fi

echo >&2 "INFO: Installing Mise..."
# https://mise.jdx.dev/installing-mise.html#https-mise-run
curl https://mise.run | MISE_INSTALL_PATH="${HOME}/.local/bin/mise" sh
echo >&2 "INFO: Installed Mise"
