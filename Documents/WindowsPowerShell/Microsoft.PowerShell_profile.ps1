# Deliver mise [env] vars (incl. ~/.config/mise/conf.d/secrets.toml).
# `mise env -s pwsh` emits PowerShell-compatible $env:NAME="..." assignments
# (safe on both PowerShell 7+ and Windows PowerShell 5.1).
if (Get-Command mise -ErrorAction SilentlyContinue) { mise env -s pwsh | Out-String | Invoke-Expression }
