#!/usr/bin/env bash
# Configure postfix as a local-only MTA so cronie can deliver cron job output —
# chezmoi-update-cron's drift/failure nag — to /var/mail/$USER.
#
# Design:
#   Without an MTA, cronie logs "No MTA installed, discarding output" and the
#   nag never reaches the mail spool. Postfix restricted to loopback accepts
#   cron's bare-username submission, resolves it via $myorigin=$myhostname to
#   <user>@localhost, matches $mydestination, and delivers 0600 to
#   /var/mail/<user> (/var/mail -> /var/spool/mail symlink on Arch) — the same
#   MTA and spool behavior macOS ships built in. Recipe container-verified
#   end-to-end on an ephemeral Arch image.
#
#   Trigger: run_after_ deliberately, NOT run_onchange_. chezmoi-sudo exits 0
#   with a WARN when it has no TTY and no cached credentials (by design, so
#   unattended runs don't block) — under run_onchange_ that silent skip would
#   be recorded as "done" and postfix would never actually be enabled.
#   run_after_ re-checks every apply and self-heals on the next interactive
#   one (same rationale as the cronie installer in this stage). The
#   steady-state cost is the two-check idempotence guard below.

set -euo pipefail

echo >&2 "INFO: Starting $0"

# Defensive: postfix is installed by the stage-10 pacman sync, which runs before
# this stage-90 script — but if it is absent (fresh machine with a failed or
# skipped sync), warn and let a later apply retry rather than failing this one.
if ! command -v postconf >/dev/null 2>&1 || ! command -v systemctl >/dev/null 2>&1; then
  echo >&2 "WARN: postconf or systemctl not found — postfix not installed yet?"
  echo >&2 "WARN: Skipping postfix setup; it will be retried on the next chezmoi apply."
  echo >&2 "INFO: Ending $0"
  exit 0
fi

# Idempotence guard: already configured for loopback-only delivery and enabled
# in systemd — nothing to do.
if [ "$(postconf -h inet_interfaces)" = "loopback-only" ] && systemctl is-enabled postfix >/dev/null 2>&1; then
  echo >&2 "INFO: postfix already configured (loopback-only) and enabled."
  echo >&2 "INFO: Ending $0"
  exit 0
fi

# Local-only delivery: listen on loopback only; all mail resolves to
# <user>@localhost and lands in the local spool. postconf -e writes
# /etc/postfix/main.cf (root-owned), hence chezmoi-sudo.
echo >&2 "INFO: Configuring postfix for local-only delivery..."
chezmoi-sudo postconf -e "myhostname = localhost" "mydestination = localhost" "inet_interfaces = loopback-only"
chezmoi-sudo newaliases

# If postfix is already running with the old config, restart it: inet_interfaces
# changes require a full stop/start (`postfix reload` is not sufficient per the
# postfix docs). Without this, the config would be "healed" on disk while the
# running daemon kept the stale settings.
if systemctl is-active postfix >/dev/null 2>&1; then
  echo >&2 "INFO: Restarting running postfix to pick up the new config..."
  chezmoi-sudo systemctl restart postfix
fi

# WSL note (pattern copied from the cronie installer): `systemctl enable --now
# postfix` may print "Cannot start unit with --now when systemd is not running"
# if WSL2 launched without systemd (/etc/wsl.conf [boot] systemd=true not yet in
# effect). `enable` still creates the symlink, so postfix starts automatically
# on the next WSL boot. Exit code remains 0 in this case — it is not an error.
if systemctl is-enabled postfix >/dev/null 2>&1; then
  if systemctl is-active postfix >/dev/null 2>&1; then
    echo >&2 "INFO: postfix is enabled and running."
  else
    echo >&2 "INFO: postfix is enabled but not yet running (will start on next WSL boot)."
    echo >&2 "INFO: Run 'wsl --shutdown' from Windows then restart WSL to activate it."
  fi
else
  echo >&2 "INFO: Enabling postfix via systemd..."
  # chezmoi-sudo: use our resilient wrapper so this doesn't block unattended runs.
  # (First chezmoi apply is interactive, so the TTY branch fires; subsequent runs
  #  use the cached-creds or askpass branch.)
  chezmoi-sudo systemctl enable --now postfix
  # chezmoi-sudo exits 0 even when it has no credentials or TTY — the post-
  # condition is the only reliable signal (same rationale as the cronie
  # installer's macOS branch). Don't claim success without verifying.
  if ! systemctl is-enabled postfix >/dev/null 2>&1; then
    echo >&2 "WARN: postfix is still not enabled — chezmoi-sudo likely skipped (unattended)."
    echo >&2 "WARN: It will self-heal on the next interactive chezmoi apply."
  elif systemctl is-active postfix >/dev/null 2>&1; then
    echo >&2 "INFO: postfix enabled and running."
  else
    echo >&2 "INFO: postfix enabled (symlink created). Not yet running — systemd may not be"
    echo >&2 "INFO: active in this WSL session. Run 'wsl --shutdown' from Windows then"
    echo >&2 "INFO: restart WSL to start postfix and activate cron-mail delivery."
  fi
fi

echo >&2 "INFO: Ending $0"
