# shellcheck shell=bash
# Shared bash helper: register_ssh_key <host> <token>
#
# Included verbatim via `includeTemplate "github/register-ssh-key.sh"` into
# each caller .tmpl — no template directives here, pure bash.
#
# Arguments:
#   host  - GitHub hostname. Empty string → github.com (uses GH_TOKEN).
#           Non-empty → GitHub Enterprise Server (uses GH_HOST + GH_ENTERPRISE_TOKEN).
#   token - PAT with admin:public_key or write:public_key scope.
#
# Behaviour & WHY:
#   - Derives the public key from the PRIVATE key (`ssh-keygen -y`), not from
#     id_ed25519.pub. The private key is the source of truth, so we can never
#     upload an orphan public key whose private half is missing/unusable — the
#     exact failure behind the 2026-06-26 github.com lockout.
#   - ADD-ONLY: never deletes existing keys. The previous version deleted any
#     same-title key before adding the new one; a failed/return-less add then left
#     the account with NO usable key. Stale per-host entries are pruned manually.
#   - Idempotent: skips if the key body is already registered on the target host.
#   - Best-effort: missing key / no network / bad token warn loudly and return 0
#     rather than aborting the whole `chezmoi apply`.
#   - Title format: "$(uname -s):$(whoami)@$(hostname)" — matches the comment
#     burned into the key and is human-readable in the GitHub web UI.
register_ssh_key() {
  local host="$1"
  local token="$2"
  local label="${host:-github.com}"

  local key="${HOME}/.ssh/id_ed25519"
  if [[ ! -s "${key}" ]]; then
    echo >&2 "WARN: ${key} missing; cannot register SSH key on ${label}."
    return 0
  fi

  # Source of truth: derive the public half from the private key.
  local pub_line key_body
  if ! pub_line="$(ssh-keygen -y -f "${key}" 2>/dev/null)"; then
    echo >&2 "WARN: ${key} is not a usable private key; skipping ${label} registration."
    return 0
  fi
  key_body="$(printf '%s' "${pub_line}" | awk '{print $2}')"
  local key_title
  key_title="$(uname -s):$(whoami)@$(hostname)"

  # Build the minimal env needed to authenticate gh against the target host.
  # GH_TOKEN targets github.com; GH_ENTERPRISE_TOKEN + GH_HOST targets a
  # self-hosted GitHub Enterprise Server instance.
  local -a gh_env
  if [[ -n "${host}" ]]; then
    gh_env=(GH_HOST="${host}" GH_ENTERPRISE_TOKEN="${token}")
  else
    gh_env=(GH_TOKEN="${token}")
  fi

  local listed
  if ! listed="$(env "${gh_env[@]}" gh ssh-key list 2>/dev/null)"; then
    echo >&2 "WARN: cannot reach ${label} (network/token); skipping SSH key registration."
    return 0
  fi
  if grep -qF "${key_body}" <<<"${listed}"; then
    echo >&2 "INFO: SSH public key already registered on ${label}; skipping."
    return 0
  fi

  if env "${gh_env[@]}" gh ssh-key add "${key}.pub" \
    --title "${key_title}" --type authentication 2>/dev/null; then
    echo >&2 "INFO: SSH public key added to ${label} as '${key_title}'."
  else
    echo >&2 "WARN: failed to add SSH key to ${label}; existing keys left untouched."
  fi
}
