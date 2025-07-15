#!/usr/bin/env bash
set -euo pipefail

echo >&2 "INFO: Starting $0"

if ! command -v xonsh >/dev/null; then
  echo >&2 "WARNING: Could not find xonsh for xpip"
  exit 0
fi

scriptName="$(basename "$0")"
outFile="$(mktemp -t "${scriptName}.out")"
echo >&2 "INFO: Stdout file for ${scriptName} - ${outFile}"

userName="$(whoami)"
hostName="$(hostname)"
bakSuffix="${userName}.${hostName}"
bakDir="${CHEZMOI_SOURCE_DIR}/.backups"
bakFile="${bakDir}/xpip-freeze.${bakSuffix}"
reqFile="${HOME}/.default-python-packages"
export GIT_DIR="${CHEZMOI_SOURCE_DIR}/.git"
export GIT_WORK_TREE="${CHEZMOI_WORKING_TREE}"

backup() {
  local clarifier="${1:?required}"
  local action="${2:?required}"

  xonsh --no-rc -c "import sys; \$UV_PYTHON=@(sys.executable) uv pip freeze > '${bakFile}'"
  git add "${bakFile}"
  if [ -n "$(git status --porcelain -- "${bakDir}")" ]; then
    git commit --message "chore(backups): Freeze xpip packages ${clarifier} ${action} for ${userName} on ${hostName}" -- "${bakDir}"
  fi
}

mkdir -p "${bakDir}"

{
  backup before install
  xonsh --no-rc -c "\$UV_PYTHON=@(__import__('sys').executable) uv pip install --requirement=${reqFile} --upgrade"
  backup after install
} >>"${outFile}"

echo >&2 "INFO: Ending $0"
