from _utils import rc


@rc(interactive=True)
def __rc_interactive(xsh):
    xsh.aliases["chez"] = "chezmoi"
    xsh.aliases["chezad"] = "chezmoi add"
    xsh.aliases["chezap"] = "chezmoi apply"
    xsh.aliases["chezd"] = "chezmoi diff"
