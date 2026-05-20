#!/usr/bin/env bash
set -euo pipefail

echo >&2 "INFO: Starting $0"

# https://xon.sh/customization.html#set-xonsh-as-my-default-shell
if command -v xonsh; then
  BREW_XONSH="$(brew --prefix)/bin/xonsh"
  if [ -e "$BREW_XONSH" ]; then
    XONSH_EXECUTABLE="${BREW_XONSH}"
  else
    XONSH_EXECUTABLE="$(which xonsh)"
  fi
  if ! grep -q "${XONSH_EXECUTABLE}" /etc/shells; then
    echo "${XONSH_EXECUTABLE}" | sudo tee -a /etc/shells
  fi
  if [ "${XONSH_EXECUTABLE}" != "${SHELL}" ]; then
    chsh -s "${XONSH_EXECUTABLE}"
  fi
fi

echo >&2 "INFO: Ending $0"
