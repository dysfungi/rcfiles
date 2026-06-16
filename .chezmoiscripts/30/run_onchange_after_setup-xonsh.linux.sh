#!/usr/bin/env bash
# Register xonsh in /etc/shells and set as the default login shell.
# Mirrors run_onchange_after_setup-xonsh.darwin.sh for Linux (mamba xonsh env).
set -euo pipefail

echo >&2 "INFO: Starting $0"

XONSH_EXECUTABLE="$HOME/.local/xonsh-env/bin/xonsh"

if [ ! -f "$XONSH_EXECUTABLE" ]; then
  echo >&2 "ERROR: $XONSH_EXECUTABLE does not exist"
  exit 1
elif [ "$XONSH_EXECUTABLE" != "${SHELL:-}" ]; then
  # chsh requires PAM auth which is not wired in WSL; usermod is sudo-friendly
  chezmoi-sudo usermod -s "$XONSH_EXECUTABLE" "$USER"
  echo >&2 "INFO: Set $XONSH_EXECUTABLE as default shell for $USER!"
fi

echo >&2 "INFO: Ending $0"
