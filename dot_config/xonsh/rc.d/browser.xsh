import webbrowser
from xonsh.built_ins import XSH


# https://xon.sh/tutorial.html#callable-aliases
XSH.aliases["web"] = lambda args: webbrowser.open(*args)
XSH.aliases["webn"] = lambda args: webbrowser.open_new(*args)
XSH.aliases["webw"] = "webn"
XSH.aliases["webt"] = lambda args: webbrowser.open_new_tab(*args)
