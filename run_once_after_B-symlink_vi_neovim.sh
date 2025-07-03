#!/usr/bin/env bash
set -euo pipefail

if [[ "$0" != *"${ONLY_SCRIPTS:-}"* ]]; then
  echo >&2 "INFO: Only running scripts with '${ONLY_SCRIPTS}'; Skipping $0"
  exit 0
else
  echo >&2 "INFO: Starting $0"
fi

TARGET_VI=/usr/local/bin/vi

if ! [[ "$(readlink "${TARGET_VI}")" =~ .*/nvim ]]; then
  echo "Removing ${TARGET_VI}..."
  sudo rm -v "${TARGET_VI}"
fi

if ! [ -e "${TARGET_VI}" ]; then
  sudo ln -s "$(which nvim)" /usr/local/bin/vi
fi

echo >&2 "INFO: Ending $0"
