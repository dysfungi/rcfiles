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
# $MULTILINE_PROMPT = '`·.,¸,.·*¯`·.,¸,.·*¯'
$XONSH_AUTOPAIR = True
$XONSH_HISTORY_MATCH_ANYWHERE = True
$XONSH_SHOW_TRACEBACK = False
$XONSH_STORE_STDOUT = True

#########
# $PATH #
#########

$PATH.prepend(p"/usr/local/bin")

############
# Homebrew #
############

# Python 3.12+ RuntimeError: Unsupported fstring syntax
# https://github.com/xonsh/xonsh/issues/5166
HOMEBREW_PREFIX = Path($(brew --prefix)) if $(command -v brew) else p'/opt/homebrew'
HOMEBREW_BIN = HOMEBREW_PREFIX / 'bin'
if HOMEBREW_BIN.exists() and str(HOMEBREW_BIN) not in $PATH:
    $PATH.prepend(HOMEBREW_BIN)
