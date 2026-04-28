$secretsDir = Join-Path $HOME ".secrets"
if (-not (Test-Path -LiteralPath $secretsDir -PathType Container)) {
    return
}

Get-ChildItem -LiteralPath $secretsDir -File | ForEach-Object {
    $name = $_.Name
    if ($name -match '^[A-Za-z_][A-Za-z0-9_]*$') {
        $envPath = "Env:$name"
        if (-not (Test-Path -LiteralPath $envPath)) {
            $value = (Get-Content -LiteralPath $_.FullName -Raw).Trim()
            if (-not [string]::IsNullOrWhiteSpace($value) -and -not $value.StartsWith("op://")) {
                Set-Item -LiteralPath $envPath -Value $value
            }
        }
    }
}
