# Shared PowerShell helper: Register-SshKey -GhHost <host> -Token <token>
#
# Native-Windows counterpart of github/register-ssh-key.sh, included verbatim
# via `includeTemplate "github/register-ssh-key.ps1"` into each caller .tmpl.
#
# Arguments:
#   -GhHost  GitHub hostname. Empty string -> github.com (uses GH_TOKEN).
#            Non-empty -> GitHub Enterprise Server (GH_HOST + GH_ENTERPRISE_TOKEN).
#   -Token   PAT with admin:public_key or write:public_key scope.
#
# Behaviour & WHY (mirrors the bash helper):
#   - Derives the public key from the PRIVATE key (ssh-keygen -y), the source of
#     truth, so we can never upload an orphan public key whose private half is
#     missing/unusable.
#   - ADD-ONLY: never deletes existing keys. Stale per-host entries are pruned
#     manually.
#   - Idempotent: skips if the key body is already registered on the target host.
#   - Best-effort: missing key / tool / network / bad token WARN and return
#     rather than throwing (callers must not abort `chezmoi apply`).
#   - Title "Windows:$USERNAME@$COMPUTERNAME" — distinct from the WSL key's
#     "Linux:..." title, so both coexist on GitHub with no collision.
function Register-SshKey {
    param(
        [string]$GhHost,
        [string]$Token
    )

    $label = if ($GhHost) { $GhHost } else { "github.com" }
    $key = Join-Path $HOME ".ssh\id_ed25519"
    $pub = "$key.pub"

    if (-not (Test-Path $key) -or ((Get-Item $key).Length -eq 0)) {
        Write-Host "WARN: $key missing; cannot register SSH key on $label." -ForegroundColor Yellow
        return
    }
    foreach ($tool in @("ssh-keygen", "gh")) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
            Write-Host "WARN: $tool not found; skipping $label registration." -ForegroundColor Yellow
            return
        }
    }

    # Source of truth: derive the public half from the private key.
    $pubLine = ssh-keygen -y -f $key 2>$null
    if (-not $pubLine) {
        Write-Host "WARN: $key is not a usable private key; skipping $label registration." -ForegroundColor Yellow
        return
    }
    $keyBody = ($pubLine -split '\s+')[1]
    $keyTitle = "Windows:$env:USERNAME@$env:COMPUTERNAME"

    # Minimal env for gh against the target host: GH_TOKEN for github.com;
    # GH_HOST + GH_ENTERPRISE_TOKEN for a self-hosted Enterprise Server.
    $ghEnv = @{}
    if ($GhHost) {
        $ghEnv["GH_HOST"] = $GhHost
        $ghEnv["GH_ENTERPRISE_TOKEN"] = $Token
    }
    else {
        $ghEnv["GH_TOKEN"] = $Token
    }

    try {
        foreach ($name in $ghEnv.Keys) { Set-Item "env:$name" $ghEnv[$name] }

        $listed = gh ssh-key list 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "WARN: cannot reach $label (network/token); skipping SSH key registration." -ForegroundColor Yellow
            return
        }
        if ($listed -match [regex]::Escape($keyBody)) {
            Write-Host "INFO: SSH public key already registered on $label; skipping."
            return
        }
        gh ssh-key add $pub --title $keyTitle --type authentication 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "INFO: SSH public key added to $label as '$keyTitle'."
        }
        else {
            Write-Host "WARN: failed to add SSH key to $label; existing keys left untouched." -ForegroundColor Yellow
        }
    }
    finally {
        foreach ($name in $ghEnv.Keys) { Remove-Item "env:$name" -ErrorAction SilentlyContinue }
    }
}
