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
XSH.aliases[".."] = "cd .."
XSH.aliases["..."] = "cd ../.." # TODO: fix to override Ellipsis
XSH.aliases["...."] = "cd ../../.."
XSH.aliases["cd."] = "cd .."
XSH.aliases["cd.."] = "cd ../.."
XSH.aliases["cd..."] = "cd ../../.."
XSH.aliases["cd...."] = "cd ../../../.."


#######
# PWD #
#######

XSH.aliases["cwd"] = Path.cwd
XSH.aliases["wd"] = lambda: Path.cwd().stem
