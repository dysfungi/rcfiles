#!/usr/bin/env bash
set -euo pipefail

if [[ "$0" != *"${ONLY_SCRIPTS:-}"* ]]; then
  echo >&2 "INFO: Only running scripts with '${ONLY_SCRIPTS:-}'; Skipping $0"
  exit 0
else
  echo >&2 "INFO: Starting $0"
fi

if [ "$(uname -s)" != Darwin ]; then
  echo "INFO: Not Darwin; Skipping Homebrew install..."
  exit 0
fi

echo >&2 "INFO: Installing Homebrew..."
# https://brew.sh/
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
echo >&2 "INFO: Installed Homebrew"
