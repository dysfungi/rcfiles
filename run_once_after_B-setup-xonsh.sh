#!/usr/bin/env bash
set -euo pipefail

# https://xon.sh/customization.html#set-xonsh-as-my-default-shell
if command -v xonsh; then
  XONSH_EXECUTABLE="$(which xonsh)"
  if ! grep -q "${XONSH_EXECUTABLE}" /etc/shells; then
    echo "${XONSH_EXECUTABLE}" | sudo tee -a /etc/shells
  fi
  if [ "${XONSH_EXECUTABLE}" != "${SHELL}" ]; then
    chsh -s "${XONSH_EXECUTABLE}"
  fi
fi
