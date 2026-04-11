# Force loud failure if not running as Administrator
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Error "CRITICAL: This script must be run as Administrator to enable Developer Mode and install packages."
    Write-Host "Please restart your PowerShell session as Administrator and try again." -ForegroundColor Red
    exit 1
}

winget install --id AgileBits.1Password --silent --accept-package-agreements --accept-source-agreements
