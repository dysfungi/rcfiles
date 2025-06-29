"""
References:
    https://pubs.opengroup.org/onlinepubs/9699919799//utilities/V3_chap02.html#tag_18_09
"""
from xonsh.built_ins import XSH


######
# CD #
######

XSH.aliases["cv"] = 'cdargs @($args) && cd $(cat "$HOME/.cdargsresult")'
