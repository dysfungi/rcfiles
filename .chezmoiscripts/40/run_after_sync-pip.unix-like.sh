#!/usr/bin/env bash
set -euo pipefail

echo >&2 "INFO: Starting $0"

if ! command -v mise >/dev/null; then
  echo >&2 "WARNING: mise not found; skipping pip sync"
  exit 0
fi

MISE_PYTHON_DIR="$(mise where python 2>/dev/null || true)"
if [ -z "$MISE_PYTHON_DIR" ] || [ ! -f "${MISE_PYTHON_DIR}/bin/python" ]; then
  echo >&2 "WARNING: mise-managed Python not found; skipping pip sync"
  exit 0
fi

MISE_PYTHON="${MISE_PYTHON_DIR}/bin/python"

userName="$(whoami)"
hostName="$(hostname)"
bakSuffix="${userName}.${hostName}"
bakDir="${CHEZMOI_SOURCE_DIR}/.backups"
bakFile="${bakDir}/pip-freeze.${bakSuffix}"
reqFile="${HOME}/.default-python-packages"
export GIT_DIR="${CHEZMOI_SOURCE_DIR}/.git"
export GIT_WORK_TREE="${CHEZMOI_WORKING_TREE}"

backup() {
  local clarifier="${1:?required}"
  local action="${2:?required}"

  UV_PYTHON="${MISE_PYTHON}" uv pip freeze >"${bakFile}"
  git add "${bakFile}"
  if ! git diff --cached --quiet -- "${bakDir}"; then
    git commit --message "chore(backups): Freeze pip packages ${clarifier} ${action} for ${userName} on ${hostName}" -- "${bakDir}"
  fi
}

mkdir -p "${bakDir}"

backup before install
UV_PYTHON="${MISE_PYTHON}" uv pip install --requirement="${reqFile}" --upgrade
backup after install

echo >&2 "INFO: Ending $0"
