#!/usr/bin/env bash
set -euo pipefail

echo >&2 "INFO: Starting $0"

scriptName="$(basename "$0")"
outFile="$(mktemp -t "${scriptName}.out")"
echo >&2 "INFO: Stdout file for ${scriptName} - ${outFile}"

# https://lazy.folke.io/usage
nvim --headless "+MasonUpdate" "+MasonToolsInstallSync" "+MasonToolsUpdateSync" "+Lazy! sync" "+qa" >>"${outFile}"

echo >&2 "INFO: Ending $0"
echo >&2
