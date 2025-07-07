#!/usr/bin/env bash
set -euo pipefail

if [[ "$0" != *"${ONLY_SCRIPTS:-}"* ]]; then
  echo >&2 "INFO: Only running scripts with '${ONLY_SCRIPTS}'; Skipping $0"
  exit 0
else
  echo >&2 "INFO: Starting $0"
fi

scriptName="$(basename $0)"
outFile="$(mktemp -t "${scriptName}.out")"
echo >&2 "INFO: Stdout file for ${scriptName} - ${outFile}"

# https://lazy.folke.io/usage
nvim --headless "+MasonUpdate" "+MasonToolsInstallSync" "+MasonToolsUpdateSync" "+Lazy! sync" "+qa" >> "${outFile}"

echo >&2 "INFO: Ending $0"
echo >&2
