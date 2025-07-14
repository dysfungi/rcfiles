#!/usr/bin/env bash
set -euo pipefail

echo >&2 "INFO: Starting $0"

echo >&2 "INFO: Installing Mise..."
# https://mise.jdx.dev/installing-mise.html#https-mise-run
curl https://mise.run | MISE_INSTALL_PATH="${HOME}/.local/bin/mise" sh
echo >&2 "INFO: Installed Mise"
