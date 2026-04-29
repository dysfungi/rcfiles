#!/usr/bin/env bash
set -euo pipefail

echo >&2 "INFO: Starting $0"

if ! command -v logrotate >/dev/null 2>&1; then
  echo >&2 "WARNING: logrotate is not installed; skipping log rotation."
  echo >&2 "INFO: Install with Homebrew: brew install logrotate"
  echo >&2 "INFO: Ending $0"
  exit 0
fi

configFile="${HOME}/.config/logrotate/chezmoi.conf"
stateDir="${HOME}/.local/state/logrotate"
stateFile="${stateDir}/chezmoi.status"

if [ ! -f "$configFile" ]; then
  echo >&2 "INFO: No logrotate config found at $configFile; skipping."
  echo >&2 "INFO: Ending $0"
  exit 0
fi

mkdir -p "$stateDir"
logrotate --state "$stateFile" "$configFile"

echo >&2 "INFO: Ending $0"
