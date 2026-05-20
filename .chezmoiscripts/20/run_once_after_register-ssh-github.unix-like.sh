#!/usr/bin/env bash
# Register the machine's SSH public key with GitHub and switch the chezmoi
# source remote from HTTPS to SSH. Runs once per machine after files are applied
# (so ~/.ssh/id_ed25519.pub is guaranteed to exist from the modify_ script).
set -euo pipefail

echo >&2 "INFO: Starting $0"

PUB_KEY="${HOME}/.ssh/id_ed25519.pub"
KEY_BODY="$(awk '{print $2}' "${PUB_KEY}")"
KEY_TITLE="$(uname -s):$(whoami)@$(hostname)"

if GH_TOKEN="${MISE_GITHUB_TOKEN}" gh ssh-key list | grep -qF "${KEY_BODY}"; then
  echo >&2 "INFO: SSH public key already registered on GitHub; skipping."
else
  EXISTING_ID="$(GH_TOKEN="${MISE_GITHUB_TOKEN}" gh api /user/keys \
    --jq ".[] | select(.title == \"${KEY_TITLE}\") | .id")"
  if [ -n "${EXISTING_ID}" ]; then
    GH_TOKEN="${MISE_GITHUB_TOKEN}" gh ssh-key delete "${EXISTING_ID}" --yes
    echo >&2 "INFO: Deleted stale SSH key '${KEY_TITLE}' (id: ${EXISTING_ID})."
  fi
  GH_TOKEN="${MISE_GITHUB_TOKEN}" gh ssh-key add "${PUB_KEY}" \
    --title "${KEY_TITLE}" --type authentication
  echo >&2 "INFO: SSH public key added to GitHub as '${KEY_TITLE}'."
fi

git -C "${HOME}/.local/share/chezmoi" remote set-url origin \
  git@github.com:dysfungi/rcfiles.git
echo >&2 "INFO: chezmoi remote set to SSH."

echo >&2 "INFO: Ending $0"
