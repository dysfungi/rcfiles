# Ensure the machine has a per-host SSH keypair at ~/.ssh/id_ed25519{,.pub}.
#
# Native-Windows counterpart of run_before_generate-ssh-key.unix-like.sh. Same
# honest model: generate ONCE, never touch an existing key, and always DERIVE
# the .pub from the private key so the two halves can never drift. run_before_
# so the keypair exists before the run_onchange_after_ GitHub registration
# scripts read it.
#
# Best-effort: SSH provisioning problems WARN and exit 0 rather than aborting the
# whole `chezmoi apply` (the memory-external abort was the lesson here). A key
# that isn't generated just means the register scripts no-op; nothing else
# breaks (the memory external is gated off Windows).
$ErrorActionPreference = "Stop"
Write-Host "INFO: Starting $PSCommandPath"

try {
    # ssh-keygen ships with Windows OpenSSH (System32) and Git for Windows.
    if (-not (Get-Command ssh-keygen -ErrorAction SilentlyContinue)) {
        Write-Host "WARN: ssh-keygen not found (install the Windows OpenSSH Client feature or Git for Windows); skipping SSH key generation." -ForegroundColor Yellow
        Write-Host "INFO: Ending $PSCommandPath"
        exit 0
    }

    $sshDir = Join-Path $HOME ".ssh"
    $key = Join-Path $sshDir "id_ed25519"
    $pub = "$key.pub"
    $comment = "Windows:$env:USERNAME@$env:COMPUTERNAME"

    if (-not (Test-Path $sshDir)) {
        New-Item -ItemType Directory -Path $sshDir -Force | Out-Null
    }

    # Generate ONLY when the private key is genuinely absent/empty on disk —
    # decide on the real file, never on an external signal. Existing keys are
    # never touched. `-N '""'` is the Windows idiom for an empty passphrase
    # (PowerShell forwards the literal "" which ssh-keygen reads as empty).
    if (-not (Test-Path $key) -or ((Get-Item $key).Length -eq 0)) {
        Write-Host "INFO: no SSH key at $key; generating a fresh ed25519 keypair."
        ssh-keygen -t ed25519 -C $comment -N '""' -f $key -q
    }

    # Keep .pub in sync with the private key (source of truth), rewriting only on
    # drift so re-runs are no-ops. Write LF explicitly (avoid CRLF in the key).
    $want = "$(ssh-keygen -y -f $key) $comment"
    $current = if (Test-Path $pub) { (Get-Content -Raw $pub).Trim() } else { "" }
    if ($current -ne $want) {
        Write-Host "INFO: (re)deriving $pub from the private key."
        [System.IO.File]::WriteAllText($pub, "$want`n")
    }

    # Windows OpenSSH refuses private keys with loose ACLs. Restrict to the
    # current account only: reset inheritance and replace grants in one call.
    # Use the full identity name (DOMAIN\user) so it works for domain accounts.
    $acct = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    icacls $key /inheritance:r /grant:r "${acct}:F" | Out-Null
}
catch {
    Write-Host "WARN: SSH key generation failed: $_" -ForegroundColor Yellow
}

Write-Host "INFO: Ending $PSCommandPath"
