# Bootstrap script for Windows. Requires Administrator for Developer Mode and WSL.
# Exits silently when not elevated or when all bootstrap deps are already present.
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")
if (-not $isAdmin) { exit 0 }

$wslDistro = if ($args.Count -gt 0) { $args[0] } else { "archlinux" }

# Fast-path: skip if 1Password CLI, Git, mise, uv, and WSL distro are already installed
$opOk   = (Get-Command op   -ErrorAction SilentlyContinue) -ne $null
$gitOk  = (Get-Command git  -ErrorAction SilentlyContinue) -ne $null
$miseOk = (Get-Command mise -ErrorAction SilentlyContinue) -ne $null
$uvOk   = (Get-Command uv   -ErrorAction SilentlyContinue) -ne $null
$ErrorActionPreference = "Continue"
wsl -d $wslDistro -- true 2>$null | Out-Null
$wslOk = $LASTEXITCODE -eq 0
$ErrorActionPreference = "Stop"
if ($opOk -and $gitOk -and $miseOk -and $uvOk -and $wslOk) { exit 0 }

Write-Host "INFO: Starting $PSCommandPath"

# 1. Enable Developer Mode (Registry)
Write-Host "Enabling Developer Mode..."
$registryPath = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock"
if (-not (Test-Path $registryPath)) {
    New-Item -Path $registryPath -Force | Out-Null
}
Set-ItemProperty -Path $registryPath -Name "AllowDevelopmentShortcut" -Value 1
Set-ItemProperty -Path $registryPath -Name "AllowAllTrustedApps" -Value 1

# 2. Grant SeCreateSymbolicLinkPrivilege (User Rights Assignment)
Write-Host "Granting SeCreateSymbolicLinkPrivilege..."
$sid = ([System.Security.Principal.WindowsIdentity]::GetCurrent()).User.Value
$tempFile = [System.IO.Path]::GetTempFileName()
$dbFile = [System.IO.Path]::GetTempFileName()

# Export current security policy
secedit /export /cfg $tempFile /areas USER_RIGHTS | Out-Null

# Append current user SID to SeCreateSymbolicLinkPrivilege line
$content = Get-Content $tempFile -Encoding Unicode
if ($content -match "SeCreateSymbolicLinkPrivilege") {
    $content = $content -replace "(SeCreateSymbolicLinkPrivilege = .*)$", "`$1,$sid"
} else {
    $content += "SeCreateSymbolicLinkPrivilege = $sid"
}
$content | Set-Content $tempFile -Encoding Unicode

# Import and apply updated policy
secedit /import /db $dbFile /cfg $tempFile | Out-Null
secedit /configure /db $dbFile /cfg $tempFile /areas USER_RIGHTS | Out-Null

# Cleanup
Remove-Item $tempFile, $dbFile -ErrorAction SilentlyContinue

# 3. Install 1Password, Git, mise, and uv (early dependencies)
# mise must exist before chezmoi's stage-20 `mise install` runs.
# uv must exist before chezmoi's file-sync phase runs modify_* scripts.
# Both declared in .chezmoidata/packages.yaml and bootstrapped here.
Write-Host "Installing 1Password, Git, mise, and uv..."
$packages = @("AgileBits.1Password", "AgileBits.1Password.CLI", "Git.Git", "jdx.mise", "astral-sh.uv")
foreach ($package in $packages) {
    winget install --id $package --silent --accept-package-agreements --accept-source-agreements
}

# 4. Install WSL with desired Linux distribution (no interactive launch; user setup handled by chezmoi)
Write-Host "Checking WSL $wslDistro distribution..."
$ErrorActionPreference = "Continue"
wsl -d $wslDistro -- true 2>$null
$ErrorActionPreference = "Stop"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing $wslDistro..."
    wsl --install --distribution $wslDistro --no-launch
    wsl --set-default $wslDistro
    Write-Host "Done. chezmoi will complete WSL user setup in a later script."
} else {
    Write-Host "$wslDistro already installed. Skipping."
}
Write-Host "INFO: Ending $PSCommandPath"
