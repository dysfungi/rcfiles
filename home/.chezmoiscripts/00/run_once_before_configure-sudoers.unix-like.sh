#!/usr/bin/env bash
set -euo pipefail

echo >&2 "INFO: Starting $0"

if [ ! -d /etc/sudoers.d ]; then
  echo >&2 "ERROR: Could not find /etc/sudoers.d/"
  exit 1
fi

echo >&2 "INFO: Installing sudoer..."
sudo tee "/etc/sudoers.d/${USER}" <<-EOF
# 4 hour timeout per terminal
# https://unix.stackexchange.com/a/515148
Defaults	timestamp_timeout = 480
EOF
echo >&2 "INFO: Installed sudoer"
