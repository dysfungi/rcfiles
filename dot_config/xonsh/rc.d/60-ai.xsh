from _utils import rc


@rc(interactive=True)
def __rc_interactive(xsh):
    xsh.aliases["ai"] = xsh.aliases["fabric"] = "fabric-ai"

    for pattern in $(fabric-ai --listpatterns).splitlines():
        xsh.aliases[pattern] = ["fabric-ai", f"--pattern={pattern}"]

    xsh.aliases["ai-patterns"] = xsh.aliases["aipatterns"] = xsh.aliases["patterns"] = [
        "fzf",
        "--preview=cat {}",
        "--walker-root=$HOME/.config/fabric/patterns",
        # "--preview-window=up:50%:wrap",
    ]
    xsh.aliases["ai-strategies"] = xsh.aliases["aistrategies"] = xsh.aliases["strategies"] = [
        "fzf",
        "--preview=cat {}",
        "--walker-root=$HOME/.config/fabric/strategies",
    ]
