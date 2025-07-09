from _utils import rc


@rc(interactive=True)
def __rc_interactive(xsh):
    if $(command -v nvim):
        XSH.aliases["vi"] = "nvim"
        XSH.aliases["vim"] = "nvim"
