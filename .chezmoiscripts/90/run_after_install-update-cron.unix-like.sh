#!/usr/bin/env bash
# Install a daily cron job that runs chezmoi-update-cron.
#
# Design:
#   Uses crontab (same interface on macOS and Linux). On macOS the cron daemon is
#   built-in (managed by launchd); on Arch/WSL it is `cronie` (installed via pacman
#   and enabled by systemd). The cron line and this script are identical across OSes.
#
#   Trigger: run_after_ (not run_onchange_) because the crontab is external mutable
#   state that must be re-asserted on every `chezmoi apply`. run_onchange_ only fires
#   when the rendered script content changes, so any drift (manual crontab edit,
#   silent write failure) would never be self-healed. The script is idempotent (it
#   strips and re-merges the managed block), so running every apply is safe and cheap.
#
#   A marked managed block (>>>/<<< delimiters) is merged idempotently into the
#   existing crontab so that unrelated entries are never clobbered.
#
#   Schedule: daily at 12:<minute> local time. The minute is derived from the
#   hostname checksum so machines don't stampede at :00 (they stagger naturally
#   across a 60-minute window with no coordination needed).
#
#   Hard-fail philosophy: the script exits non-zero whenever it cannot achieve its
#   goal (crontab absent, write did not persist, daemon not loadable). Silent
#   failures here cause the daily chezmoi-update job to silently never run.
#
#   Daemon management (checked after crontab write):
#   - Linux/WSL: systemctl branch — ensures cronie is enabled via systemd.
#   - macOS: launchctl branch — launchd auto-starts com.vix.cron via
#     QueueDirectories on /usr/lib/cron/tabs when the crontab is written. We verify
#     the service is *known to launchd* (not necessarily state=running, since it is
#     on-demand) and kickstart it if needed. We re-verify after kickstart because
#     chezmoi-sudo exits 0 even when it has no credentials or TTY — the post-
#     condition is the only reliable signal.
#   - Neither: hard failure.
#
#   macOS caveat: cron requires Full Disk Access once (System Settings → Privacy &
#   Security → Full Disk Access → add /usr/sbin/cron and your terminal app).
#   Without it, cron jobs that touch protected paths silently fail. This cannot be
#   detected or remediated programmatically; a WARNING is always emitted on macOS.

set -euo pipefail

echo >&2 "INFO: Starting $0"

if ! command -v crontab >/dev/null 2>&1; then
  echo >&2 "ERROR: crontab not found — cannot install daily chezmoi-update cron job."
  echo >&2 "ERROR: Install a cron implementation (e.g. cronie on Arch) and re-run chezmoi apply."
  exit 1
fi

# ── derive a per-host minute offset to stagger across machines ───────────────
# cksum outputs "<checksum> <byte-count> <filename>"; we take the first field.
HOSTNAME_SUM=$(hostname | cksum | awk '{print $1}')
CRON_MINUTE=$((HOSTNAME_SUM % 60))
CRON_LINE="${CRON_MINUTE} 12 * * * ${HOME}/.local/bin/chezmoi-update-cron"

BLOCK_BEGIN="# >>> chezmoi-update >>>"
BLOCK_END="# <<< chezmoi-update <<<"

MANAGED_BLOCK="${BLOCK_BEGIN}
# Installed by chezmoi. Do not edit this block manually — it is regenerated on
# chezmoi apply. To change the schedule, edit the source script:
#   .chezmoiscripts/90/run_after_install-update-cron.unix-like.sh
${CRON_LINE}
${BLOCK_END}"

# ── read current crontab (empty string if none exists yet) ───────────────────
existing_crontab="$(crontab -l 2>/dev/null || true)"

