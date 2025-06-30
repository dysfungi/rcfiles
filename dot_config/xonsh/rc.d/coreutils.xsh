"""
References:
    https://pubs.opengroup.org/onlinepubs/9699919799//utilities/V3_chap02.html#tag_18_09
"""
from xonsh.built_ins import XSH


######
# LS #
######

if $(command -v gls):
    XSH.aliases["ls"] = ["gls", "--color=auto"]
elif $(ls --color):
    XSH.aliases["ls"] = ["gls", "--color=auto"]
else:
    XSH.aliases["ls"] = ["ls", "-A"]

XSH.aliases["l"] = ["ls", "-CFAL"]
XSH.aliases["la"] = ["ls", "-A"]
XSH.aliases["ll"] = ["ls", "-alFh"]
