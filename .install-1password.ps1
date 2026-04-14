# Force loud failure if not running as Administrator
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Error "CRITICAL: This script must be run as Administrator to enable Developer Mode and install packages."
    Write-Host "Please restart your PowerShell session as Administrator and try again." -ForegroundColor Red
    exit 1
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

winget install --id AgileBits.1Password --silent --accept-package-agreements --accept-source-agreements
