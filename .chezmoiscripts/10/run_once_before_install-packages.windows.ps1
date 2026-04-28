# Self-elevate the script if required
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    $arguments = "& '" + $MyInvocation.MyCommand.Definition + "'"
    Start-Process powershell -Verb runAs -ArgumentList $arguments
    break
}

Write-Host "Installing Windows packages with winget..."

$packages = @(
    "BurntSushi.ripgrep.MSVC",
    "Git.Git",
    "GitHub.cli",
    "jdx.mise",
    "LLVM.LLVM", # for clangd / Unreal development
    "Mamba.Micromamba",
    "Neovim.Neovim",
    "sharkdp.fd",
    "wez.wezterm"
)

foreach ($package in $packages) {
    Write-Host "Checking $package..."
    # Using --accept-package-agreements and --accept-source-agreements to avoid interactive prompts
    winget install --id $package --silent --accept-package-agreements --accept-source-agreements
}

# Set XDG_CONFIG_HOME to ~/.config to keep things consistent with Mac/Linux
$configHome = Join-Path $HOME ".config"
if (-not (Test-Path $configHome)) {
    New-Item -ItemType Directory -Path $configHome -Force
}

# Persist for future sessions (User scope)
[Environment]::SetEnvironmentVariable("XDG_CONFIG_HOME", $configHome, "User")
$env:XDG_CONFIG_HOME = $configHome

Write-Host "Windows package installation complete."
