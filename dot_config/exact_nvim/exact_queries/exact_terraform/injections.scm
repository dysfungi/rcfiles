; Override HCL's heredoc injection: the default tries to load a parser named
; after the heredoc identifier (JSON, EOF, EOT, etc.) on every cursor movement,
; which freezes Neovim when the named parser isn't installed.
