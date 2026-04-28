#!/usr/bin/env bash
set -euo pipefail

echo >&2 "INFO: Starting $0"

export PYTHON_VER=3.14
export TARGET_DIR="$HOME/.local/xonsh-env"
export XONSH_VER='xonsh[full]'

# https://xon.sh/install_mamba.html
# We patch the script on-the-fly to handle Windows paths:
# 1. python.exe is in the target dir root, not bin/
# 2. xonsh.exe is in Scripts/, not bin/
curl -fsSL https://xon.sh/install/mamba-install-xonsh.sh |
  sed 's|/bin/python|/python|g' |
  sed 's|/bin/xonsh|/Scripts/xonsh|g' |
  bash

echo >&2 "INFO: Ending $0"
