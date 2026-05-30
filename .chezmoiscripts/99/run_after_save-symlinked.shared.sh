#!/usr/bin/env bash
set -euo pipefail

echo >&2 "INFO: Starting $0"

symlinkedDir="${CHEZMOI_SOURCE_DIR}/.symlinked"
userName="$(whoami)"
hostName="$(hostname)"

save_symlinked_changes() {
  local -x GIT_DIR="${CHEZMOI_SOURCE_DIR}/.git"
  local -x GIT_WORK_TREE="${CHEZMOI_WORKING_TREE}"

  git add "${symlinkedDir}"
  if [ -n "$(git status --porcelain -- "${symlinkedDir}")" ]; then
    git commit --no-verify --message "chore(symlinked): Save updates made to externally managed, symlinked files for ${userName} on ${hostName}" -- "${symlinkedDir}"
  fi
}

save_symlinked_changes

echo >&2 "INFO: Ending $0"
