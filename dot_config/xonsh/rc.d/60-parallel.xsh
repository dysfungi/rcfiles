from _utils import rc


@rc(interactive=True)
def __rc_interactive(xsh):
    xsh.aliases["rp"] = "rust-parallel"
    xsh.aliases["rpar"] = "rust-parallel"
    xsh.aliases["rparallel"] = "rust-parallel"
    xsh.aliases["parallelr"] = "rust-parallel"
