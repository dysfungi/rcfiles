#!/usr/bin/env bash
set -euo pipefail

echo >&2 "INFO: Starting $0"

export PATH="${HOME}/.local/bin:${PATH}"

if ! command -v mise >/dev/null 2>&1; then
  echo >&2 "WARN: mise not found; skipping. Re-run 'chezmoi apply' after mise is installed."
  echo >&2 "INFO: Ending $0"
  exit 0
fi

userName="$(whoami)"
hostName="$(hostname)"
bakSuffix="${userName}.${hostName}"
bakDir="${CHEZMOI_SOURCE_DIR}/.backups"
bakFile="${bakDir}/mise-ls.${bakSuffix}"

_commit_backup() {
  local clarifier="${1:?required}"
  local action="${2:?required}"

  local -x GIT_DIR="${CHEZMOI_SOURCE_DIR}/.git"
  local -x GIT_WORK_TREE="${CHEZMOI_WORKING_TREE}"

  git add "${bakFile}"
  if ! git diff --cached --quiet -- "${bakDir}"; then
    git commit --no-verify --message "chore(backups): List mise tools ${clarifier} ${action} for ${userName} on ${hostName}" -- "${bakDir}"
  fi
}

backup() {
  local clarifier="${1:?required}"
  local action="${2:?required}"

  mise ls >"${bakFile}"

  _commit_backup "${clarifier}" "${action}"
}

mkdir -p "${bakDir}"

backup before install
mise install --yes
backup after install

backup before upgrade
mise upgrade --yes
backup after upgrade

# Run upstream `scripts.postinstall` for npm wrapper-binary packages that
# mise's npm backend skipped (npm lifecycle scripts are not executed). The
# K-δ heuristic narrows to the wrapper-binary pattern: postinstall declared
# AND optionalDependencies has a per-platform native key AND the bin file is
# still a small stub (< 4 KB). Then verify the materialized bin is > 4 KB
# AND executable, else fail loudly. See
# .tests/chezmoiscripts/test_run_after_sync_mise.py for the executable spec.
# Confirmed failure pattern: @anthropic-ai/claude-code (2.1.x).
_materialize_npm_wrappers() {
  if ! command -v jq >/dev/null || ! command -v node >/dev/null; then
    echo >&2 "WARN: jq or node missing; skipping npm postinstall scan"
    return 0
  fi
  local suffix
  case "$(uname -s)/$(uname -m)" in
  Darwin/arm64) suffix=darwin-arm64 ;;
  Darwin/x86_64) suffix=darwin-x64 ;;
  Linux/aarch64 | Linux/arm64) suffix=linux-arm64 ;;
  Linux/x86_64 | Linux/amd64) suffix=linux-x64 ;;
  *)
    echo >&2 "WARN: unrecognized host $(uname -sm); skipping scan"
    return 0
    ;;
  esac
  # Note: Alpine/musl is untested — install.cjs's per-platform optional dep
  # would be `-linux-x64-musl`; add a musl branch above if needed.

  shopt -s nullglob
  local pkgDir match binPath postinstall optDep pkgName size
  for pkgDir in \
    "${HOME}"/.local/share/mise/installs/npm-*/*/lib/node_modules/*/ \
    "${HOME}"/.local/share/mise/installs/npm-*/*/lib/node_modules/@*/*/; do
    # Skip if no package.json (the glob may match non-package dirs like
    # @anthropic-ai/ that contain a scope, not a package).
    [[ -f "${pkgDir}package.json" ]] || continue
    # Single jq emits "<bin>|<postinstall>|<optDep>" iff all three predicates
    # pass (H4 postinstall set, H5 per-host optDep, H1 bin is < 4 KB stub).
    # `endswith` catches both `<pkg>-darwin-arm64` and `@scope/<pkg>-darwin-arm64`.
    # `|| true` absorbs jq's non-zero exit on parse errors so `set -e` in the
    # parent script does not abort the loop.
    match="$(jq -r --arg s "-${suffix}" --arg dir "${pkgDir}" '
      (.scripts.postinstall // "") as $p
      | ([.optionalDependencies // {} | keys[]? | select(endswith($s))] | first // "") as $o
      | ((.bin // null) | if type=="string" then . elif type=="object" then to_entries[0].value else "" end) as $b
      | ($dir + $b) as $bp
      | select($p != "" and $o != "" and $b != "")
      | "\($bp)|\($p)|\($o)"
    ' "${pkgDir}package.json" 2>/dev/null || true)"
    [[ -n "${match}" ]] || continue
    IFS='|' read -r binPath postinstall optDep <<<"${match}"
    [[ -f "${binPath}" ]] || continue
    size="$(stat -f%z "${binPath}" 2>/dev/null || stat -c%s "${binPath}")"
    ((size < 4096)) || continue

    pkgName="$(jq -r '.name' "${pkgDir}package.json" 2>/dev/null || echo "<unknown>")"
    echo >&2 "INFO: npm postinstall: ${pkgName} (bin=${size}B, optDep=${optDep})"
    (cd "${pkgDir}" && eval "${postinstall}")

    size="$(stat -f%z "${binPath}" 2>/dev/null || stat -c%s "${binPath}")"
    if ((size < 4096)) || [[ ! -x "${binPath}" ]]; then
      echo >&2 "ERROR: ${pkgName} postinstall left ${binPath} unmaterialized (size=${size}B)"
      return 1
    fi
    echo >&2 "INFO: npm postinstall OK: ${pkgName} (bin=${size}B)"
  done
  shopt -u nullglob
}

_materialize_npm_wrappers

echo >&2 "INFO: Ending $0"
