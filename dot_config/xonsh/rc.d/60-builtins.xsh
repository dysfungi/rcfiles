"""
References:
    https://pubs.opengroup.org/onlinepubs/9699919799//utilities/V3_chap02.html#tag_18_09
"""
from pathlib import Path
from xonsh.built_ins import XSH


######
# CD #
######

XSH.aliases["cv"] = 'cdargs @($args) && cd $(cat "$HOME/.cdargsresult")'

XSH.aliases["-"] = "cd -"
XSH.aliases["cd-"] = "cd -"


# https://github.com/anki-code/xontrib-rc-awesome/blob/main/xontrib/rc_awesome.xsh#L126
@aliases.register(".")
@aliases.register("cd.")
@aliases.register("..")
@aliases.register("cd..")
@aliases.register("...")  # TODO: fix to override Ellipsis
@aliases.register("cd...")
@aliases.register("....")
@aliases.register("cd....")
def _alias_cd_dots(*args, **kwargs):
    cd @("../" * len($__ALIAS_NAME.lstrip("cd")))


#######
# PWD #
#######

XSH.aliases["cwd"] = Path.cwd
XSH.aliases["wd"] = lambda: Path.cwd().stem
