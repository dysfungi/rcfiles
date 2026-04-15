# Self-elevate the script if required
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    $arguments = "& '" + $MyInvocation.MyCommand.Definition + "'"
    Start-Process powershell -Verb runAs -ArgumentList $arguments
    break
}

$fontDir = "$env:LOCALAPPDATA\Microsoft\Windows\Fonts\Iosevka"
$registryPath = "HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Fonts"

if (Test-Path $fontDir) {
    Write-Host "Registering Iosevka fonts..."
    Get-ChildItem -Path $fontDir -Include "*.ttc", "*.ttf", "*.otf" -Recurse | ForEach-Object {
        $fontName = $_.Name
        $fontPath = $_.FullName

        # Check if already registered
        if (-not (Get-ItemProperty -Path $registryPath -Name $fontName -ErrorAction SilentlyContinue)) {
            Set-ItemProperty -Path $registryPath -Name $fontName -Value $fontPath
            Write-Host "Registered: $fontName"
        }
    }
}
