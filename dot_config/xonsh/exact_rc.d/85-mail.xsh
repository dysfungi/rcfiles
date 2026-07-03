"""Generic mail-spool notices for xonsh — login(1) parity, nothing chezmoi-specific.

xonsh has no built-in mail check (zsh gets one for free once MAIL is set —
see .zsh/mail/), so this module replicates the two standard notices:

  1. Startup notice ("You have mail.") — NON-DARWIN ONLY: on macOS every new
     tmux pane / Terminal tab is spawned via login(1), which already prints
     it (a second startup check would double-print); Linux has no login(1)
     on that path, so the shell prints it instead.
  2. Throttled pre-prompt check ("You have new mail.") — covers long-lived
     panes where mail (e.g. the noon chezmoi-update-cron drift summary)
     arrives mid-session.
"""

from _utils import rc


@rc(interactive=True)
def __rc_mail(xsh):
    import os
    import sys
    import time

    xsh.env.setdefault("MAIL", "/var/mail/" + xsh.env.get("USER", ""))
    spool = str(xsh.env.get("MAIL"))

    # (1) Startup notice — see module docstring for the platform gate.
    if sys.platform != "darwin":
        try:
            if os.path.getsize(spool) > 0:
                print("You have mail.", file=sys.stderr)
        except OSError:
            pass  # No spool yet (or unreadable) — silence, like login(1).

    # (2) Pre-prompt check, at most once per 60s (zsh MAILCHECK parity).
    # Announce only on spool GROWTH since the last check: size increase, or
    # mtime advance at non-shrinking size (a shrink means the spool was read,
    # not new mail). Baseline is taken at the first prompt so pre-existing
    # mail is never re-announced — that is the startup notice's job.
    state = {"last_check": 0.0, "stat": None}

    @events.on_pre_prompt
    def _mail_check_hook(**kwargs):
        now = time.monotonic()
        if now - state["last_check"] < 60.0:
            return
        state["last_check"] = now
        try:
            st = os.stat(spool)
        except OSError:
            state["stat"] = None  # Spool gone (read+emptied) — rebaseline.
            return
        prev, cur = state["stat"], (st.st_mtime, st.st_size)
        state["stat"] = cur
        if prev is None or cur == prev or st.st_size == 0:
            return
        if st.st_size > prev[1] or (st.st_mtime > prev[0] and st.st_size >= prev[1]):
            print("You have new mail.", file=sys.stderr)
