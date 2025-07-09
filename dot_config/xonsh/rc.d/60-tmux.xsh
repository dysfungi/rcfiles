from _utils import rc


@rc(interactive=True)
def __rc_interactive(xsh):
    xsh.aliases["tmx"] = "tmux attach -t @($args) || tmux new -s @($args)"
    xsh.aliases["tmu"] = ["tmx"]
