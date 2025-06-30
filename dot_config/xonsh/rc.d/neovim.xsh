from xonsh.built_ins import XSH


if $(command -v nvim):
    XSH.aliases["vi"] = "nvim"
    XSH.aliases["vim"] = "nvim"
