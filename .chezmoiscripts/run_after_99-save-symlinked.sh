#!/usr/bin/env bash
set -euo pipefail

echo >&2 "INFO: Starting $0"

symlinkedDir="${CHEZMOI_SOURCE_DIR}/.symlinked"
export GIT_DIR="${CHEZMOI_SOURCE_DIR}/.git"
export GIT_WORK_TREE="${CHEZMOI_WORKING_TREE}"

git add "${symlinkedDir}"
if [ -n "$(git status --porcelain -- "${symlinkedDir}")" ]; then
  git commit --message "chore(backup): Save updates made to externally managed, symlinked files" -- "${symlinkedDir}"
fi

echo >&2 "INFO: Ending $0"
