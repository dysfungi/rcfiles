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
  brew bundle dump --file="${bakFile}"

  _commit_backup "${clarifier}"
}

mkdir -p "${bakDir}"

backup before

# Trust non-official taps before bundle install. Homebrew 5.2/6.0 will require
# explicit trust before loading formulae/casks from non-official taps; trusting
# here is a harmless no-op on 5.1.x and future-proofs the sync. Derived from
# the Brewfile so packages.yaml remains the single source of truth — no second
# hardcoded list that can drift.
# `brew trust --tap` (not bare `brew trust`) is required for 2-part user/repo
# tap names; bare positional targets expect 3-part user/repo/formula notation.
while IFS= read -r tap; do
  [ -n "${tap}" ] && brew trust --tap "${tap}"
done < <(grep -E '^tap ' "${brewFile}" | sed -E 's/^tap "([^"]+)".*/\1/' | grep -v '^homebrew/' || true)

# HOMEBREW_BUNDLE_FORCE_INSTALL_CLEANUP: replaces the deprecated --cleanup flag.
# The flag was removed in Homebrew 5.x; the env var activates non-interactive
# cleanup (equivalent to the old --cleanup --force) across all supported versions.
HOMEBREW_BUNDLE_FORCE_INSTALL_CLEANUP=1 brew bundle install --file="${brewFile}" --upgrade
backup after

echo >&2 "INFO: Ending $0"
