#!/usr/bin/env bash
set -euo pipefail

echo >&2 "INFO: Starting $0"

if ! command -v xonsh >/dev/null; then
  echo >&2 "WARNING: Could not find xonsh for xpip"
  exit 0
fi

userName="$(whoami)"
hostName="$(hostname)"
bakSuffix="${userName}.${hostName}"
bakDir="${CHEZMOI_SOURCE_DIR}/.backups"
bakFile="${bakDir}/xpip-freeze.${bakSuffix}"
reqFile="${HOME}/.default-python-packages"
export GIT_DIR="${CHEZMOI_SOURCE_DIR}/.git"
export GIT_WORK_TREE="${CHEZMOI_WORKING_TREE}"

HOMEBREW_XONSH="/opt/homebrew/bin/xonsh"
USR_BIN_XONSH="/usr/bin/xonsh"

LOGIN_SHELL=$(getent passwd "$USER" 2>/dev/null | cut -d: -f7)
if [[ "$LOGIN_SHELL" = */xonsh ]] && [ -f "$LOGIN_SHELL" ]; then
  XONSH_EXECUTABLE="$LOGIN_SHELL"
elif [ -f "$HOMEBREW_XONSH" ]; then
  XONSH_EXECUTABLE="$HOMEBREW_XONSH"
elif [ -f "$USR_BIN_XONSH" ]; then
  XONSH_EXECUTABLE="$USR_BIN_XONSH"
else
  echo >&2 "ERROR: xonsh not configured or installed at $HOMEBREW_XONSH or $USR_BIN_XONSH"
  exit 1
fi

backup() {
  local clarifier="${1:?required}"
  local action="${2:?required}"

  ${XONSH_EXECUTABLE} --no-rc -c "import sys; \$UV_PYTHON=@(sys.executable) uv pip freeze > '${bakFile}'"
  git add "${bakFile}"
  if ! git diff --cached --quiet -- "${bakDir}"; then
    git commit --message "chore(backups): Freeze xpip packages ${clarifier} ${action} for ${userName} on ${hostName}" -- "${bakDir}"
  fi
}

mkdir -p "${bakDir}"

backup before install
# https://xon.sh/customization.html#set-xonsh-as-my-default-shell
${XONSH_EXECUTABLE} --no-rc -c "\$UV_PYTHON=@(__import__('sys').executable) uv pip install --requirement=${reqFile} --upgrade --break-system-packages"
backup after install

echo >&2 "INFO: Ending $0"