# ── strip the old managed block (idempotent) ─────────────────────────────────
# Use awk to delete lines between the begin and end markers (inclusive).
stripped_crontab="$(printf '%s\n' "${existing_crontab}" | awk "
  /^${BLOCK_BEGIN//\//\\/}\$/ { in_block=1; next }
  /^${BLOCK_END//\//\\/}\$/ { in_block=0; next }
  !in_block { print }
")"

# ── append the new managed block ─────────────────────────────────────────────
# Ensure there's a trailing newline before the block when the crontab is non-empty.
if [ -n "${stripped_crontab}" ]; then
  new_crontab="${stripped_crontab}
${MANAGED_BLOCK}"
else
  new_crontab="${MANAGED_BLOCK}"
fi

printf '%s\n' "${new_crontab}" | crontab -

# ── verify the block actually persisted ──────────────────────────────────────
# On macOS, crontab may silently fail to persist without Full Disk Access (TCC).
# Read it back and confirm the marker is present before reporting success.
if ! crontab -l 2>/dev/null | grep -qF "${BLOCK_BEGIN}"; then
  echo >&2 "ERROR: crontab write did not persist — '${BLOCK_BEGIN}' not found in 'crontab -l'."
  echo >&2 "ERROR: On macOS this is most often a Full Disk Access (TCC) issue."
  echo >&2 "ERROR: Grant Full Disk Access to your terminal app and to /usr/sbin/cron:"
  echo >&2 "ERROR:   System Settings → Privacy & Security → Full Disk Access"
  echo >&2 "ERROR: Then re-run: chezmoi apply --include scripts"
  exit 1
fi
echo >&2 "INFO: Cron job installed: ${CRON_LINE}"

# ── ensure cron daemon is running ────────────────────────────────────────────
if command -v systemctl >/dev/null 2>&1; then
  # ── Linux/WSL: ensure cronie is enabled via systemd ─────────────────────────
  # WSL note: `systemctl enable --now cronie` may print "Cannot start unit with
  # --now when systemd is not running" if WSL2 launched without systemd (i.e.
  # /etc/wsl.conf [boot] systemd=true not yet in effect). `enable` still creates
  # the symlink, so cronie starts automatically on the next WSL boot. Exit code
  # remains 0 in this case — it is not an error.
  if systemctl is-enabled cronie >/dev/null 2>&1; then
    if systemctl is-active cronie >/dev/null 2>&1; then
      echo >&2 "INFO: cronie is enabled and running."
    else
      echo >&2 "INFO: cronie is enabled but not yet running (will start on next WSL boot)."
      echo >&2 "INFO: Run 'wsl --shutdown' from Windows then restart WSL to activate it."
    fi
  else
    echo >&2 "INFO: Enabling cronie via systemd..."
    # chezmoi-sudo: use our resilient wrapper so this doesn't block unattended runs.
    # (First chezmoi apply is interactive, so the TTY branch fires; subsequent runs
    #  use the cached-creds or askpass branch.)
    chezmoi-sudo systemctl enable --now cronie
    if systemctl is-active cronie >/dev/null 2>&1; then
      echo >&2 "INFO: cronie enabled and running."
    else
      echo >&2 "INFO: cronie enabled (symlink created). Not yet running — systemd may not be"
      echo >&2 "INFO: active in this WSL session. Run 'wsl --shutdown' from Windows then"
      echo >&2 "INFO: restart WSL to start cronie and activate the daily update cron job."
    fi
  fi
elif command -v launchctl >/dev/null 2>&1; then
  # ── macOS: verify com.vix.cron is known to launchd ──────────────────────────
  # launchd auto-starts com.vix.cron via QueueDirectories when crontab writes to
  # /usr/lib/cron/tabs/$USER. We verify the service is *known to launchd* — not
  # necessarily state=running (it is on-demand; asserting running would be a flaky
  # false-negative). If not known, kickstart it via chezmoi-sudo.
  #
  # We re-verify after kickstart because chezmoi-sudo exits 0 even with no
  # credentials or TTY (by design, to avoid blocking unattended cron runs).
  # The post-condition is the only reliable signal.
  if ! launchctl print system/com.vix.cron >/dev/null 2>&1; then
    echo >&2 "INFO: com.vix.cron not known to launchd — attempting kickstart..."
    chezmoi-sudo launchctl kickstart -k system/com.vix.cron || true
    if ! launchctl print system/com.vix.cron >/dev/null 2>&1; then
      echo >&2 "ERROR: com.vix.cron is still not loaded in the system domain after kickstart."
      echo >&2 "ERROR: The crontab entry was installed but the daemon may not execute it."
      echo >&2 "ERROR: Try manually:"
      echo >&2 "ERROR:   sudo launchctl kickstart -k system/com.vix.cron"
      echo >&2 "ERROR:   sudo launchctl bootstrap system /System/Library/LaunchDaemons/com.vix.cron.plist"
      exit 1
    fi
    echo >&2 "INFO: com.vix.cron loaded successfully."
  else
    echo >&2 "INFO: com.vix.cron is known to launchd (auto-starts via QueueDirectories)."
  fi
  echo >&2 "WARNING: macOS requires Full Disk Access (TCC) for cron to access protected paths."
  echo >&2 "WARNING: Grant Full Disk Access to your terminal app and to /usr/sbin/cron:"
  echo >&2 "WARNING:   System Settings → Privacy & Security → Full Disk Access"
else
  echo >&2 "ERROR: No daemon manager found (neither systemctl nor launchctl on PATH)."
  echo >&2 "ERROR: Cannot verify the cron daemon is running. Cron job was not activated."
  exit 1
fi

echo >&2 "INFO: Ending $0"
