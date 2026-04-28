# My Dot and RC Files

[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)

## Setting Up a New Machine

Unfortunately, bootstrapping requires installing a couple things manually, so follow the platform-specific instructions and then follow [setup new machine][chez-new-machine].

### Unix-like

Use one of the [Chezmoi one-line install methods](https://www.chezmoi.io/install/#one-line-binary-install) unless Homebrew is already installed.

### Windows

Open Powershell and run:

```ps1
winget install twpayne.chezmoi AgileBits.1Password
```

For first-time bootstrapping with 1Password service mode, set the token in the
PowerShell session before running `chezmoi init`:

```ps1
$env:OP_SERVICE_ACCOUNT_TOKEN = Read-Host "OP_SERVICE_ACCOUNT_TOKEN"
chezmoi init <repo>
Remove-Item Env:OP_SERVICE_ACCOUNT_TOKEN
```

Or write the token once to `~/.secrets/OP_SERVICE_ACCOUNT_TOKEN`:

```ps1
$token = Read-Host "OP_SERVICE_ACCOUNT_TOKEN"
$secretDir = Join-Path $HOME ".secrets"
New-Item -ItemType Directory -Path $secretDir -Force | Out-Null
Set-Content -LiteralPath (Join-Path $secretDir "OP_SERVICE_ACCOUNT_TOKEN") -NoNewline -Value $token
```

[chez-new-machine]: https://www.chezmoi.io/user-guide/daily-operations/#install-chezmoi-and-your-dotfiles-on-a-new-machine-with-a-single-command
