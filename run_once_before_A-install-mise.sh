#!/usr/bin/env bash
set -euo pipefail

# https://mise.jdx.dev/installing-mise.html#https-mise-run
curl https://mise.run | MISE_INSTALL_PATH="${HOME}/.local/bin/mise" sh
