#!/usr/bin/env bash
set -euo pipefail
# ~/.terminfo hash: {{ include "~/.terminfo" | sha256sum }}

echo >&2 "INFO: Starting $0"

# https://wezterm.org/config/lua/config/term.html
for terminfo in ~/.terminfo/*.terminfo; do
  tic -x -o "${HOME}/.terminfo" "${terminfo}"
done

echo >&2 "INFO: Ending $0"
