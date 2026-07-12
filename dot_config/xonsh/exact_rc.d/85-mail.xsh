"""Generic mail-spool notices for interactive xonsh shells.

xonsh has no built-in mail check (zsh gets one for free once MAIL is set —
see .zsh/mail/), so this module supplies the two standard notices on every
platform now that managed tmux and WezTerm launch configured shells directly:

  1. Startup notice ("You have mail.") for a populated spool.
  2. Throttled pre-prompt check ("You have new mail.") for mail that arrives
     while a pane remains open.
"""

from time import monotonic as _mail_clock

from _utils import rc


@rc(interactive=True)
def __rc_mail(xsh):
    import os
    import sys

    xsh.env.setdefault("MAIL", "/var/mail/" + xsh.env.get("USER", ""))
    spool = str(xsh.env.get("MAIL"))

    # (1) Startup notice. "Unreadable" means getsize cannot read metadata;
    # a mode-000 spool that remains stat-able is still a populated spool.
    spool_missing = False
    try:
        if os.path.getsize(spool) > 0:
            print("You have mail.", file=sys.stderr)
    except FileNotFoundError:
        spool_missing = True
    except OSError:
        pass  # Metadata unreadable — remain silent rather than guess.

    # (2) Pre-prompt check, at most once per 60s (zsh MAILCHECK parity).
    # Announce only on spool GROWTH since the last check: size increase, or
    # mtime advance at non-shrinking size. A shrink deliberately rebaselines:
    # between polls it is indistinguishable from user-driven read/compaction,
    # so treating it as mail would create a false notice. Baseline is taken at
    # the first prompt so pre-existing mail is never re-announced — that is the
    # startup notice's job. An observed missing spool is different: its later
    # creation is a delivery event, so it announces new mail when non-empty.
    state = {
        "last_check": 0.0,
        "spool_missing": spool_missing,
        "stat": None,
    }

    @events.on_pre_prompt
    def _mail_check_hook(**kwargs):
        now = _mail_clock()
        if now - state["last_check"] < 60.0:
            return
        state["last_check"] = now
        try:
            st = os.stat(spool)
        except FileNotFoundError:
            state["spool_missing"] = True
            state["stat"] = None
            return
        except OSError:
            state["spool_missing"] = False
            state["stat"] = None  # Metadata unreadable — do not infer mail.
            return
        prev, cur = state["stat"], (st.st_mtime, st.st_size)
        was_missing = state["spool_missing"]
        state["spool_missing"] = False
        state["stat"] = cur
        if prev is None:
            if was_missing and st.st_size > 0:
                print("You have new mail.", file=sys.stderr)
            return
        if cur == prev or st.st_size == 0:
            return
        if st.st_size > prev[1] or (st.st_mtime > prev[0] and st.st_size >= prev[1]):
            print("You have new mail.", file=sys.stderr)
