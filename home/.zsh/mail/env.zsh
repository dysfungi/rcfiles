# Enable zsh's NATIVE mail check by setting MAIL (the repo previously set
# neither MAIL nor mailpath, so zsh checked nothing): with MAIL set,
# interactive zsh polls the spool every $MAILCHECK seconds (default 60) and
# announces "You have new mail." for mail arriving WHILE a shell is open —
# e.g. the noon chezmoi-update-cron drift summary. Interactive-only by zsh
# design; no non-interactive noise.
# https://zsh.sourceforge.io/Doc/Release/Parameters.html#index-MAIL
export MAIL="/var/mail/${USER}"
