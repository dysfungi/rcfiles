#!/usr/bin/env bash
# Register xonsh in /etc/shells and set as the default login shell.
# Mirrors run_once_after_setup-xonsh.darwin.sh for Linux (mise pip:xonsh path).
set -euo pipefail

echo >&2 "INFO: Starting $0"

if command -v xonsh >/dev/null 2>&1; then
  XONSH_EXECUTABLE="$(which xonsh)"
else
  echo >&2 "ERROR: xonsh not found in PATH. PATH=$PATH"
  exit 1
fi

if ! grep -qF "$XONSH_EXECUTABLE" /etc/shells; then
  echo "$XONSH_EXECUTABLE" | sudo tee -a /etc/shells
fi
if [ "$XONSH_EXECUTABLE" != "${SHELL:-}" ]; then
  # chsh requires PAM auth which is not wired in WSL; usermod is sudo-friendly
  sudo usermod -s "$XONSH_EXECUTABLE" "$USER"
fi

echo >&2 "INFO: Ending $0"
