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
# Behaviour:
#   - Reads ~/.ssh/id_ed25519.pub (guaranteed present when a run_once_after_ script runs,
#     because the modify_private_id_ed25519 file sync runs in Phase 2 before scripts).
#   - Idempotent: skips if the key body is already registered on the target host.
#   - Stale-key cleanup: if a key with the same machine title but a different body is
#     registered, it is deleted before re-adding (handles key rotation).
#   - Title format: "$(uname -s):$(whoami)@$(hostname)" — matches the comment burned into
#     the key by ssh-keygen and is human-readable in the GitHub web UI.
register_ssh_key() {
  local host="$1"
  local token="$2"

  local pub_key="${HOME}/.ssh/id_ed25519.pub"
  local key_body
  key_body="$(awk '{print $2}' "${pub_key}")"
  local key_title
  key_title="$(uname -s):$(whoami)@$(hostname)"

  # Build the minimal env needed to authenticate gh against the target host.
  # GH_TOKEN targets github.com / ghe.com cloud; GH_ENTERPRISE_TOKEN + GH_HOST
  # targets a self-hosted GitHub Enterprise Server instance.
  local -a gh_env
  if [[ -n "${host}" ]]; then
    gh_env=(GH_HOST="${host}" GH_ENTERPRISE_TOKEN="${token}")
  else
    host="github.com"
    gh_env=(GH_TOKEN="${token}")
  fi

  if env "${gh_env[@]}" gh ssh-key list | grep -qF "${key_body}"; then
    echo >&2 "INFO: SSH public key already registered on ${host}; skipping."
    return
  fi

  local existing_id
  existing_id="$(env "${gh_env[@]}" gh api /user/keys \
    --jq ".[] | select(.title == \"${key_title}\") | .id")"
  if [[ -n "${existing_id}" ]]; then
    env "${gh_env[@]}" gh ssh-key delete "${existing_id}" --yes
    echo >&2 "INFO: Deleted stale SSH key '${key_title}' (id: ${existing_id}) from ${host}."
  fi

  env "${gh_env[@]}" gh ssh-key add "${pub_key}" \
    --title "${key_title}" --type authentication
  echo >&2 "INFO: SSH public key added to ${host} as '${key_title}'."
}
