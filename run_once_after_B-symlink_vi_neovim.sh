#!/usr/bin/env bash
set -euo pipefail

TARGET_VI=/usr/local/bin/vi

if ! [[ "$(readlink "${TARGET_VI}")" =~ .*/nvim ]]; then
  echo "Removing ${TARGET_VI}..."
  sudo rm -v "${TARGET_VI}"
fi

if ! [ -e "${TARGET_VI}" ]; then
  sudo ln -s "$(which nvim)" /usr/local/bin/vi
fi
