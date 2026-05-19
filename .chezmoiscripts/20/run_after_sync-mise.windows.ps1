$ErrorActionPreference = "Stop"
Write-Host "INFO: Starting $PSCommandPath"

if (-not (Get-Command mise -ErrorAction SilentlyContinue)) {
    Write-Host "WARN: mise not found; skipping. Re-run 'chezmoi apply' after mise is installed." -ForegroundColor Yellow
    Write-Host "INFO: Ending $PSCommandPath"
    exit 0
}

mise install
mise upgrade

Write-Host "INFO: Ending $PSCommandPath"
