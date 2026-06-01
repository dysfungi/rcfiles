#!/usr/bin/env bash
set -euo pipefail

echo >&2 "INFO: Starting $0"

if [ "$(uname -s)" != Darwin ]; then
  echo "Not Darwin; Skipping Homebrew install..."
  exit 0
fi

userName="$(whoami)"
hostName="$(hostname)"
bakSuffix="${userName}.${hostName}"
configDir="$HOME/.config/homebrew"
brewFile="${configDir}/Brewfile"
bakDir="${CHEZMOI_SOURCE_DIR}/.backups"
bakFile="${bakDir}/Brewfile.${bakSuffix}"
export HOMEBREW_BUNDLE_FILE="${brewFile}"

_commit_backup() {
  local clarifier="${1:?required}"

  local -x GIT_DIR="${CHEZMOI_SOURCE_DIR}/.git"
  local -x GIT_WORK_TREE="${CHEZMOI_WORKING_TREE}"

  git add "${bakFile}"
  if ! git diff --cached --quiet -- "${bakDir}"; then
    git commit --no-verify --message "chore(backups): Dump Brewfile ${clarifier} install for ${userName} on ${hostName}" -- "${bakDir}"
  fi
}

backup() {
  local clarifier="${1:?required}"

  if [ -e "${bakFile}" ]; then
    rm "${bakFile}"
  fi
  brew bundle dump --describe --file="${bakFile}"

  _commit_backup "${clarifier}"
}

mkdir -p "${bakDir}"

backup before
# HOMEBREW_BUNDLE_FORCE_INSTALL_CLEANUP: on Homebrew HEAD+ --cleanup became
# interactive (needs --force, --force-cleanup, or this env var); on 5.1.x the
# env var is a no-op and --cleanup already acts like cleanup --force. Using the
# env var here avoids depending on --force-cleanup, which doesn't exist in 5.1.x.
HOMEBREW_BUNDLE_FORCE_INSTALL_CLEANUP=1 brew bundle install --cleanup --file="${brewFile}" --upgrade
backup after

echo >&2 "INFO: Ending $0"
