#!/usr/bin/env bash
set -euo pipefail

export PATH="${PATH}:/opt/homebrew/bin"

if ! command -v brew >/dev/null; then
  # https://brew.sh/
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

if ! command -v op >/dev/null; then
  brew install 1password-cli
fi
