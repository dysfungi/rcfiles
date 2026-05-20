#!/usr/bin/env bash
set -euo pipefail

echo >&2 "INFO: Starting $0"

XONSH_EXECUTABLE="$HOME/.local/xonsh-env/bin/xonsh"

# https://xon.sh/customization.html#set-xonsh-as-my-default-shell
if [ ! -f "$XONSH_EXECUTABLE" ]; then
  echo >&2 "ERROR: Cannot set xonsh as default shell; does not exist at $XONSH_EXECUTABLE"
elif [ "${XONSH_EXECUTABLE}" != "${SHELL}" ]; then
  if ! grep -q "${XONSH_EXECUTABLE}" /etc/shells; then
    echo "${XONSH_EXECUTABLE}" | sudo tee -a /etc/shells
    echo >&2 "INFO: Added $XONSH_EXECUTABLE to /etc/shells"
  fi

  chsh -s "${XONSH_EXECUTABLE}"
  echo >&2 "INFO: Set $XONSH_EXECUTABLE as default shell!"
fi

echo >&2 "INFO: Ending $0"
