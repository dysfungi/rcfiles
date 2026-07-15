#!/usr/bin/env bash
set -euo pipefail

echo >&2 "INFO: Starting $0"

if ! command -v mise >/dev/null; then
  echo >&2 "WARNING: mise not found; skipping pip sync"
  exit 0
fi

if ! mise ls python --installed 2>/dev/null | grep -q .; then
  echo >&2 "WARNING: No mise-managed Python found; skipping pip sync"
  exit 0
fi

userName="$(whoami)"
hostName="$(hostname)"
bakSuffix="${userName}.${hostName}"
bakDir="${CHEZMOI_WORKING_TREE}/.backups"
bakFile="${bakDir}/pip-freeze.${bakSuffix}"
reqFile="${HOME}/.default-python-packages"

mkdir -p "${bakDir}"

_commit_backup() {
  local clarifier="${1:?required}"
  local action="${2:?required}"

  local -x GIT_DIR="${CHEZMOI_WORKING_TREE}/.git"
  local -x GIT_WORK_TREE="${CHEZMOI_WORKING_TREE}"

  git add "${bakFile}"
  if ! git diff --cached --quiet -- "${bakDir}"; then
    git commit --no-verify --message "chore(backups): Freeze pip packages ${clarifier} ${action} for ${userName} on ${hostName}" -- "${bakDir}"
  fi
}

backup() {
  local clarifier="${1:?required}"
  local action="${2:?required}"

  mise exec python -- uv pip freeze --system >"${bakFile}"

  _commit_backup "${clarifier}" "${action}"
}

backup before install
mise ls python --installed | awk '{print $2}' | while read -r ver; do
  echo >&2 "INFO: Installing pip packages for python@${ver}"
  mise exec "python@${ver}" -- uv pip install --system --requirement="${reqFile}" --upgrade
done
backup after install

echo >&2 "INFO: Ending $0"
