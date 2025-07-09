"""
References:
    https://pubs.opengroup.org/onlinepubs/9699919799//utilities/V3_chap02.html#tag_18_09
"""
from _utils import rc


@rc(interactive=True)
def __rc_interactive_ls(xsh):
    # https://xon.sh/xonshrc.html#get-better-colors-from-the-ls-command
    # $LS_COLORS='rs=0:di=01;36:ln=01;36:mh=00:pi=40;33:so=01;35:do=01;35:bd=40;33;01:cd=40;33;01:or=40;31;01:su=37;41:sg=30;43:ca=30;41:tw=30;42:ow=34;42:st=37;44:ex=01;32:'

    if $(command -v gls):
        xsh.aliases["ls"] = ["gls", "--color=auto"]
    elif $(ls --color):
        xsh.aliases["ls"] = ["gls", "--color=auto"]
    else:
        xsh.aliases["ls"] = ["ls", "-A"]

    xsh.aliases["l"] = ["ls", "-CFAL"]
    xsh.aliases["l1"] = ["ls", "-A1"]
    xsh.aliases["la"] = ["ls", "-A"]
    xsh.aliases["la1"] = ["l1"]
    xsh.aliases["ll"] = ["ls", "-alFh"]


@rc(interactive=True)
def __rc_interactive_touch(xsh):
    def _touch_with_parents(args):
        for file in map(Path, args):
            file.parent.mkdir(parents=True, exist_ok=True)
            file.touch(exist_ok=True)

    xsh.aliases["tp"] = _touch_with_parents
