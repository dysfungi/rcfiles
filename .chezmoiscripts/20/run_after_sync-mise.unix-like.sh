#!/usr/bin/env bash
set -euo pipefail

echo >&2 "INFO: Starting $0"

export PATH="${HOME}/.local/bin:${PATH}"

if ! command -v mise >/dev/null 2>&1; then
  echo >&2 "WARN: mise not found; skipping. Re-run 'chezmoi apply' after mise is installed."
  echo >&2 "INFO: Ending $0"
  exit 0
fi

userName="$(whoami)"
hostName="$(hostname)"
bakSuffix="${userName}.${hostName}"
bakDir="${CHEZMOI_SOURCE_DIR}/.backups"
bakFile="${bakDir}/mise-ls.${bakSuffix}"

_commit_backup() {
  local clarifier="${1:?required}"
  local action="${2:?required}"

  local -x GIT_DIR="${CHEZMOI_SOURCE_DIR}/.git"
  local -x GIT_WORK_TREE="${CHEZMOI_WORKING_TREE}"

  git add "${bakFile}"
  if ! git diff --cached --quiet -- "${bakDir}"; then
    git commit --message "chore(backups): List mise tools ${clarifier} ${action} for ${userName} on ${hostName}" -- "${bakDir}"
  fi
}

backup() {
  local clarifier="${1:?required}"
  local action="${2:?required}"

  mise ls >"${bakFile}"

  _commit_backup "${clarifier}" "${action}"
}

mkdir -p "${bakDir}"

backup before install
mise install --yes
backup after install

backup before upgrade
mise upgrade --yes
backup after upgrade

echo >&2 "INFO: Ending $0"
