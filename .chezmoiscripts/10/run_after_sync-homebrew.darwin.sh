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
export GIT_DIR="${CHEZMOI_SOURCE_DIR}/.git"
export GIT_WORK_TREE="${CHEZMOI_WORKING_TREE}"
export HOMEBREW_BUNDLE_FILE="${brewFile}"

backup() {
  local clarifier="${1:?required}"

  if [ -e "${bakFile}" ]; then
    rm "${bakFile}"
  fi
  brew bundle dump --describe --file="${bakFile}"
  git add "${bakFile}"
  if [ -n "$(git status --porcelain -- "${bakDir}")" ]; then
    git commit --message "chore(backups): Dump Brewfile ${clarifier} install for ${userName} on ${hostName}" -- "${bakDir}"
  fi
}

mkdir -p "${bakDir}"

backup before
brew bundle install --cleanup --file="${brewFile}" --upgrade
backup after

echo >&2 "INFO: Ending $0"
