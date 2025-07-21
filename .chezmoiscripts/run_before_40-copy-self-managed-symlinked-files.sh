#!/usr/bin/env bash
set -euo pipefail

echo >&2 "INFO: Starting $0"

symlinkedDir="${CHEZMOI_SOURCE_DIR}/.symlinked/"
configDir="${HOME}/.config"
sourceLazyLockFile="${symlinkedDir}/config/nvim/lazy-lock.${USER}.${HOSTNAME}.json"
targetLazyLockFile="${configDir}/nvim/lazy-lock.json"

if [[ -f "${targetLazyLockFile}" && ! -L "${targetLazyLockFile}" ]]; then
  cp -v "${targetLazyLockFile}" "${sourceLazyLockFile}"
fi

echo >&2 "INFO: Ending $0"
