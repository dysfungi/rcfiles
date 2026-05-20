#!/usr/bin/env bash
set -euo pipefail

export PATH="${PATH}:/opt/homebrew/bin"

# Fast-path: skip logging and installs if all bootstrap deps are present
if command -v brew >/dev/null 2>&1 && command -v op >/dev/null 2>&1; then
  exit 0
fi

echo >&2 "INFO: Starting $0"

if ! command -v brew >/dev/null 2>&1; then
  # https://brew.sh/
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

if ! command -v op >/dev/null 2>&1; then
  brew install 1password-cli
fi

echo >&2 "INFO: Ending $0"
