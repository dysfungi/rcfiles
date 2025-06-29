from xonsh.built_ins import XSH


XSH.aliases["tmx"] = "tmux attach -t @($args) || tmux new -s @($args)"
XSH.aliases["tmu"] = ["tmx"]
