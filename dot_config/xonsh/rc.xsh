"""

References:
    [xonsh RC Files](https://xon.sh/xonshrc.html)
    [$XONSH_INTERACTIVE](https://xon.sh/envvars.html#xonsh-interactive)
    [$XONSH_LOGIN](https://xon.sh/envvars.html#xonsh-login)
"""

from pathlib import Path
from xonsh.built_ins import XSH

#########
# xonsh #
#########

# [xonsh Env Vars](https://xon.sh/envvars.html)
$COMPLETIONS_CONFIRM = True
$XONSH_AUTOPAIR = True
$XONSH_CACHE_SCRIPTS = 0
$XONSH_CACHE_EVERYTHING = 0
# $XONSH_DEBUG = 1
$XONSH_HISTORY_MATCH_ANYWHERE = True
$XONSH_SHOW_TRACEBACK = 0
# $XONSH_TRACE_SUBPROC = 2
$XONSH_STORE_STDOUT = True

#########
# $PATH #
#########

USR_LOCAL_BIN = p"/usr/local/bin"
if USR_LOCAL_BIN.exists() and str(USR_LOCAL_BIN) not in $PATH:
    $PATH.insert(0, str(USR_LOCAL_BIN))

#######
# Env #
#######

XSH.env.setdefault("EDITOR", "nvim -e")
XSH.env.setdefault("VISUAL", "nvim")

############
# Homebrew #
############

xontrib load homebrew  # https://github.com/eugenesvk/xontrib-homebrew

# Python 3.12+ RuntimeError: Unsupported fstring syntax
# https://github.com/xonsh/xonsh/issues/5166
HOMEBREW_PREFIX = Path($(brew --prefix)) if $(command -v brew) else p'/opt/homebrew'
HOMEBREW_BIN = HOMEBREW_PREFIX / 'bin'
if HOMEBREW_BIN.exists() and str(HOMEBREW_BIN) not in $PATH:
    $PATH.insert(0, str(HOMEBREW_BIN))
