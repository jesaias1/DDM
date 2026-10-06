$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$python = "$PSScriptRoot\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Koer INSTALL_DDM.ps1 foerst." }
if (Test-Path -LiteralPath "$PSScriptRoot\.env.local.ps1") {
    . "$PSScriptRoot\.env.local.ps1"
} else {
    $env:DDM_LIVE = "0"
    $env:SMARTSTAKE_LIVE = "0"
    Write-Host "Starter uden rigtige kryptohandler."
}
Write-Host "Lokal terminal: http://127.0.0.1:5000 (Ctrl+C stopper serveren)"
& $python "$PSScriptRoot\app.py"
if ($LASTEXITCODE -ne 0) { throw "Serveren stoppede med en fejl." }
