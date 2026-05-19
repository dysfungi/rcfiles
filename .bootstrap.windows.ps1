# Bootstrap script for Windows. Requires Administrator for Developer Mode and WSL.
# Exits gracefully when not elevated — chezmoi operations should not be blocked.
Write-Host "INFO: Starting $PSCommandPath"
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Host "INFO: Not running as Administrator. Skipping bootstrap (run as Admin to provision)." -ForegroundColor Yellow
    Write-Host "INFO: Ending $PSCommandPath"
    exit 0
}

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

# 3. Install 1Password and Git (Early dependencies)
Write-Host "Installing 1Password and Git..."
$packages = @("AgileBits.1Password", "AgileBits.1Password.CLI", "Git.Git")
foreach ($package in $packages) {
    winget install --id $package --silent --accept-package-agreements --accept-source-agreements
}

# 4. Install WSL with desired Linux distribution (no interactive launch; user setup handled by chezmoi)
$wslDistro = if ($args.Count -gt 0) { $args[0] } else { "archlinux" }
Write-Host "Checking WSL $wslDistro distribution..."
$ErrorActionPreference = "Continue"
wsl -d $wslDistro -- true 2>$null
$ErrorActionPreference = "Stop"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing $wslDistro..."
    wsl --install --distribution $wslDistro --no-launch
    wsl --set-default $wslDistro
    Write-Host "Done. Run 'chezmoi apply' to complete WSL user setup."
} else {
    Write-Host "$wslDistro already installed. Skipping."
}
Write-Host "INFO: Ending $PSCommandPath"
