#!/usr/bin/env bash
# Ensure the machine has a per-host SSH keypair at ~/.ssh/id_ed25519{,.pub}.
#
# WHY A SCRIPT, AND WHY THE KEYS ARE chezmoi-IGNORED (NOT A modify_)
#   A per-host *generated* key has no declarative source: there is nothing for
#   chezmoi to diff against or restore from. The previous `modify_` faked
#   ownership by emitting `output == current file` and inferring "generate a new
#   key" from EMPTY STDIN. chezmoi can feed a modify_ script empty stdin even when
#   the key is intact (disk-full/ENOSPC or any transient read failure) — on
#   2026-06-26 that destroyed the keypair's integrity (regenerated key, clobbered
#   .pub) while the real key sat untouched. The honest model is: generate once,
#   never touch an existing key, and keep the keys out of chezmoi's managed set
#   (see .chezmoiignore.tmpl). The .pub is always DERIVED from the private key so
#   the two halves can never drift.
#
#   run_before_ so the keypair exists before the run_onchange_after_ GitHub
#   registration scripts read it.
set -euo pipefail

echo >&2 "INFO: Starting $0"

key="${HOME}/.ssh/id_ed25519"
pub="${key}.pub"

mkdir -p "${HOME}/.ssh"
chmod 700 "${HOME}/.ssh"

# Generate ONLY when the private key is genuinely absent/empty on disk — decide
# on the real file, never on an external signal. Existing keys are never touched.
if [[ ! -s "${key}" ]]; then
  echo >&2 "INFO: no SSH key at ${key}; generating a fresh ed25519 keypair."
  ssh-keygen -t ed25519 -C "$(uname -s):$(whoami)@$(hostname)" -N "" -f "${key}" -q
fi
chmod 600 "${key}"

# Keep .pub in sync with the private key, atomically (temp + mv); rewrite only on
# drift, with a deterministic comment so re-runs are no-ops.
want="$(ssh-keygen -y -f "${key}") $(uname -s):$(whoami)@$(hostname)"
if [[ "$(cat "${pub}" 2>/dev/null || true)" != "${want}" ]]; then
  echo >&2 "INFO: (re)deriving ${pub} from the private key."
  tmp="$(mktemp "${HOME}/.ssh/.id_ed25519.pub.XXXXXX")"
  trap 'rm -f "${tmp}"' EXIT
  printf '%s\n' "${want}" >"${tmp}"
  mv -f "${tmp}" "${pub}"
fi
chmod 644 "${pub}"

echo >&2 "INFO: Ending $0"
