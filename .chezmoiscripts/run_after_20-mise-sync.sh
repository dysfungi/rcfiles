#!/usr/bin/env bash
set -euo pipefail

echo >&2 "INFO: Starting $0"

scriptName="$(basename "$0")"
outFile="$(mktemp -t "${scriptName}.out")"
echo >&2 "INFO: Stdout file for ${scriptName} - ${outFile}"

userName="$(whoami)"
hostName="$(hostname)"
bakSuffix="${userName}.${hostName}"
bakDir="${CHEZMOI_SOURCE_DIR}/.backups"
bakFile="${bakDir}/mise-ls.${bakSuffix}"
export GIT_DIR="${CHEZMOI_SOURCE_DIR}/.git"
export GIT_WORK_TREE="${CHEZMOI_WORKING_TREE}"

backup() {
  local clarifier="${1:?required}"
  local action="${2:?required}"

  mise ls >"${bakFile}"
  git add "${bakFile}"
  if [ -n "$(git status --porcelain -- "${bakDir}")" ]; then
    git commit --message "chore(backups): List mise tools ${clarifier} ${action} for ${userName} on ${hostName}" -- "${bakDir}"
  fi
}

mkdir -p "${bakDir}"

{
  backup before install
  mise install --yes
  backup after install

  backup before upgrade
  mise upgrade --yes
  backup after upgrade
} >>"${outFile}"

echo >&2 "INFO: Ending $0"
