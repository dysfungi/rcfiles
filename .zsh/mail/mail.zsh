# Startup notice for fresh zsh shells: native MAILCHECK only announces mail
# that arrives AFTER startup, never a pre-existing spool. This covers direct
# WezTerm launch-menu, SSH, and bare `zsh` sessions.
[[ -s $MAIL ]] && print -u2 "You have mail."
