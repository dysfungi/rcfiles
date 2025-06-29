#!/usr/bin/env bash
set -euo pipefail

if command -v xonsh; then
  XONSH_EXECUTABLE="$(which xonsh)"
  if ! grep -q "${XONSH_EXECUTABLE}" /etc/shells; then
    echo "${XONSH_EXECUTABLE}" | sudo tee -a /etc/shells
  fi
  chsh -s "${XONSH_EXECUTABLE}"
fi
