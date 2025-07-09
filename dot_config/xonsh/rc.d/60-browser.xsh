from _utils import rc


@rc(interactive=True)
def __rc_interactive(xsh):
    import webbrowser

    # https://xon.sh/tutorial.html#callable-aliases
    xsh.aliases["web"] = lambda args: webbrowser.open(*args)
    xsh.aliases["webn"] = lambda args: webbrowser.open_new(*args)
    xsh.aliases["webw"] = "webn"
    xsh.aliases["webt"] = lambda args: webbrowser.open_new_tab(*args)
